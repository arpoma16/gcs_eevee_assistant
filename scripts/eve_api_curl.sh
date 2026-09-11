#!/usr/bin/env bash
# Flujo completo contra la API de EVE: estado → agente → subagente → thread →
# mensaje (con reintento ante 409) → historial.
set -euo pipefail

: "${EVE_BASE_URL:?Debes definir EVE_BASE_URL}"
: "${EVE_API_KEY:?Debes definir EVE_API_KEY}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EXAMPLES="$REPO_ROOT/examples"

AUTH=(-H "Authorization: Bearer $EVE_API_KEY" -H "Content-Type: application/json")

eve_get()  { curl -sS -X GET  "$EVE_BASE_URL$1" "${AUTH[@]}"; }
eve_post() { curl -sS -X POST "$EVE_BASE_URL$1" "${AUTH[@]}" "${@:2}"; }

json_field() { python3 -c "import json,sys; print(json.load(sys.stdin).get('$1',''))"; }

echo "[1/6] Estado del servicio"
eve_get "/v1/status"
echo

echo "[2/6] Crear agente principal"
AGENT_ID="${AGENT_ID:-$(eve_post "/v1/agents" -d @"$EXAMPLES/agents/agent_payload.json" | json_field agent_id)}"
echo "agent_id=$AGENT_ID"

echo "[3/6] Crear subagente planner"
eve_post "/v1/agents/$AGENT_ID/subagents" -d @"$EXAMPLES/agents/subagent_planner_payload.json"
echo

echo "[4/6] Crear thread"
THREAD_ID="$(eve_post "/v1/agents/$AGENT_ID/threads" | json_field thread_id)"
echo "thread_id=$THREAD_ID"

echo "[5/6] Enviar mensaje (reintento con backoff ante 409)"
# Contrato de concurrencia: un 409 significa que el mensaje NO fue aceptado y
# el cliente conserva la responsabilidad de reenviarlo. Backoff exponencial
# partiendo del retry_after sugerido; nunca se descarta el mensaje.
MAX_RETRIES=5
DELAY=0
RESPONSE_FILE="$(mktemp)"
trap 'rm -f "$RESPONSE_FILE"' EXIT
SENT=false
for attempt in $(seq 1 "$MAX_RETRIES"); do
  HTTP_CODE="$(curl -sS -o "$RESPONSE_FILE" -w '%{http_code}' \
    -X POST "$EVE_BASE_URL/v1/agents/$AGENT_ID/threads/$THREAD_ID/messages" \
    "${AUTH[@]}" -d @"$EXAMPLES/threads/message_send_payload.json")"

  if [[ "$HTTP_CODE" != "409" ]]; then
    cat "$RESPONSE_FILE"
    echo
    SENT=true
    break
  fi

  RETRY_AFTER="$(json_field retry_after < "$RESPONSE_FILE")"
  DELAY=$(( DELAY == 0 ? ${RETRY_AFTER:-5} : DELAY * 2 ))
  echo "Thread ocupado (intento $attempt/$MAX_RETRIES), reintentando en ${DELAY}s..."
  sleep "$DELAY"
done

if [[ "$SENT" != true ]]; then
  echo "ERROR: thread sigue ocupado tras $MAX_RETRIES intentos; el mensaje NO fue entregado." >&2
  exit 1
fi

echo "[6/6] Leer historial"
eve_get "/v1/agents/$AGENT_ID/threads/$THREAD_ID/messages"
echo
