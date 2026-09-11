# Agentes y subagentes

Define la topología de agentes del sistema y sus payloads de creación.

## Decisiones de arquitectura

1. **Un agente EVE fijo y reutilizable.** Se crea una sola vez y atiende todas
   las conversaciones del GCS; la separación entre conversaciones la dan los
   threads (ver [conversation.md](conversation.md)), no agentes efímeros.
2. **Los perfiles son subagentes reales, con tools propias.** `default` y
   `planner` existen hoy en `multiuav_gcs` como perfiles markdown
   (`server/models/chat/agents/*.md`, con frontmatter `allowedTools` y
   `capability`). En EVE se implementan como subagentes con instrucciones y
   tools propias — no como metadata suelta sobre un agente genérico.
3. **Un sandbox por conversación**, compartido por el agente y sus subagentes
   dentro del mismo thread, persistente mientras el thread esté activo.

## Crear el agente principal

```
POST /v1/agents
```

Body: [`examples/agents/agent_payload.json`](../examples/agents/agent_payload.json)

El agente principal es el equivalente del perfil `default` de `multiuav_gcs`:
atiende al operador, ejecuta tools de vuelo directas y delega la planificación
de misiones en el subagente `planner`.

## Crear subagentes

```
POST /v1/agents/{agentId}/subagents
```

| Subagente | Payload | Rol (espejo en multiuav_gcs) |
| --------- | ------- | ---------------------------- |
| `planner` | [`examples/agents/subagent_planner_payload.json`](../examples/agents/subagent_planner_payload.json) | Perfil `planner`: construye y valida planes de misión. Tarea de razonamiento pesado → modelo de mayor capacidad. |

Las `instructions` de los payloads son resúmenes de arranque. Los system
prompts completos se portan desde `multiuav_gcs/server/models/chat/agents/`
(`default.md`, `planner.md`) cuando se cierre el flujo de la Fase 5.

## Tools por agente

Cada payload declara `allowed_tools` como allowlist estricta sobre el MCP real
del GCS. El inventario completo de tools, el mapeo por agente y la
configuración del transporte están en [tools.md](tools.md).

## Pendiente (fases siguientes)

- **Fase 5**: contrato del resultado del subagente hacia el thread padre
  (equivalente a `SubAgentManager.injectSubAgentResponse` de `multiuav_gcs`:
  el resultado se añade como mensaje `subagent_result` nuevo y el plan de
  misión viaja solo como referencia persistida, nunca embebido).
