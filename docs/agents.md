# Agentes y subagentes

Define la topología de agentes del sistema y dónde vive cada pieza.

## Decisiones de arquitectura

1. **Un agente raíz fijo.** En eve el agente *es* el directorio `agent/`: se
   compila y se deploya, no se crea por API. Atiende todas las conversaciones
   del GCS; la separación entre conversaciones la dan las sesiones.
2. **Los perfiles son subagentes declarados, con tools propias.** `default` y
   `planner` existen en `multiuav_gcs` como perfiles markdown
   (`server/models/chat/agents/*.md`, con frontmatter `allowedTools` y
   `capability`). Acá `default` es el agente raíz y `planner` un subagente bajo
   `agent/subagents/planner/`.
3. **Aislamiento total del subagente.** Un subagente declarado **no hereda nada**
   del raíz: ni instructions, ni tools, ni connections, ni sandbox. Lo que
   necesita, lo declara en su propio directorio. Eso es lo que hace que la
   separación de permisos sea real y no una convención.

## El agente raíz (operador)

| Pieza | Archivo |
| ----- | ------- |
| Modelo | [`agent/agent.ts`](../agent/agent.ts) — provider directo (Gemini u OpenAI según la API key) |
| System prompt | [`agent/instructions.md`](../agent/instructions.md) — portado de `default.md` |
| Tools del GCS | [`agent/connections/multiuav-gcs.ts`](../agent/connections/multiuav-gcs.ts) |
| Delegación | [`agent/tools/request_mission_plan.ts`](../agent/tools/request_mission_plan.ts) |
| Canal HTTP | [`agent/channels/eve.ts`](../agent/channels/eve.ts) |

Atiende al operador, ejecuta tools de vuelo directas (con aprobación humana en
las que mandan a los UAVs) y delega la planificación.

## El subagente `planner`

| Pieza | Archivo |
| ----- | ------- |
| Config + `description` | [`agent/subagents/planner/agent.ts`](../agent/subagents/planner/agent.ts) |
| System prompt | [`agent/subagents/planner/instructions.md`](../agent/subagents/planner/instructions.md) — portado de `planner.md` |
| Sus tools | [`agent/subagents/planner/connections/multiuav-gcs.ts`](../agent/subagents/planner/connections/multiuav-gcs.ts) |

Dos detalles que impone eve:

- **`description` es obligatoria** y el compilador rechaza el subagente sin
  ella: es lo que lee el padre para decidir si delega.
- **El nombre del directorio es el nombre de la tool.** `agent/subagents/planner/`
  se registra como la tool `planner`, en el mismo namespace que las tools
  autoradas — por eso un subagente y una tool no pueden llamarse igual.

Usa el modelo más capaz disponible (`capability: high` en el original): la
planificación es geometría 3D, coste de rutas y reparación iterativa.

## Tools por agente

| Agente | Tools |
| ------ | ----- |
| raíz | `get_devices`, `get_fleet_telemetry`, `get_registered_objects`, `get_element_groups`, `get_bases_with_assignments`, `show_mission_to_user`, `load_mission_to_uav`, `start_mission` + `request_mission_plan` (propia) |
| `planner` | `mark_step_complete`, `validate_mission` |

Las allowlists son disjuntas a propósito: el operador no puede planificar a mano
y el planner no puede arrancar misiones. Inventario completo y transporte en
[tools.md](tools.md).

## Delegación

El raíz delega con `request_mission_plan`, un background workflow tool que
valida y convierte el briefing antes de invocar al `planner`. Contrato completo
en [delegation.md](delegation.md).
