# gcs_eevee_assistant

Implementación base para trabajar con EVE (Client API) con:

- `curl` para estado, creación de agentes y subagentes.
- Configuración de sandbox para ejecutar scripts de Python.
- Ejemplo de integración de herramientas vía MCP server.

## Estructura

- `/docs/eve_implementation.md`: guía completa en español.
- `/examples/eve_api_curl.sh`: comandos `curl` parametrizados.
- `/examples/eve_agent_payload.json`: payload de ejemplo para crear un agente.
- `/examples/eve_subagent_payload.json`: payload de ejemplo para crear un subagente.
- `/examples/eve_sandbox_mcp_config.json`: sandbox + MCP server.
- `/scripts/hello_from_sandbox.py`: script de Python para ejecutar en sandbox.

## Uso rápido

```bash
chmod +x /home/runner/work/gcs_eevee_assistant/gcs_eevee_assistant/examples/eve_api_curl.sh
EVE_BASE_URL="https://api.eve.dev" \
EVE_API_KEY="tu_api_key" \
/home/runner/work/gcs_eevee_assistant/gcs_eevee_assistant/examples/eve_api_curl.sh
```

> Nota: ajusta rutas/endpoints finales según tu versión de EVE si difieren de la guía oficial.
