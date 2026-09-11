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
agent/                      El agente eve (el framework compila este directorio)
  agent.ts                  Configuración runtime (modelo, opciones)
  instructions.md           System prompt del agente principal
  instrumentation.ts        Observabilidad (OTel; local automática)
  channels/                 Entrada HTTP (canal eve por defecto)
  connections/              Conexiones MCP/OpenAPI (→ mcp_server de multiuav)
  tools/                    Tools tipadas propias
  skills/                   Procedimientos reutilizables
  subagents/                Subagentes (→ planner)
  sandbox/
    sandbox.ts              Definición del sandbox
    workspace/tools/        Smoke test (sembrado en /workspace/tools)
    workspace/pipeline/     Pipeline de planificación, steps 2/4/5 (→ /workspace/pipeline)
  hooks/  lib/  schedules/  Ciclo de vida, código compartido, tareas recurrentes
docs/                       Especificación, un archivo por responsabilidad
examples/
  agents/                   Payloads de creación de agente y subagentes
  threads/                  Payloads y respuestas del contrato de conversación
  mcp/                      Configuración de servidores MCP
  sandbox/                  Configs de sandbox por agente + datos de ejemplo
scripts/
  eve_api_curl.sh           Flujo completo ejecutable (incluye reintento ante 409)
```

## Uso rápido

Requisitos: Node 24 (`nvm use 24`) y una API key de Gemini u OpenAI.

```bash
# 1. Crear .env en la raíz con UNA de las dos keys (Gemini tiene prioridad):
#    GOOGLE_GENERATIVE_AI_API_KEY=...   (https://aistudio.google.com/apikey)
#    OPENAI_API_KEY=...                 (https://platform.openai.com/api-keys)
#    EVE_MODEL=gemini-2.5-pro           (opcional; defaults: gemini-2.5-flash / gpt-5.1)

# 2. Instalar y correr
nvm use 24
npm install
npm run dev          # REPL interactivo en la terminal

# Servidor HTTP sin UI (lo que consumirá el GCS):
npm exec -- eve dev --no-ui         # http://127.0.0.1:2000
#   POST /eve/v1/session                    → crea sesión y manda el primer mensaje
#   GET  /eve/v1/session/:id/stream         → respuesta en streaming
#   POST /eve/v1/session/:id                → mensajes siguientes

# Deploy local (self-hosted, sin Vercel):
npm run build && npm run start
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
