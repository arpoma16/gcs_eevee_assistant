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

Cada agente de eve tiene **exactamente un sandbox**, y un subagente declarado
**no hereda el del padre**: o declara el suyo, o recibe el default del
framework. Eso vale también para los archivos sembrados.

| Agente | Definición | Contenido sembrado |
| ------ | ---------- | ------------------ |
| raíz | [`agent/sandbox/sandbox.ts`](../agent/sandbox/sandbox.ts) + `agent/sandbox/workspace/**` | `/workspace/tools` (smoke test), `/workspace/pipeline` (scripts de planificación) |
| `planner` | sin declarar → default del framework | ninguno |

El layout de carpeta (`agent/sandbox/sandbox.ts` junto a
`agent/sandbox/workspace/`) es lo que le dice a eve que siembre ese directorio
en `/workspace` al crear el sandbox:

```
/workspace/
  tools/      sembrado — smoke test y utilidades comunes
  pipeline/   sembrado — pipeline de planificación
  data/       lo crean los scripts — entrada/salida de la misión en curso
```

Los scripts están versionados en el repo, no se generan en runtime.

> **Estado: el pipeline todavía no está conectado.** Los scripts se siembran,
> pero nada le indica al planner que los ejecute — sus instructions siguen
> pidiéndole que razone la geometría a mano, como el `planner.md` original. Y
> como el sandbox no se hereda, conectarlo implica además mover el seed a
> `agent/subagents/planner/sandbox/`. Lo de abajo es el diseño objetivo, no lo
> que corre hoy.

## Flujo de datos del planner (diseño objetivo)

```
mission_input.json          (lo escribiría el briefing al delegar — NO pasa por el modelo)
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

`mission_input.json` sería el briefing ya resuelto en XYZ que hoy
`request_mission_plan` arma y le pasa al planner dentro del `message` (ver
[delegation.md](delegation.md)): los mismos datos, pero llegando como archivo
en vez de como texto en el contexto del modelo.

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
