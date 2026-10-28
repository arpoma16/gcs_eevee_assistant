"""EJEMPLO de script de inspección. Copialo a scripts/inspection.py y adaptá PLAN.

Pedido del operador que resuelve este ejemplo:
    "Revisá la erosión del borde de ataque en las puntas de las palas a 1 mm/px y
     los receptores de rayo. La torre completa desde 10 m. Un dron para las palas
     y otro para la torre."

Qué hace (y qué hace tu script si partís de acá):
  1. Carga el escenario (World): targets con su modelo ya instanciado en su
     posición, orientación (azimFront) y ESTADO propio (rumbo de góndola, azimut
     del rotor...). Dos turbinas del mismo tipo con distinto estado dan puntos
     distintos sin que toques nada: el modelo resuelve la cinemática.
  2. Por cada target, genera candidatos con lib.patterns según PLAN.
  3. Los valida y repara con lib.views.solve_all (clearance al modelo completo
     del target, distancia a la geometría simple de los demás, altitud,
     geovalla, gimbal, línea de visión).
  4. Escribe data/views.json. Cada vista lleva un `block`: la unidad que después
     se asigna a UN dron. Un bloque por target es lo normal; acá cada turbina
     se parte en "<target>/blades" y "<target>/tower" porque el pedido reparte
     las palas y la torre entre dos drones.

Reglas:
  - Nunca escribas una coordenada, un ángulo o una distancia a mano. Los nombres
    de partes, superficies, zonas y features salen de `python3 tools/describe.py`.
  - Los números del pedido (GSD, rango en metros, clearance) sí son tuyos: vienen
    del operador o de MISSION PARAMETERS.
  - Si un target queda sin vistas, el script falla: una misión no puede omitir
    un target.

    python3 scripts/inspection.py              # usa /workspace/data
    python3 scripts/inspection.py --data DIR   # otro directorio de datos
"""
import argparse
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKSPACE))

from lib.patterns import inspect  # noqa: E402
from lib.views import Camera, Safety, solve_all, write_views  # noqa: E402
from lib.world import World  # noqa: E402

# ---------------------------------------------------------------------------
# PLAN: lo único que cambia de un pedido a otro.
#
# Por tipo de elemento, una lista de (bloque, tarea). `bloque` es el sufijo del
# bloque de asignación (None = un solo bloque con el nombre del target). La
# tarea son los argumentos de lib.patterns.inspect:
#   target      glob de parte ("tower", "blade_*"), lista de globs, o {"class": ..., "name": ...}
#   surfaces    ids de superficie (sin esto: todas las de la parte)
#   zones       zonas de la parte (rango en fracción del eje)
#   range_m     [desde, hasta] en metros sobre el eje (None = extremo)
#   features    ids o clases de feature (sin esto: superficies completas)
#   gsd_mm      resolución pedida; el standoff sale de la cámara
#   standoff_m  distancia fija, en vez de gsd_mm
#   overlap     solape entre fotos (0.3 por defecto)
# ---------------------------------------------------------------------------
PLAN = {
    "Wind Turbine": [
        ("blades", {"target": {"class": "rotor_blade"}, "surfaces": ["leading_edge"], "zones": ["tip"],
                    "gsd_mm": 1.0}),
        ("blades", {"target": {"class": "rotor_blade"}, "features": ["lightning_receptor"], "gsd_mm": 1.5}),
        ("tower", {"target": "tower", "range_m": [10, None], "gsd_mm": 2.0}),
    ],
}

# Tipos que el pedido no menciona: todas sus superficies, un bloque por target.
DEFAULT_TASKS = [(None, {"target": "*"})]

# Cámara y seguridad. Tomá la cámara de MISSION PARAMETERS; la seguridad, de las
# constantes de tus instrucciones salvo que el operador pida otra cosa.
# El techo es 120 m, salvo junto a un elemento de más de 105 m: a menos de 50 m
# de él se puede subir hasta 15 m sobre su altura (UE 2019/947, lib/regulation.py).
# Esa excepción exige que la pida el responsable del elemento: si la inspección no
# es por encargo suyo, poné tall_obstacle_exception=False.
#
# Si una vista se rechaza, leé su `blocking` y su pista antes de tocar nada: si el
# bloqueo es altura, geovalla o gimbal, cambiar números (standoff, clearance) no
# lo arregla; se cambia QUÉ se inspecciona o se informa como no inspeccionable.
CAMERA = Camera(hfov_deg=72.0, image_width_px=5280, image_height_px=3956)
SAFETY = Safety(min_clearance_m=6.0, transit_clearance_m=10.0, min_altitude_m=5.0, max_altitude_m=120.0)


def plan_target(world, target):
    """Vistas y rechazos de un target según PLAN."""
    views, rejected = [], []
    for suffix, task in PLAN.get(target.type, DEFAULT_TASKS):
        task = dict(task)
        block = f"{target.name}/{suffix}" if suffix else target.name
        candidates = inspect(target.model, CAMERA, task.pop("target"), safety=SAFETY, **task)
        ok, bad = solve_all(candidates, target, world, CAMERA, SAFETY, block=block)
        views += ok
        rejected += bad
    return views, rejected


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", type=Path, default=WORKSPACE / "data")
    args = parser.parse_args()

    world = World.load(args.data)
    views, rejected = [], []
    for target in world.targets:
        v, r = plan_target(world, target)
        if target.model.ignored_state:
            print(f"AVISO {target.name}: attributes que no son estado del modelo, ignorados: "
                  f"{sorted(target.model.ignored_state)}")
        views += v
        rejected += r

    write_views(views, args.data / "views.json", rejected, CAMERA, SAFETY)

    missing = [t.name for t in world.targets if not any(v["target"] == t.name for v in views)]
    if missing:
        sys.exit(f"Targets sin ninguna vista: {', '.join(missing)}. Revisá PLAN o las rechazadas.")


if __name__ == "__main__":
    main()
