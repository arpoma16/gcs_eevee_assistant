# Tools: MCP real del GCS y permisos por agente

Define cómo EVE se conecta al MCP server real de `multiuav` y qué tools puede
usar cada agente. Nada de servidores de ejemplo: esta es la entrada real del
sistema.

## El MCP server de multiuav

Vive en `llm_planner_gcs/mcp_server` y expone las tools de dominio (drones,
misiones, planificación) consumiendo la API REST del GCS (`MUAV_API_URL`).

Transportes soportados (elegido por argumento de arranque, `src/index.ts`):

| Transporte | Arranque | Endpoint |
| ---------- | -------- | -------- |
| `stdio`  | `npx tsx src/index.ts stdio` | proceso local |
| `http`   | `npx tsx src/index.ts http`  | `POST/GET/DELETE http://<host>:3001/mcp` (Streamable HTTP, header `mcp-session-id`) |
| `sse`    | `npx tsx src/index.ts sse`   | `GET /sse` + `POST /messages` (una sola conexión; limitado) |

Para EVE el transporte es **`http`**: EVE corre fuera del proceso del GCS y
`stdio` no aplica. `sse` queda descartado: la implementación actual soporta una
única conexión simultánea.

### Configuración en eve

La conexión vive en [`agent/connections/multiuav-gcs.ts`](../agent/connections/multiuav-gcs.ts)
(`defineMcpClientConnection`). El nombre del archivo es el nombre de la
conexión, y solo admite minúsculas y guiones — de ahí `multiuav-gcs`, no
`multiuav_gcs`.

```ts
export default defineMcpClientConnection({
  url: process.env.GCS_MCP_URL ?? "http://127.0.0.1:3001/mcp",
  description: "…",              // esto es lo que lee connection_search
  tools: { allow: ALLOWED_TOOLS },
  approval: …,                   // gate humano en tools de vuelo
});
```

Cómo las ve el modelo: **no** recibe las tools de arranque. Las descubre con la
tool built-in `connection_search` (busca por keywords sobre la `description` de
la conexión y de cada tool) y después las llama por su nombre calificado,
`multiuav-gcs__get_devices`. Por eso la `description` de la conexión se escribe
para el modelo, no para el lector.

Levantar el MCP server antes de usar el agente:

```bash
cd llm_planner_gcs/mcp_server && npx tsx src/index.ts http   # :3001/mcp
```

### Aprobación humana en tools de vuelo

`load_mission_to_uav`, `start_mission` y `send_command` tienen
`approval: "user-approval"`: el turno se pausa y espera confirmación de una
persona antes de ejecutarlas. Todo lo demás (lectura, visualización,
validación) corre sin gate. La frontera es deliberada: **el agente piensa y
decide; nada que mueva un UAV real pasa sin que alguien lo apruebe.**

### Incompatibilidad verificada: `web_search` + Gemini

[`agent/tools/web_search.ts`](../agent/tools/web_search.ts) desactiva la tool
built-in `web_search`. Es *provider-defined*, y Gemini no soporta combinarlas
con function tools (`"combination of function and provider-defined tools is not
supported"`): con `web_search` activa, el agente **no emite ningún tool call** —
anuncia que va a buscar la herramienta y termina el turno. El agente opera
contra el GCS, no contra la web, así que no se pierde nada.

**Gap de seguridad, explícito**: el endpoint `/mcp` actual
(`src/httpStemeable.ts`) no valida ningún header de autenticación — solo
gestiona sesiones. Mientras EVE y el GCS compartan red confiable puede operar
así; en cuanto EVE sea un servicio externo, agregar la validación del
`Authorization` en el mcp_server es **prerrequisito de despliegue**, no un
opcional. El campo `headers` de la config ya lo deja preparado.

## Inventario de tools (nombres reales)

Fuente: `mcp_server/src/tools/`. Agrupadas por dominio:

