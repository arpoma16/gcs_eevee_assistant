# gcs_eevee_assistant

Especificación e implementación de la integración entre **EVE** (plataforma de
agentes) y el GCS multi-UAV (`multiuav_gcs`). EVE reemplaza al orquestador de
chat actual del GCS (`chat.js` + `subAgentManager.js` + `mcpClient.js`):
threads, loop de tools, subagentes y sandbox pasan a vivir en EVE, y el GCS
queda como cliente de su API.

## Documentación

Cada documento cubre una sola responsabilidad:

| Documento | Contenido |
| --------- | --------- |
| [`docs/setup.md`](docs/setup.md) | Variables de entorno, autenticación y convenciones. |
| [`docs/agents.md`](docs/agents.md) | Agente principal fijo y subagentes (`planner`). |
| [`docs/conversation.md`](docs/conversation.md) | Contrato de threads y mensajes: endpoints, esquema normalizado, concurrencia (`409`). |
| [`docs/tools.md`](docs/tools.md) | MCP real del GCS: transportes, inventario de tools, `allowed_tools` por agente. |
| [`docs/sandbox.md`](docs/sandbox.md) | Sandbox Python: pipeline de waypoints, datos como archivos, config por agente. |
| [`docs/lifecycle.md`](docs/lifecycle.md) | Ciclo de vida: límites por agente, timeouts, reporte de errores, expiración. |
| [`docs/delegation.md`](docs/delegation.md) | Delegación nativa y resultado asíncrono del subagente al thread padre. |

## Estructura

```
docs/                       Especificación, un archivo por responsabilidad
examples/
  agents/                   Payloads de creación de agente y subagentes
  threads/                  Payloads y respuestas del contrato de conversación
  mcp/                      Configuración de servidores MCP
  sandbox/                  Configs de sandbox por agente + datos de ejemplo
scripts/
  eve_api_curl.sh           Flujo completo ejecutable (incluye reintento ante 409)
  sandbox/common/           Smoke test del sandbox
  sandbox/pipeline/         Pipeline de planificación (steps 2, 4 y 5 como scripts)
```

## Uso rápido

```bash
export EVE_BASE_URL="https://<host-de-tu-tenant-eve>"
export EVE_API_KEY="<api-key>"
./scripts/eve_api_curl.sh
```

## Estado del proyecto

| Fase | Alcance | Estado |
| ---- | ------- | ------ |
| 1 | Contrato de conversación (threads, mensajes, 409) | Hecho |
| 2 | Tool-calling contra el MCP real del GCS (`allowed_tools` por subagente) | Hecho |
| 3 | Sandbox Python con caso de uso real | Hecho |
| 4 | Ciclo de vida y resiliencia (timeouts, límites de iteración) | Hecho |
| 5 | Resultado del subagente hacia el thread padre | Hecho |
| 6 | Consolidación final | Hecho |
