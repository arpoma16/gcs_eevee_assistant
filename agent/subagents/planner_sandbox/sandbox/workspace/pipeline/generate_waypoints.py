"""Step 4 del plan de misión: generación determinista de waypoints.

Lee targets.json y devices.json (posiciones), collision_objects.json (geometría
real de cada elemento), geometry.json (los parámetros de vuelo que derivaste por
tipo) y strategy_params.json (los valores globales de la misión). Escribe
step4_waypoints.json con la forma del esquema `Step4WaypointsSchema`:

- takeoff/landing por drone (XY de la posición inicial, Z = z + takeoff_landing_alt)
- un target_block por target: anillo de viewpoints a stand_off del footprint,
  Z por fracción de la altura del elemento, yaw apuntando al centro.

Los parámetros de vuelo se resuelven POR ELEMENTO: primero `by_name`, después
`by_type`, y al final los globales de strategy_params. Una misión con turbinas y
edificios necesita un stand-off distinto para cada tipo, porque el encuadre
depende de las dimensiones del propio elemento.

El stand-off nunca baja de R_SAFE (footprint + safety_margin): la seguridad gana
sobre el encuadre, igual que en la regla `standoff = max(standoff_optical, R_SAFE)`.
"""

import argparse
import math

from pipelib import DATA_DIR, footprint_radius, load_json, pos_xyz, save_json, yaw_towards

COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
FLIGHT_PARAMS = ("stand_off", "altitude_fraction", "viewpoints")


def ring_label(index, count, angle_deg):
    if count <= len(COMPASS) and count in (4, 8):
        return COMPASS[index * (len(COMPASS) // count)]
    return f"P{index + 1}-{round(angle_deg)}deg"


def flight_params(target, geometry, defaults):
    """Parámetros de vuelo del elemento: by_name → by_type → globales."""
    by_name = (geometry.get("by_name") or {}).get(target["name"]) or {}
    by_type = (geometry.get("by_type") or {}).get(target.get("type") or "unknown") or {}

    resolved = {
        "stand_off": defaults["stand_off"],
        "altitude_fraction": defaults["altitude_fraction"],
        "viewpoints": defaults["viewpoints_per_target"],
    }
    for source in (by_type, by_name):
        for key in FLIGHT_PARAMS:
            if source.get(key) is not None:
                resolved[key] = source[key]
    return resolved


def target_block(obstacle, params):
    center = obstacle["position"]
    cx, cy, cz = pos_xyz(center)
    footprint = footprint_radius(obstacle.get("dimensions"))
    r_safe = footprint + float(obstacle["safety_margin"])
    radius = max(footprint + float(params["stand_off"]), r_safe)
    height = float(obstacle.get("height", 0.0))
    z = round(cz + height * float(params["altitude_fraction"]), 1)

    count = int(params["viewpoints"])
    waypoints = []
    for i in range(count):
        angle = 360.0 * i / count  # 0=Norte, sentido horario (convención yaw)
        rad = math.radians(angle)
        pos = {
            "x": round(cx + radius * math.sin(rad), 1) + 0.0,
            "y": round(cy + radius * math.cos(rad), 1) + 0.0,
            "z": z,
        }
        waypoints.append(
            {
                "label": ring_label(i, count, angle),
                "position": pos,
                "yaw": yaw_towards(pos, center),
            }
        )
    return {"target_name": obstacle["obstacle_name"], "waypoints": waypoints}


def takeoff_landing(drone, params):
    x, y, z = pos_xyz(drone["position"])
    point = {"x": round(x, 1), "y": round(y, 1), "z": round(z + float(params["takeoff_landing_alt"]), 1)}
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

    blocks = []
    for target in targets:  # solo los targets llevan anillo; el resto son obstáculos
        params = flight_params(target, geometry, defaults)
        blocks.append(target_block(by_name[target["name"]], params))
        print(
            f"{target['name']} ({target.get('type')}): stand_off={params['stand_off']}m "
            f"alt_frac={params['altitude_fraction']} viewpoints={params['viewpoints']}"
        )

    save_json(
        args.output,
        {
            "takeoff_landing": [takeoff_landing(d, defaults) for d in load_json(args.devices)],
            "target_blocks": blocks,
        },
    )


if __name__ == "__main__":
    main()
