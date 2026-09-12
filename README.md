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
  subagents/
    planner/                Razona la geometría (puerto de planner.md). Tools MCP.
    planner_sandbox/        La computa con un pipeline Python. Tools propias.
  sandbox/
    sandbox.ts              Definición del sandbox del agente raíz
    workspace/tools/        Smoke test (→ /workspace/tools)
  hooks/  lib/  schedules/  Vacíos por ahora
docs/                       Un archivo por responsabilidad
examples/pipeline/          Fixtures para correr el pipeline a mano
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
| `EVE_PLANNER_MODEL` | Modelo de los planners (tarea de razonamiento pesado). | `gemini-3.1-pro-preview` / `gpt-5.1` |
| `EVE_PLANNER` | Qué planner recibe la delegación: `planner` (razona la geometría) o `planner_sandbox` (la computa con el pipeline). | `planner` |
| `GCS_MCP_URL` | Endpoint MCP del GCS. | `http://127.0.0.1:3001/mcp` |
| `MUAV_API_URL` | API REST del GCS, para resolver y convertir el briefing. | `http://localhost:4000/api` |
| `GCS_CHAT_ID` | Chat del GCS al que el mcp_server notifica cuando persiste un plan. Solo lo usa `planner`; ver pendientes. | — |

Una más, `MISSION_DATA_DIR`, no va en el `.env`: la leen los scripts del pipeline
para poder correrlos contra fixtures fuera del sandbox (dentro siempre es
`/workspace/data`). Ver [`docs/sandbox.md`](docs/sandbox.md).

## Estado

Funciona y está verificado en vivo: el agente descubre las tools del GCS,
consulta flota y telemetría filtrando por estado, y despacha la planificación
con el briefing ya validado y convertido a XYZ.

El pipeline de `planner_sandbox` está verificado contra el validador real del
GCS: produce misiones estructuralmente válidas y sin colisiones a partir de los
fixtures de `examples/pipeline/`.

Pendientes conocidos:

- **Ningún planner completó un plan de punta a punta bajo el agente.** El
  pipeline se probó suelto; falta la corrida completa operador → planner →
  validación → plan mostrado.
- **`GCS_CHAT_ID` es un parche**, y solo lo necesita `planner`: al persistir,
  el mcp_server notifica a un chat del orquestador viejo, así que se le pasa
  uno real para que no falle. `planner_sandbox` no lo usa — persiste por su
  propia tool. El arreglo limpio vive en `mcp_server`, no en este repo.
- **Sin evals.** `evals/` y `npm run eval` están disponibles y sin usar. Con dos
  planners que resuelven lo mismo de formas distintas, es justo lo que haría
  falta para compararlos con algo más que una corrida suelta.
