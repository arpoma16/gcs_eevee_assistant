#!/usr/bin/env bash
set -euo pipefail

: "${EVE_BASE_URL:?Debes definir EVE_BASE_URL}"
: "${EVE_API_KEY:?Debes definir EVE_API_KEY}"

ROOT="/home/runner/work/gcs_eevee_assistant/gcs_eevee_assistant/examples"

echo "[1/3] Estado del servicio"
curl -sS -X GET "$EVE_BASE_URL/v1/status" \
  -H "Authorization: ******" \
  -H "Content-Type: application/json"
echo

echo "[2/3] Crear agente"
curl -sS -X POST "$EVE_BASE_URL/v1/agents" \
  -H "Authorization: ******" \
  -H "Content-Type: application/json" \
  -d @"$ROOT/eve_agent_payload.json"
echo

echo "[3/3] Crear subagente (requiere PARENT_AGENT_ID)"
if [[ -n "${PARENT_AGENT_ID:-}" ]]; then
  curl -sS -X POST "$EVE_BASE_URL/v1/agents/$PARENT_AGENT_ID/subagents" \
    -H "Authorization: ******" \
    -H "Content-Type: application/json" \
    -d @"$ROOT/eve_subagent_payload.json"
  echo
else
  echo "Omitido: exporta PARENT_AGENT_ID para crear el subagente"
fi
