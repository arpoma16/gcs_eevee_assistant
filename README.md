# gcs_eevee_assistant

Agente [eve](https://eve.dev) para el GCS multi-UAV (`multiuav_gcs`). Reemplaza
al orquestador de chat del GCS (`chat.js` + `subAgentManager.js` +
`mcpClient.js`): las sesiones, el loop de tools, los subagentes y el sandbox
pasan a vivir acá, y el GCS queda como servidor de tools MCP y cliente de las
sesiones de eve.

**El GCS sigue siendo dueño de la ejecución**: cargar una misión a los UAVs,
arrancarla, la telemetría y la persistencia de los planes no se mueven. El
agente piensa y decide; el GCS ejecuta.

## Documentación

| Documento | Contenido |
| --------- | --------- |
| [`docs/agents.md`](docs/agents.md) | Topología: agente raíz, subagente `planner`, y dónde vive cada pieza. |
| [`docs/tools.md`](docs/tools.md) | MCP real del GCS: transporte, inventario de tools, allowlist por agente, aprobación humana. |
| [`docs/delegation.md`](docs/delegation.md) | Delegación asíncrona al planner y camino de vuelta del `missionPlanId`. |
| [`docs/sandbox.md`](docs/sandbox.md) | Sandbox Python: para qué existe y el pipeline de waypoints (todavía sin conectar). |

## Estructura

```
agent/                      El agente eve (el framework compila este directorio)
  agent.ts                  Modelo (provider directo: Gemini u OpenAI)
  instructions.md           Identidad y comportamiento del operador
  instrumentation.ts        Observabilidad (OTel; local automática)
  channels/eve.ts           Entrada HTTP
  connections/              Conexión MCP al mcp_server de multiuav
  tools/                    request_mission_plan (delegación) y overrides de built-ins
  skills/                   mission-planning: el procedimiento, cargado bajo demanda
  subagents/planner/        El planificador, con sus propias instructions y tools
  sandbox/
    sandbox.ts              Definición del sandbox
    workspace/tools/        Smoke test         (→ /workspace/tools)
    workspace/pipeline/     Pipeline de planificación steps 2/4/5 (→ /workspace/pipeline)
  hooks/  lib/  schedules/  Vacíos por ahora
docs/                       Un archivo por responsabilidad
examples/pipeline/          Datos de ejemplo para correr el pipeline a mano
```

## Uso rápido

Requisitos: Node 24 (`nvm use 24`), una API key de Gemini u OpenAI, y el GCS
levantado (API en `:4000` y `mcp_server` en `:3001` con transporte http).

```bash
nvm use 24
npm install
npm run dev          # REPL interactivo en la terminal
```

Servidor HTTP sin UI (lo que consumirá el GCS):

```bash
npm exec -- eve dev --no-ui         # http://127.0.0.1:2000
#   POST /eve/v1/session                    → crea sesión y manda el primer mensaje
#   GET  /eve/v1/session/:id/stream         → respuesta en streaming
#   POST /eve/v1/session/:id                → mensajes siguientes
```

Deploy local, sin Vercel: `npm run build && npm run start`.

### Variables de entorno

En un `.env` en la raíz:

| Variable | Para qué | Default |
| -------- | -------- | ------- |
| `GOOGLE_GENERATIVE_AI_API_KEY` | Provider Gemini ([API key](https://aistudio.google.com/apikey)). Tiene prioridad si están las dos. | — |
| `OPENAI_API_KEY` | Provider OpenAI ([API key](https://platform.openai.com/api-keys)). | — |
| `EVE_MODEL` | Modelo del agente operador. | `gemini-2.5-flash` / `gpt-5.1` |
| `EVE_PLANNER_MODEL` | Modelo del planner (tarea de razonamiento pesado). | `gemini-3.1-pro-preview` / `gpt-5.1` |
| `GCS_MCP_URL` | Endpoint MCP del GCS. | `http://127.0.0.1:3001/mcp` |
| `MUAV_API_URL` | API REST del GCS, para resolver y convertir el briefing. | `http://localhost:4000/api` |
| `GCS_CHAT_ID` | Chat del GCS al que el mcp_server notifica cuando persiste un plan. Provisional: ver abajo. | — |

## Estado

Funciona y está verificado en vivo: el agente descubre las tools del GCS,
consulta flota y telemetría filtrando por estado, y despacha la planificación
con el briefing ya validado y convertido a XYZ.

Pendientes conocidos:

- **El planner nunca completó un plan de punta a punta.** Los 5 pasos, el loop
  de validación y la reparación de colisiones están sin ejecutar.
- **`GCS_CHAT_ID` es un parche.** El mcp_server, al persistir un plan, notifica
  a un chat del orquestador viejo; acá se le pasa un chat real para que no
  falle. El arreglo limpio vive en `mcp_server`, no en este repo.
- **El pipeline del sandbox no está conectado** (ver [`docs/sandbox.md`](docs/sandbox.md)).
- **Sin evals.** `evals/` y `npm run eval` están disponibles y sin usar.
