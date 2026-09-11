# Ciclo de vida y resiliencia

Define las garantías de terminación de un turno: cómo un thread vuelve
siempre a `idle`, qué límites lo protegen y cómo se reportan los errores.

## Invariante central

**Todo turno termina y toda terminación deja el thread en `idle`** — éxito,
error de tool, error del modelo o timeout. Un thread que se queda `running`
para siempre es un bug del servidor, no un estado válido: significaría `409`
eterno para el cliente.

```
idle ──POST /messages──▶ running ──éxito──────────▶ idle
                            │
                            ├──error (tool/modelo)─▶ idle  (+ mensaje de error)
                            ├──timeout de reloj────▶ idle  (+ mensaje de error)
                            └──límite iteraciones──▶ idle  (+ mensaje de error)
```

## Límites por agente

Cada agente/subagente declara sus límites en el payload de creación (campo
`limits`); si no los declara, hereda los defaults. Valores iniciales, espejo
de los del orquestador actual (`chat.js` de `multiuav_gcs`):

| Límite | Default | `planner` | Qué corta |
| ------ | ------- | --------- | --------- |
| `max_tool_iterations` | 25 | 18 | Iteraciones del loop de tools en un turno. Protege contra loops infinitos de tool-calling. |
| `turn_timeout_seconds` | 600 | 900 | Tiempo de reloj del turno completo, tools incluidas. Protege contra tools colgadas — un límite de iteraciones solo no alcanza si una iteración nunca vuelve. |

El timeout de reloj es la novedad respecto de `multiuav_gcs` (hoy solo hay
límite de iteraciones): es lo que garantiza el invariante incluso cuando una
tool MCP o el sandbox no responden. El `planner` recibe más tiempo y menos
iteraciones: su variante single-turn hace pocas llamadas, pero cada una (el
pipeline del sandbox, `validate_mission`) puede ser larga.

## Reporte de errores

Cuando un turno termina por error, la terminación es **visible dos veces**:

1. **En la respuesta del `POST /messages`**: HTTP `200` (el turno ocurrió y
   quedó registrado) con un campo `error` en el envelope:

```json
{
  "thread_id": "thr_8f2c1a",
  "turn_id": "…",
  "status": "idle",
  "error": { "code": "turn_timeout", "detail": "Turno abortado a los 600 s." },
  "messages": [ "…los mensajes generados hasta el corte…" ]
}
```

   Códigos: `turn_timeout`, `max_iterations_exceeded`, `tool_error`,
   `model_error`.

2. **En el historial**: el último mensaje del turno es un `role: "assistant"`,
   `type: "text"` con `status: "error"` (campo opcional del esquema
   normalizado, mismo convenio que `emitAssistantError` en `multiuav_gcs`) y el
   texto legible del error. Así la UI muestra el fallo en el chat sin lógica
   especial.

El mensaje del usuario que disparó el turno **queda persistido** aunque el
turno falle: el operador puede pedir "reintentá" sin repetir el input.

## Qué NO se destruye en un error

- **El sandbox sobrevive**: los archivos de `/workspace/data` quedan intactos
  tras un error o timeout. Es deliberado — el turno siguiente puede
  inspeccionarlos, repararlos o reintentar el pipeline sin regenerar todo.
- **El historial nunca se reescribe**: los mensajes generados antes del corte
  quedan; el error se añade al final. Mismo principio de inmutabilidad que el
  `subagent_result` de la Fase 5.

## Expiración de threads

Un thread inactivo (sin turnos) durante más de `thread_ttl_hours`
(configurable, default 24 h) expira: su sandbox se destruye y el thread pasa a
solo lectura — el historial sigue disponible vía `GET /messages`, pero un
`POST /messages` responde `410 Gone`. El cliente crea un thread nuevo para
continuar la conversación.
