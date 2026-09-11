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

### Configuración en EVE

- Config real: [`examples/mcp/gcs_mcp_config.json`](../examples/mcp/gcs_mcp_config.json)

El esquema de `mcp_servers` heredado solo soportaba procesos locales
(`command`/`args`/`env`). Se extiende con entradas remotas:

```json
{
  "type": "http",
  "url": "${GCS_MCP_URL}",
  "headers": {
    "Authorization": "Bearer ${GCS_MCP_TOKEN}"
  }
}
```

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

## `allowed_tools` por agente

Cada subagente declara sus tools permitidas en su payload de creación
(campo `allowed_tools`), espejo del frontmatter `allowedTools` de
`multiuav_gcs/server/models/chat/agents/*.md`:

| Agente | Payload | Tools |
| ------ | ------- | ----- |
| principal (`default`) | [`agent_payload.json`](../examples/agents/agent_payload.json) | `get_devices`, `get_fleet_telemetry`, `get_registered_objects`, `get_element_groups`, `show_mission_to_user`, `load_mission_to_uav`, `start_mission` + delegación nativa en `planner` |
| `planner` | [`subagent_planner_payload.json`](../examples/agents/subagent_planner_payload.json) | `submit_mission_plan`, `validate_mission` |

Notas:

- El listado es **allowlist estricta**: toda tool no listada es invisible para
  ese agente. Es lo que impide que el agente principal llame
  `submit_mission_plan` o que el planner arranque misiones.
- El perfil `planner` de EVE adopta la variante **single-turn**
  (`plannerFast` en multiuav_gcs: razona los 5 pasos y entrega con un solo
  `submit_mission_plan`, luego `validate_mission`). La variante turno-a-turno
  (`mark_step_complete`, hasta 18 iteraciones) queda como alternativa si el
  modelo pierde calidad al razonar todo junto — el tradeoff es
  costo/latencia (N llamadas) contra trazabilidad paso a paso.
