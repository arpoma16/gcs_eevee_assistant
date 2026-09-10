# Implementación EVE (estado, agentes, subagentes, sandbox Python y MCP)

Esta guía propone una implementación mínima para iniciar con EVE Client API.

## 1) Variables de entorno

```bash
export EVE_BASE_URL="https://api.eve.dev"
export EVE_API_KEY="tu_api_key"
```

## 2) Verificar estado del servicio

```bash
curl -sS -X GET "$EVE_BASE_URL/v1/status" \
  -H "Authorization: ******" \
  -H "Content-Type: application/json"
```

## 3) Crear un agente

```bash
curl -sS -X POST "$EVE_BASE_URL/v1/agents" \
  -H "Authorization: ******" \
  -H "Content-Type: application/json" \
  -d @/home/runner/work/gcs_eevee_assistant/gcs_eevee_assistant/examples/eve_agent_payload.json
```

## 4) Crear un subagente

```bash
export PARENT_AGENT_ID="agent_123"

curl -sS -X POST "$EVE_BASE_URL/v1/agents/$PARENT_AGENT_ID/subagents" \
  -H "Authorization: ******" \
  -H "Content-Type: application/json" \
  -d @/home/runner/work/gcs_eevee_assistant/gcs_eevee_assistant/examples/eve_subagent_payload.json
```

## 5) Configurar sandbox para scripts de Python

La configuración está en:

- `/home/runner/work/gcs_eevee_assistant/gcs_eevee_assistant/examples/eve_sandbox_mcp_config.json`

Incluye:

- Runtime Python (`python:3.12-slim`)
- Directorio de trabajo `/workspace`
- Montaje del código local
- Comando permitido para ejecutar Python

Script de ejemplo:

- `/home/runner/work/gcs_eevee_assistant/gcs_eevee_assistant/scripts/hello_from_sandbox.py`

## 6) Conectar herramientas con MCP server

La misma configuración incluye un servidor MCP de ejemplo (`filesystem`) y un placeholder de `github`.

Si necesitas otro MCP server, reemplaza `command`, `args` y `env` por los de tu servidor MCP.

## 7) Flujo recomendado

1. Validar estado (`/v1/status`).
2. Crear agente.
3. Crear subagente.
4. Pasar configuración sandbox+MCP al agente.
5. Ejecutar el script Python dentro del sandbox.

---

Si tu tenant de EVE usa endpoints/nombres de campos distintos, conserva esta estructura y adapta únicamente rutas y payloads.
