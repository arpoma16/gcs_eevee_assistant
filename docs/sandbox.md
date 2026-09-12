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
| 1 — geometría y vuelo, por tipo | **modelo** → `geometry.json` | Extraer dimensiones de prosa irregular, y derivar de ellas el stand-off y la altitud que pide la estrategia. |
| 1b — objetos de colisión | `build_collision_objects.py` | Expande la geometría por tipo sobre cada elemento y la une con su posición. |
| 2 — asignación y orden | `plan_routes.py` | Reparto por cercanía con tope de carga, vecino más cercano y 2-opt, contra el makespan. |
| 2b — medidas del campo | `spatial_analysis.py` | Distancias, spans, pares extremos, para cuando el modelo quiera decidir el reparto él. |
| 3 — parámetros de misión | **modelo** → `strategy_params.json` | Velocidad de crucero, altura de despegue, y fallbacks. |
| 3b — patrón de inspección | **modelo** → `patterns/*.py` | Qué forma tiene la inspección. Solo si el anillo no alcanza. |
| 3c — waypoints | `generate_waypoints.py` | Instancia el patrón en cada elemento: rota, traslada, apunta la cámara, recorta Z. |
| 4 — revisión por target | `check_viewpoints.py` | Cada punto contra cada objeto, aislado y barato, antes de ensamblar. |
| 5 — ensamblado | `build_mission.py` | Entrada y salida de cada anillo, y la misión completa. |

**Una entrada por TIPO, no por elemento.** Las características viven en el
grupo, así que dieciséis turbinas comparten una geometría: el modelo escribe una
entrada y el script la expande. `by_name` queda para el elemento que
genuinamente difiere de su tipo.

**Y por tipo también el vuelo**, no solo la forma. El stand-off sale de
`frame_extent / (2 × tan(fov/2))`, y `frame_extent` son las dimensiones del
propio elemento: una misión con turbinas (rotor 56 m) y edificios (fachada 35 m)
necesita 48,5 m para unas y 30,3 m para otros. Un único valor global es
incorrecto para al menos uno de los dos, así que `geometry.json` los lleva por
tipo y `strategy_params.json` queda solo con lo que es de la misión entera
(velocidad, altura de despegue) más fallbacks.

La regla, con precisión: **el modelo deriva la geometría del elemento; los
scripts derivan la del vuelo.** El modelo escribe distancias y ángulos —
`radius`, `height`, `yaw`, `stand_off`— porque salen de leer una descripción.
Lo que no escribe nunca es una **posición**: ninguna coordenada de waypoint, de
ruta o de obstáculo pasa por él.

## Patrones: cuando un parámetro no alcanza

Un anillo de N puntos cubre SIMPLE y CIRCULAR. No cubre nada más: los anillos
apilados de una estructura voluminosa, el barrido boustrophedon de una esbelta,
la grilla zig-zag de una fachada o las palas de un aerogenerador **no son el
mismo algoritmo con otros números** — son algoritmos distintos. Ningún script
parametrizado los expresa a todos.

Por eso `generate_waypoints.py` no genera la forma: la **instancia**. La forma
la aporta un patrón, un módulo en `/workspace/patterns/` con una función:

```python
def viewpoints(element, params) -> [{"label", "local": (x, y, z), "yaw_towards"}]
```

que devuelve los puntos en el **marco local del elemento** — origen en el centro
de su huella a nivel del suelo, `+Y` hacia donde mira, `+Z` arriba. El runner lo
rota por el yaw de cada elemento, lo traslada a su posición real, apunta la
cámara y recorta la altitud.

Ahí está la propiedad que buscábamos: **la forma se describe una vez, relativa
al objeto, y se aplica a los diez aerogeneradores** pasándole a cada llamada la
posición absoluta leída del archivo. El patrón nunca ve una coordenada del
mundo, así que tampoco puede equivocarla.

Viene uno solo: `ring`, el default, que además es el **contrato documentado** —
su docstring explica la firma y el marco local. Los demás los escribe el modelo
para la inspección que le pidieron, y por eso no se versionan: un patrón de
palas, de fachada o de barrido de caras depende de qué te pidieron mirar. Eso es
lo que justifica tener un sandbox y no solo un archivo de configuración.

### El modelo de colisión depende de qué inspeccionás

Probando un patrón de palas apareció una tensión de dominio que conviene
conocer, porque no es un bug sino una decisión:

Una turbina vista desde afuera es un cilindro del ancho del rotor barrido — nada
puede cruzar ese disco. **La misma turbina inspeccionada en sus palas es una
torre de pocos metros**: el rotor es un disco delgado, y un dron a 12 m de su
cara está en aire libre. Modelada como rotor, los waypoints de palas dieron
**76 colisiones**; modelada como torre, los mismos waypoints dieron **0**. Le
estás diciendo al validador dónde hay materia sólida, y si le decís que el dron
está adentro del objeto, te rechaza la misión entera — con razón.

```
prepare_mission_input          → origin/devices/targets/obstacles/element_types.json
        │
        ▼  el modelo lee SOLO element_types.json
geometry.json          forma + parámetros de vuelo, POR TIPO   (los escribe el modelo)
strategy_params.json   velocidad, despegue y fallbacks          (los escribe el modelo)
step3_assignment.json  qué drone vuela qué target               (los escribe el modelo)
        │
        ▼
pipeline/build_collision_objects.py → collision_objects.json
pipeline/plan_routes.py             → route_plan.json   (quién vuela qué, y en qué orden)
pipeline/generate_waypoints.py      → step4_waypoints.json
pipeline/check_viewpoints.py        → revisa cada target por separado, --fix los aleja
pipeline/build_mission.py           → mission.json      (aborta si falta o sobra un target)
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
MISSION_DATA_DIR=$D python3 plan_routes.py
MISSION_DATA_DIR=$D python3 generate_waypoints.py
MISSION_DATA_DIR=$D python3 check_viewpoints.py
MISSION_DATA_DIR=$D python3 build_mission.py
```

El `mission.json` resultante se puede mandar al validador real del GCS
(`POST /api/missions/validate`) sin pasar por el agente. Así se encontraron tres
cosas que no se veían de otra forma:

- **Yaw fuera de rango**: los waypoints salían en 0–360 y el esquema exige
  [-180, 180].
- **Colisión autoinfligida**: la ruta salía de un anillo por el punto opuesto y
  el tramo siguiente cruzaba el objeto **por su centro**. Se elegía el punto de
  entrada pero no el de salida.
- **El balance perfecto genera conflictos entre drones**: rutas de largo
  idéntico ponen a los drones en posiciones espejadas en tiempos idénticos. Con
  dos turbinas a 100 m y anillos de radio 43, los dos aparatos se cruzan por el
  hueco del medio **en el mismo segundo**, a 3 m. Se repara con separación de
  altitud (R.3-bis), pero conviene saber que lo causa optimizar el makespan.

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
