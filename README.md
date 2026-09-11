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

## Estructura

```
docs/                       Especificación, un archivo por responsabilidad
examples/
  agents/                   Payloads de creación de agente y subagentes
  threads/                  Payloads y respuestas del contrato de conversación
  mcp/                      Configuración de sandbox + servidores MCP
scripts/
  eve_api_curl.sh           Flujo completo ejecutable (incluye reintento ante 409)
  hello_from_sandbox.py     Script de prueba del sandbox
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
| 2 | Tool-calling contra el MCP real del GCS (`allowed_tools` por subagente) | Pendiente |
| 3 | Sandbox Python con caso de uso real | Pendiente |
| 4 | Ciclo de vida y resiliencia (timeouts, límites de iteración) | Pendiente |
| 5 | Resultado del subagente hacia el thread padre | Pendiente |
| 6 | Consolidación final | Pendiente |
