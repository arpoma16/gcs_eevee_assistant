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

1. **Pipeline de planificación** (`planner_sandbox`): genera los waypoints y su formato.
2. **Análisis ad-hoc** (agente principal): scripts efímeros escritos por el
   agente en runtime para procesar telemetría/misiones a pedido del operador.
3. **Verificación independiente**: recomputar clearances de un plan como
   segunda opinión de `validate_mission`, sin tocar la implementación JS.

No es para portar lógica de dominio que ya corre en el GCS
(p. ej. `coordinateConverter.js` se queda donde está).

## Dónde vive el sandbox

Cada agente de eve tiene **exactamente un sandbox**, y un subagente declarado
**no hereda el del padre**: o declara el suyo, o recibe el default del
framework. Eso vale también para los archivos sembrados — por eso el pipeline
vive dentro de `planner_sandbox` y no en el agente raíz.

| Agente | Definición | Contenido sembrado |
| ------ | ---------- | ------------------ |
| raíz | [`agent/sandbox/`](../agent/sandbox/) | `/workspace/tools` (smoke test) |
| `planner_sandbox` | [`agent/subagents/planner_sandbox/sandbox/`](../agent/subagents/planner_sandbox/sandbox/) | `/workspace/pipeline` (los scripts) |
| `planner` | sin declarar → default del framework | ninguno |

El layout de carpeta (`sandbox.ts` junto a `sandbox/workspace/`) es lo que le
dice a eve que siembre ese directorio en `/workspace` al crear el sandbox. Los
scripts están versionados en el repo, no se generan en runtime.

## Los archivos, separados por quién los lee

`prepare_mission_input` resuelve el briefing contra el GCS y lo deja en disco
repartido **por tipo de dato y por lector**:

```
/workspace/data/
  origin.json          origen local y límites del área   ← scripts
  devices.json         drones con su posición XYZ        ← scripts
  targets.json         targets con su posición XYZ e id  ← scripts
  obstacles.json       obstáculos con su posición XYZ    ← scripts
  element_types.json   tipos y sus descripciones         ← el MODELO
```

Ese reparto es la garantía central de este subagente: **el único archivo que el
modelo abre no contiene ni una coordenada.** No es una regla de prompt que
pueda ignorar — es que el dato no está ahí. Las posiciones, los ids y el origen
los leen los scripts directamente del disco.

## Qué hace el modelo y qué hacen los scripts

El catálogo del GCS guarda las características físicas de cada elemento como
**prosa**, en la descripción del grupo:

```
windTurbine:     hub_height:80m  rotor_diameter: 56m  yaw_orientation: 90deg
building_short:  rectangular buildings width 35m,length 20m y de altura 30m orietation(yaw) 90 degress
```

La segunda mezcla inglés y español y trae dos typos. Ningún parser sobrevive a
eso, y un parser que falla en silencio es peor que no tenerlo. Leer esto es
trabajo del modelo — es la tarea en la que un LLM es bueno. **Calcular no lo
es**, y ahí empiezan los scripts.

| Paso | Responsable | Por qué |
| ---- | ----------- | ------- |
| 1 — geometría de cada tipo | **modelo** → `geometry.json` | Extraer dimensiones de prosa irregular. |
| 1b — objetos de colisión | script | Expande la geometría por tipo sobre cada elemento y la une con su posición. |
| 2 — análisis espacial | script | Distancias, spans, pares extremos: medidos, no estimados. |
| 3 — asignación drone→targets | **modelo** → `step3_assignment.json` | Decisión contra el objetivo de makespan. |
| 4 — parámetros de estrategia | **modelo** → `strategy_params.json` | Traduce la estrategia a números (viewpoints, stand-off, altitud). |
| 4b — waypoints | script | Trigonometría: anillos, yaw 0=Norte/90=Este, clamps de Z. |
| 5 — orden de ruta y ensamblado | script | Vecino más cercano, dirección de giro y costo. |

**Una entrada por TIPO, no por elemento.** Las características viven en el
grupo, así que dieciséis turbinas comparten una geometría: el modelo escribe una
entrada y el script la expande. `by_name` queda para el elemento que
genuinamente difiere de su tipo.

Regla dura: **el modelo nunca escribe una coordenada, una distancia ni un
ángulo.** Si un número entra al plan, lo produjo un script.

```
prepare_mission_input          → origin/devices/targets/obstacles/element_types.json
        │
        ▼  el modelo lee SOLO element_types.json
geometry.json  strategy_params.json  step3_assignment.json   (los escribe el modelo)
        │
        ▼
pipeline/build_collision_objects.py → collision_objects.json
pipeline/spatial_analysis.py        → step2_spatial_analysis.json
pipeline/generate_waypoints.py      → step4_waypoints.json
pipeline/order_routes.py            → step5_route.json
pipeline/build_mission.py           → mission.json   (aborta si falta o sobra un target)
        │
        ▼
validate_and_persist           lee los archivos, valida contra el GCS y persiste
```

## Correr el pipeline a mano

Los scripts leen `/workspace/data`, pero el directorio es configurable con
`MISSION_DATA_DIR` para poder probarlos fuera del sandbox contra los fixtures de
[`examples/pipeline/`](../examples/pipeline/):

```bash
D=/tmp/mission && mkdir -p $D
for f in examples/pipeline/*.example.json; do cp "$f" "$D/$(basename ${f%.example.json}).json"; done
cd agent/subagents/planner_sandbox/sandbox/workspace/pipeline
MISSION_DATA_DIR=$D python3 build_collision_objects.py
MISSION_DATA_DIR=$D python3 spatial_analysis.py
MISSION_DATA_DIR=$D python3 generate_waypoints.py
MISSION_DATA_DIR=$D python3 order_routes.py
MISSION_DATA_DIR=$D python3 build_mission.py
```

El `mission.json` resultante se puede mandar al validador real del GCS
(`POST /api/missions/validate`) sin pasar por el agente. Así se encontraron dos
bugs que no se veían de otra forma: yaw fuera del rango [-180, 180] que exige el
esquema, y rutas que salían de un anillo por el punto opuesto y cruzaban el
objeto **por su centro** — el `order_routes.py` elegía el punto de entrada pero
no el de salida.

## Smoke test

Todo sandbox recién creado debe poder ejecutar:

```bash
python3 /workspace/tools/smoke_test.py
```

Verifica versión de Python, escritura en `/workspace/data`, roundtrip JSON y
stdlib matemática. Sale con código 0 y `SMOKE TEST OK`; cualquier otra cosa es
un sandbox mal montado.

Los scripts del pipeline son **stdlib-only** a propósito: nada de `pip install`
en un sandbox que puede estar sin red, y una dependencia menos que pueda
romperse entre una misión y la siguiente.
