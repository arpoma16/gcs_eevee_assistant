# Delegación y resultados asíncronos (subagente → thread padre)

Define cómo el agente principal delega en un subagente y cómo el resultado
vuelve al thread padre. Reemplaza el mecanismo actual de `multiuav_gcs`
(tools MCP `request_mission_plan`/`delegate_mission_plan_generation` que
rebotan por REST a `/chat/subagents`) por delegación **nativa de EVE**,
conservando su semántica — que es la parte que ya funciona.

## Modelo: asíncrono, como hoy

La delegación **no bloquea** el turno del padre:

```
Thread padre (operador)                    Thread hijo (planner)
──────────────────────                     ─────────────────────
turno N:
  tool_call  delegate_to_planner ──────▶   se crea thread hijo
  tool_result "started" (child_thread_id)    (parent_thread_id enlazado)
  text "Planificando la misión…"             corre con SUS límites (18 it / 900 s)
  [turno N termina → idle]                   pipeline sandbox + validate_mission
                                                    │
turno N+1 (disparado por EVE):   ◀──────── resultado (éxito o error)
  subagent_result                          thread hijo queda solo-lectura
  tool_call  show_mission_to_user
  text "Plan listo: 2 rutas, sin colisiones…"
```

El operador puede seguir conversando entre el turno N y el N+1: el thread
padre está `idle` mientras el planner trabaja.

## La tool de delegación

Por cada subagente registrado (`POST /v1/agents/{agentId}/subagents`), EVE
expone automáticamente al agente padre una tool interna
`delegate_to_<subagent_name>`. No es una tool MCP: no pasa por el GCS.

Input de la delegación:

| Campo | Qué es |
| ----- | ------ |
| `task` | El encargo en lenguaje natural (equivale al `mission_strategy_description` actual: intención, framing, viewpoints, altitud, constraints). |
| `context_files` | Datos estructurados que EVE **materializa como archivos** en el sandbox del hijo (`/workspace/data/mission_input.json`), sin pasar por el contexto del modelo. Es el reemplazo directo de los `contextParams` de `subAgentRegistry` — mismo objetivo: datos que el modelo no puede corromper. |

El `tool_result` inmediato solo confirma el arranque:
`{ "status": "started", "subagent_thread_id": "thr_child_1" }`. El thread hijo
es consultable por `GET /threads/{childId}` y `GET /threads/{childId}/messages`
(la UI puede mostrar el progreso del planner en vivo con eso).

## El resultado: mensaje `subagent_result`

Cuando el hijo termina —éxito, error o timeout— EVE inyecta en el thread padre
un mensaje `subagent_result` y dispara un turno nuevo para que el padre lo
procese. Semántica heredada 1:1 de `SubAgentManager.injectSubAgentResponse`:

1. **Se añade, nunca se reescribe.** El par tool_call/tool_result de la
   delegación cerró en el turno N; el resultado llega como mensaje NUEVO.
   El historial es inmutable.
2. **`call_id` empareja resultado con delegación.** El `subagent_result` lleva
   el `call_id` del `tool_call` de delegación original — la UI reconstruye el
   hilo sin heurísticas, aunque hayan pasado turnos en el medio.
3. **El payload nunca lleva la misión.** El plan queda persistido en el GCS
   (tabla `MissionPlan`, vía `submit_mission_plan`); el resultado solo lleva el
   `missionPlanId`. Mismo convenio que documentan los perfiles actuales.
4. **La entrega es garantizada.** Si el padre está `running` cuando el hijo
   termina, EVE retiene el resultado y lo entrega al volver a `idle`. El `409`
   es el contrato con clientes externos; la inyección interna nunca pierde el
   resultado (hoy: `processMessage` encolando detrás del lock del padre).

Forma del mensaje en el historial (ejemplo completo con la secuencia de
delegación: [`examples/threads/delegation_sequence.json`](../examples/threads/delegation_sequence.json)):

```json
{
  "role": "user",
  "type": "subagent_result",
  "content": "{\"status\":\"valid\",\"description\":\"Mission plan generated and validated\",\"missionPlanId\":42,\"validationReport\":\"no collisions\",\"totalCollisions\":0}",
  "call_id": "call_07",
  "subagent": "eve-gcs-planner",
  "timestamp": "2026-09-11T10:12:40Z"
}
```

- `role: "user"` por la misma razón que en `messageProjection.js`: es el único
  rol que todo proveedor replica verbatim al modelo. La UI no debe renderizar
  por rol acá: **`type: "subagent_result"` es la clave de renderizado**, y
  `subagent` identifica quién lo produjo.
- `content` es un JSON string `{ status, description, ...payload }` con
  `status ∈ valid | error | incomplete`. Un planner que falla o agota sus
  límites produce `status: "error"` — el padre decide si reintenta la
  delegación o informa al operador.

## Cómo se entera el cliente

El GCS no recibe push en este contrato mínimo: consulta
`GET /threads/{threadId}/messages?after=<timestamp>` (parámetro incremental
sobre el endpoint de historial) tras ver `idle` en el estado, o en su ciclo
normal de refresco. Un canal de notificaciones (webhook/SSE de EVE) queda
explícitamente fuera de esta fase; si se agrega, no cambia este contrato —
solo elimina el polling.
