# Contrato de conversación (threads y mensajes)

Define cómo un cliente (el GCS de `multiuav_gcs`) conversa con un agente EVE:
creación de threads, envío de mensajes, esquema normalizado de salida y
semántica de concurrencia.

Modelo general (decisiones de arquitectura, ver [agents.md](agents.md)):

- Un **agente EVE fijo y reutilizable** para todo el sistema.
- Un **thread por conversación** (`chatId` del GCS ↔ `thread_id` de EVE).
- Un **sandbox por conversación**, persistente mientras el thread esté activo.
- Concurrencia por **rechazo explícito** (`409 Conflict`), nunca por cola
  silenciosa ni descarte de mensajes.

## Endpoints

### Crear thread

```
POST /v1/agents/{agentId}/threads
```

Sin body obligatorio. Respuesta `201`:

- Ejemplo: [`examples/threads/thread_create_response.json`](../examples/threads/thread_create_response.json)

```json
{
  "thread_id": "thr_8f2c1a",
  "agent_id": "agent_eve_gcs",
  "status": "idle",
  "created_at": "2026-09-11T10:00:00Z"
}
```

El cliente guarda el par `chatId → thread_id` y lo reutiliza durante toda la
vida de la conversación. Crear un thread nuevo para un `chatId` existente es un
error del cliente: pierde el historial y el sandbox asociado.

### Consultar estado del thread

```
GET /v1/agents/{agentId}/threads/{threadId}
```

Respuesta `200`:

```json
{
  "thread_id": "thr_8f2c1a",
  "agent_id": "agent_eve_gcs",
  "status": "running",
  "updated_at": "2026-09-11T10:05:12Z"
}
```

`status` tiene exactamente dos valores:

| Estado    | Significado                                                        |
| --------- | ------------------------------------------------------------------ |
| `idle`    | El thread acepta mensajes.                                          |
| `running` | Hay un turno en ejecución (loop de tools incluido). Rechaza mensajes con `409`. |

La transición `running → idle` ocurre siempre al terminar el turno, tanto en
éxito como en error. Los timeouts de reloj, el límite de iteraciones del loop
de tools y la expiración de threads están en [lifecycle.md](lifecycle.md).

### Enviar mensaje (ejecuta el turno completo)

```
POST /v1/agents/{agentId}/threads/{threadId}/messages
```

Body: [`examples/threads/message_send_payload.json`](../examples/threads/message_send_payload.json)

```json
{
  "content": "Despegá el dron 1 a 10 metros y esperá confirmación."
}
```

Si el thread está `idle`, EVE ejecuta el **turno completo de forma síncrona**:
llamada al modelo, loop de tools (MCP + sandbox) hasta cerrar el turno, y
devuelve `200` con todos los mensajes generados en ese turno, normalizados:

- Ejemplo: [`examples/threads/message_response.json`](../examples/threads/message_response.json)

La respuesta final del asistente es el **último** elemento de `messages` con
`role: "assistant"` y `type: "text"`. El `turn_id` agrupa todos los mensajes
generados por un mismo input (equivalente al `turnId` de
`MessageOrchestrator._startTurn` en `multiuav_gcs`), para poder auditar el
costo real de un turno con una sola consulta.

Si el thread está `running`, responde `409` (ver
[Concurrencia](#concurrencia-y-409-conflict)).

### Leer historial

```
GET /v1/agents/{agentId}/threads/{threadId}/messages
```

Respuesta `200` con el historial completo del thread (incluye `system`), en el
mismo esquema normalizado. EVE es la fuente de verdad del historial; la UI del
GCS lo lee de acá, no mantiene una copia autoritativa.

## Esquema normalizado de mensajes

Todo mensaje que EVE devuelve —en la respuesta de un turno o en el historial—
tiene esta forma:

| Campo       | Tipo             | Descripción                                                       |
| ----------- | ---------------- | ----------------------------------------------------------------- |
| `role`      | enum             | `user` \| `assistant` \| `system` \| `tool` \| `unknown`          |
| `type`      | enum             | `text` \| `tool_call` \| `tool_result` \| `subagent_result` \| `reasoning` \| `multipart` \| `unknown` |
| `content`   | string \| null   | Texto plano derivado del payload (para render y búsqueda).        |
| `call_id`   | string \| null   | Presente en `tool_call` y `tool_result`; empareja el par. `null` en el resto. |
| `timestamp` | string (ISO 8601 UTC) | Momento de creación del mensaje.                             |
| `status`    | enum (opcional)  | `error` en el mensaje final de un turno fallido (ver [lifecycle.md](lifecycle.md)); ausente en el resto. |

Reglas:

- Un `tool_result` referencia **siempre** el `call_id` de su `tool_call`. Sin
  ese emparejamiento la UI no puede reconstruir el flujo de tools.
- `subagent_result` es el resultado asíncrono de un subagente, **añadido como
  mensaje nuevo** al thread padre — nunca se reescribe el `tool_result`
  original. Su `content` es un JSON string con `{ "status", "description",
  ...payload }`. El detalle del flujo subagente → padre se define en la Fase 5.
- `reasoning` y `multipart` existen en el vocabulario desde el día uno aunque
  el primer cliente no los renderice: eliminar valores de un enum publicado es
  un breaking change; agregarlos después también.

### Compatibilidad con multiuav_gcs

Este vocabulario es **idéntico a propósito** al de
`multiuav_gcs/server/models/chat/messageProjection.js` (`MESSAGE_ROLES` y
`MESSAGE_TYPES`). El frontend del GCS ya renderiza estos roles/tipos; EVE
reemplaza al orquestador sin obligar a tocar el renderizado de mensajes.

## Concurrencia y 409 Conflict

### Contrato

Si llega un `POST .../messages` con el thread en `running`:

- EVE responde `409 Conflict` con header `Retry-After: <segundos>` y este body:
  [`examples/threads/thread_busy_409.json`](../examples/threads/thread_busy_409.json)

```json
{
  "error": "thread_busy",
  "thread_id": "thr_8f2c1a",
  "status": "running",
  "retry_after": 5,
  "detail": "El thread tiene un turno en ejecución. Reintentá después de retry_after segundos."
}
```

Garantías, en orden de importancia:

1. **El mensaje nunca se descarta en silencio.** El `409` es la única forma de
   rechazo, y es explícita: el cliente sabe que su mensaje NO fue aceptado y
   conserva la responsabilidad de reenviarlo.
2. **EVE no encola.** Un `409` significa "no lo tengo, no lo voy a tener";
   no existe una cola oculta del lado del servidor.
3. `retry_after` es una sugerencia, no una promesa: al reintentar, el thread
   puede seguir `running` (turnos con tools largos). El cliente reintenta con
   **backoff exponencial** partiendo de `retry_after`.

### Nota de migración (responsabilidad que cambia de lado)

En `multiuav_gcs` la serialización de turnos vive hoy en el **servidor**: un
mutex por `chatId` (`chatLocks` en `chat.js`) encola los mensajes concurrentes
y `emitChatBusy` solo deshabilita el input de la UI. Con EVE esa
responsabilidad **pasa al cliente**:

- El GCS debe implementar el reintento con backoff al recibir `409` (hoy no
  existe ningún manejo de `409` en el código del GCS).
- `emitChatBusy` puede seguir existiendo como cortesía de UX (deshabilitar el
  input mientras `status === "running"`), pero deja de ser el mecanismo de
  control: el contrato lo garantiza el `409`, no el socket.

El script [`scripts/eve_api_curl.sh`](../scripts/eve_api_curl.sh) incluye un
ejemplo ejecutable de este reintento.
