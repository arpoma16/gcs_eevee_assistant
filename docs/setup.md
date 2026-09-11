# Setup

Prerrequisitos y convenciones comunes a toda la guía.

## Variables de entorno

```bash
export EVE_BASE_URL="https://<host-de-tu-tenant-eve>"   # sin barra final
export EVE_API_KEY="<api-key>"
```

No hay valores por defecto: si alguna falta, los scripts fallan al arrancar en
vez de pegarle a un host inventado.

## Convenciones

- Autenticación: header `Authorization: Bearer $EVE_API_KEY` en toda request.
- `Content-Type: application/json` en toda request con body.
- Rutas de archivos: siempre relativas a la raíz de este repositorio. Los
  scripts resuelven su propia ubicación, no dependen del directorio de trabajo.
- Timestamps: ISO 8601 en UTC (`2026-09-11T10:00:00Z`).

## Verificar el servicio

```bash
curl -sS -X GET "$EVE_BASE_URL/v1/status" \
  -H "Authorization: Bearer $EVE_API_KEY" \
  -H "Content-Type: application/json"
```

Debe responder `200` antes de crear agentes o threads. El flujo completo y
ejecutable está en [`scripts/eve_api_curl.sh`](../scripts/eve_api_curl.sh).
