"""Step 4 del plan de misión: generación determinista de waypoints.

Lee mission_input.json + strategy_params.json y escribe step4_waypoints.json
con la forma del esquema `Step4WaypointsSchema` de mcp_server:
- takeoff/landing por drone (XY de la posición inicial, Z = z + takeoff_landing_alt)
- un target_block por target: anillo de viewpoints a stand_off del footprint,
  Z por fracción de la altura del target, yaw apuntando al centro (0=Norte, 90=Este).
"""

import argparse
import math

from pipelib import DATA_DIR, footprint_radius, load_json, pos_xyz, save_json, yaw_towards

COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


def ring_label(index, count, angle_deg):
    if count <= len(COMPASS) and count in (4, 8):
        return COMPASS[index * (len(COMPASS) // count)]
    return f"P{index + 1}-{round(angle_deg)}deg"


def target_block(target, params):
    center = target["position"]
    cx, cy, cz = pos_xyz(center)
    radius = footprint_radius(target.get("dimensions")) + float(params["stand_off"])
    height = float(target.get("dimensions", {}).get("height", 0.0))
    z = round(cz + height * float(params["altitude_fraction"]), 1)

    count = int(params["viewpoints_per_target"])
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
    return {"target_name": target["name"], "waypoints": waypoints}


def takeoff_landing(drone, params):
    x, y, z = pos_xyz(drone["position"])
    point = {"x": round(x, 1), "y": round(y, 1), "z": round(z + float(params["takeoff_landing_alt"]), 1)}
    return {"drone_name": drone["name"], "takeoff": point, "landing": dict(point)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=DATA_DIR / "mission_input.json")
    parser.add_argument("--strategy", default=DATA_DIR / "strategy_params.json")
    parser.add_argument("--output", default=DATA_DIR / "step4_waypoints.json")
    args = parser.parse_args()

    mission = load_json(args.input)
    params = load_json(args.strategy)

    step4 = {
        "takeoff_landing": [takeoff_landing(d, params) for d in mission["drones"]],
        "target_blocks": [target_block(t, params) for t in mission["targets"]],
    }
    save_json(args.output, step4)


if __name__ == "__main__":
    main()
