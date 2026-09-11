# Sandbox Python

Define para qué existe el sandbox, cómo se asigna por agente y cómo fluyen los
datos como archivos.

## Para qué existe (y para qué no)

El planner de `multiuav_gcs` hoy "piensa" los waypoints: el modelo razona
geometría (distancias, anillos de inspección, yaw hacia el centro, orden de
ruta) como texto. Eso es exactamente donde un LLM alucina números. El sandbox
invierte esa responsabilidad:

- **El modelo decide estrategia** (cuántos viewpoints, regla de altitud,
  stand-off, qué drone barre qué zona).
- **Los scripts computan la geometría** de forma determinista, leyendo y
  escribiendo **archivos** en `/workspace/data`. La misión nunca viaja por el
  contexto del modelo como números inferidos: viaja como archivo.

El propio esquema de `submit_mission_plan` lo exige — el Step 2 dice
"Measured, not estimated". Medir es trabajo de script.

Usos autorizados del sandbox:

1. **Pipeline de planificación** (planner): genera los waypoints y su formato.
2. **Análisis ad-hoc** (agente principal): scripts efímeros escritos por el
   agente en runtime para procesar telemetría/misiones a pedido del operador.
3. **Verificación independiente**: recomputar clearances de un plan como
   segunda opinión de `validate_mission`, sin tocar la implementación JS.

No es para portar lógica de dominio que ya corre en el GCS
(p. ej. `coordinateConverter.js` se queda donde está).

## Asignación de sandbox por agente

- **Un sandbox por conversación**: se crea con el thread y persiste mientras el
  thread esté activo; los archivos sobreviven entre turnos del mismo thread.
- **Configuración por agente, con fallback**: cada agente/subagente puede
  declarar su `sandbox_config_path`. Si no declara ninguno, hereda la
  configuración **default**.

| Agente | Config | Contenido preconfigurado |
| ------ | ------ | ------------------------ |
| (fallback) | [`examples/sandbox/default.json`](../examples/sandbox/default.json) | `/workspace/tools` (smoke test y utilidades comunes, solo lectura) |
| principal | `examples/sandbox/default.json` | El default le alcanza: sus scripts son ad-hoc, los escribe en runtime. |
| `planner` | [`examples/sandbox/planner.json`](../examples/sandbox/planner.json) | Además, `/workspace/pipeline` (pipeline de waypoints, solo lectura) |

Layout dentro de todo sandbox:

```
/workspace/
  tools/      solo lectura — smoke test y utilidades comunes
  pipeline/   solo lectura — solo en el sandbox del planner
  data/       escritura — entrada/salida de la misión en curso
```

Los mounts de solo lectura apuntan a `scripts/sandbox/` de este repo: los
scripts preconfigurados están versionados acá, no se generan en runtime.

## Flujo de datos del planner (archivos, no contexto)

```
mission_input.json          (inyectado por el GCS al delegar — NO pasa por el modelo)
strategy_params.json        (lo escribe el planner: sus decisiones de estrategia)
        │
        ▼
pipeline/spatial_analysis.py    → step2_spatial_analysis.json   (medido, no estimado)
pipeline/generate_waypoints.py  → step4_waypoints.json          (takeoff/landing + anillos + yaw)
pipeline/order_routes.py        → step5_route.json              (orden de visita + costo)
        │
        ▼
submit_mission_plan             (el planner arma el payload leyendo los .json)
```

Reparto de pasos del plan (esquema `submitMissionPlanSchema` del mcp_server):

| Paso | Responsable | Por qué |
| ---- | ----------- | ------- |
| 1 — modelo de obstáculos | modelo | Transformación casi literal del input + márgenes de la estrategia. |
| 2 — análisis espacial | **script** | Distancias, spans, pares extremos: el esquema exige medición. |
| 3 — asignación drone→targets | modelo (informado por el step 2) | Decisión de estrategia contra el objetivo de makespan. Candidato a script en el futuro. |
| 4 — generación de waypoints | **script** | Trigonometría pura: anillos, yaw 0=Norte/90=Este, reglas de Z. |
| 5 — orden de ruta | **script** | Vecino más cercano + costo total: computación, no opinión. |

Regla dura para el planner: **los campos numéricos de los pasos 2, 4 y 5 salen
de los archivos generados por el pipeline, nunca del razonamiento del modelo.**
Los campos narrativos (`standing`, `layout`, `approach_notes`,
`reasoning_summary`) sí los redacta el modelo, leyendo los números del archivo.

`mission_input.json` es el equivalente en archivo de los `contextParams` que
hoy `subAgentRegistry` inyecta en las tool calls del subagente: datos
estructurados que llegan por un canal que el modelo no puede corromper.

## Smoke test

Todo sandbox recién creado debe poder ejecutar:

```bash
python3 /workspace/tools/smoke_test.py
```

Verifica versión de Python, escritura en `/workspace/data`, roundtrip JSON y
stdlib matemática. Sale con código 0 y `SMOKE TEST OK`; cualquier otra cosa es
un sandbox mal montado. Los scripts del pipeline son **stdlib-only** a
propósito: `python:3.12-slim` sin `pip install`, sin red (`allow_network:
false`).
