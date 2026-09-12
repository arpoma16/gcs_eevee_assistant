"""Step 4: aplica el patrón de inspección de cada tipo a cada elemento.

El patrón describe los viewpoints en el MARCO LOCAL del elemento (origen en el
centro de su huella, a nivel del suelo). Este runner lo instancia sobre cada
elemento concreto: rota por su yaw, traslada a su posición real, apunta la
cámara y recorta la altitud. Por eso un mismo patrón sirve para un aerogenerador
o para diez, sin que nadie reescriba una coordenada.

Qué patrón usa cada tipo se declara en geometry.json con `"pattern": "<nombre>"`,
y el módulo se busca en /workspace/patterns/<nombre>.py. Sin `pattern`, se usa
`ring` — el anillo clásico.

Los parámetros de vuelo se resuelven POR ELEMENTO: `by_name` → `by_type` → los
globales de strategy_params.json.
"""

import argparse
import importlib.util
import sys
from pathlib import Path

from pipelib import (
    DATA_DIR,
    clamp_alt,
    footprint_radius,
    load_json,
    local_to_world,
    save_json,
    yaw_towards,
)

PATTERNS_DIR = Path(__file__).resolve().parent.parent / "patterns"
FLIGHT_PARAMS = ("stand_off", "altitude_fraction", "viewpoints")


def load_pattern(name):
    path = PATTERNS_DIR / f"{name}.py"
    if not path.exists():
        available = ", ".join(sorted(p.stem for p in PATTERNS_DIR.glob("*.py"))) or "ninguno"
        sys.exit(f"No existe el patrón '{name}' en {PATTERNS_DIR}. Disponibles: {available}.")

    spec = importlib.util.spec_from_file_location(f"pattern_{name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "viewpoints"):
        sys.exit(f"El patrón '{name}' no define viewpoints(element, params).")
    return module


def type_entry(target, geometry):
    by_name = (geometry.get("by_name") or {}).get(target["name"]) or {}
    by_type = (geometry.get("by_type") or {}).get(target.get("type") or "unknown") or {}
    return {**by_type, **by_name}


def flight_params(entry, defaults):
    resolved = {
        "stand_off": defaults["stand_off"],
        "altitude_fraction": defaults["altitude_fraction"],
        "viewpoints": defaults["viewpoints_per_target"],
    }
    for key in FLIGHT_PARAMS:
        if entry.get(key) is not None:
            resolved[key] = entry[key]
    # Todo lo demás que el tipo declare viaja al patrón: un patrón propio puede
    # necesitar parámetros que este runner no conoce.
    return {**{k: v for k, v in entry.items() if k not in ("geometry_type", "dimensions")}, **resolved}


def target_block(obstacle, entry, params, pattern):
    center = obstacle["position"]
    element_yaw = float(obstacle.get("yaw", 0.0))
    element = {
        "name": obstacle["obstacle_name"],
        "dimensions": obstacle["dimensions"],
        "footprint": footprint_radius(obstacle["dimensions"]),
        "height": float(obstacle.get("height", 0.0)),
        "safety_margin": float(obstacle["safety_margin"]),
        **{k: v for k, v in entry.items() if k not in ("geometry_type",)},
    }

    waypoints = []
    for point in pattern.viewpoints(element, params):
        position = local_to_world(center, element_yaw, point["local"])
        position["z"] = clamp_alt(position["z"])
        look_at = local_to_world(center, element_yaw, point.get("yaw_towards") or (0.0, 0.0, 0.0))
        waypoints.append(
            {
                "label": point["label"],
                "position": position,
                "yaw": yaw_towards(position, look_at),
            }
        )
    return {"target_name": obstacle["obstacle_name"], "waypoints": waypoints}


def takeoff_landing(drone, defaults):
    position = drone["position"]
    point = {
        "x": round(float(position["x"]), 1),
        "y": round(float(position["y"]), 1),
        "z": round(float(position.get("z", 0.0)) + float(defaults["takeoff_landing_alt"]), 1),
    }
    return {"drone_name": drone["name"], "takeoff": point, "landing": dict(point)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--targets", default=DATA_DIR / "targets.json")
    parser.add_argument("--devices", default=DATA_DIR / "devices.json")
    parser.add_argument("--collision-objects", default=DATA_DIR / "collision_objects.json")
    parser.add_argument("--geometry", default=DATA_DIR / "geometry.json")
    parser.add_argument("--strategy", default=DATA_DIR / "strategy_params.json")
    parser.add_argument("--output", default=DATA_DIR / "step4_waypoints.json")
    args = parser.parse_args()

    defaults = load_json(args.strategy)
    geometry = load_json(args.geometry)
    targets = load_json(args.targets)
    by_name = {o["obstacle_name"]: o for o in load_json(args.collision_objects)}

    patterns = {}
    blocks = []
    for target in targets:  # solo los targets llevan viewpoints; el resto son obstáculos
        entry = type_entry(target, geometry)
        params = flight_params(entry, defaults)
        name = entry.get("pattern") or "ring"
        pattern = patterns.setdefault(name, load_pattern(name))

        block = target_block(by_name[target["name"]], entry, params, pattern)
        blocks.append(block)
        print(f"{target['name']} ({target.get('type')}): patrón={name} waypoints={len(block['waypoints'])}")

    save_json(
        args.output,
        {
            "takeoff_landing": [takeoff_landing(d, defaults) for d in load_json(args.devices)],
            "target_blocks": blocks,
        },
    )


if __name__ == "__main__":
    main()