| Dominio | Tool | Qué hace |
| ------- | ---- | -------- |
| Dispositivos | `get_devices` | Lista robots/UAVs registrados con estado de conexión. |
| Dispositivos | `download_device_camera_image` | Imagen en vivo de la cámara de un dispositivo. |
| Telemetría | `get_fleet_telemetry` | Última telemetría reportada (GPS, batería, modo de vuelo). |
| Comandos | `send_command` | Comando directo a un dispositivo. |
| Comandos | `get_available_commands` | Comandos disponibles por dispositivo. |
| Comandos | `send_task` | Tarea de inspección de alto nivel al GCS. |
| Misión | `load_mission_to_uav` | Carga un plan persistido (por `missionPlanId`) a los UAVs. |
| Misión | `start_mission` | Arranca la misión cargada. |
| Misión | `show_mission_to_user` | Muestra un plan persistido en la UI del operador. |
| Planificación | `get_element_groups` | Grupos de elementos registrados (liviano, sin coordenadas). |
| Planificación | `get_registered_objects` | Objetos registrados con coordenadas GPS. |
| Planificación | `get_bases_with_assignments` | Bases de operación con drones asignados. |
| Planner | `submit_mission_plan` | Entrega del plan completo (pasos 1–5) en un solo turno. |
| Planner | `mark_step_complete` | Avanza un paso lógico del plan (variante turno-a-turno). |
| Planner | `validate_mission` | Valida el plan XYZ contra la base de obstáculos 3D. |
| Planner | `show_mission_xyz` | Muestra un plan XYZ en el mapa para revisión. |

### Tools de delegación: NO se portan tal cual

`request_mission_plan` y `delegate_mission_plan_generation` existen en el
mcp_server, pero no son tools de dominio: son puntos de entrada de delegación
que llaman **de vuelta al orquestador viejo** (`POST /chat/subagents` y
`POST /chat/subagents/{chat_id}/inject` del GCS — `tools/missions.ts`).

Como EVE reemplaza a ese orquestador, estas dos tools quedan fuera del mapeo:
en EVE la delegación del agente principal al subagente `planner` es **nativa**
(mecanismo de subagentes de EVE), no una tool MCP que rebota por REST. El
contrato completo está en [delegation.md](delegation.md).

## Allowlist de tools

La conexión declara `tools: { allow: [...] }`: allowlist estricta, espejo del
frontmatter `allowedTools` de `multiuav_gcs/server/models/chat/agents/*.md`.
Toda tool que no esté listada es invisible para el modelo.

| Agente | Dónde se declara | Tools |
| ------ | ---------------- | ----- |
| principal (`default`) | [`agent/connections/multiuav-gcs.ts`](../agent/connections/multiuav-gcs.ts) | `get_devices`, `get_fleet_telemetry`, `get_registered_objects`, `get_element_groups`, `get_bases_with_assignments`, `get_available_commands`, `show_mission_to_user`, `show_mission_xyz`, `load_mission_to_uav`, `start_mission`, `validate_mission`, `submit_mission_plan` |
| `planner` | pendiente: `agent/subagents/planner/` | `submit_mission_plan`, `validate_mission` |

Notas:

- Hoy la allowlist es **única y compartida**, porque el agente principal es el
  único que existe. Al crear el subagente `planner` hay que separarlas: el
  principal pierde `submit_mission_plan`/`validate_mission` y el planner pierde
  todo lo demás. Eso es lo que impide que el principal planifique a mano o que
  el planner arranque misiones.
- El perfil `planner` adopta la variante **single-turn**
  (`plannerFast` en multiuav_gcs: razona los 5 pasos y entrega con un solo
  `submit_mission_plan`, luego `validate_mission`). La variante turno-a-turno
  (`mark_step_complete`, hasta 18 iteraciones) queda como alternativa si el
  modelo pierde calidad al razonar todo junto — el tradeoff es
  costo/latencia (N llamadas) contra trazabilidad paso a paso.
