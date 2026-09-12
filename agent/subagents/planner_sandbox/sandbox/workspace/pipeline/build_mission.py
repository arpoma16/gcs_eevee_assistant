"""Ensambla la misión final a partir de las salidas del pipeline.

Toma el orden de ruta (step5) y la geometría de waypoints (step4) y escribe
mission.json con la forma que espera el validador del GCS:
`{description, global_origin, route:[{name, uav, attributes, wp:[...]}]}`.

Verifica cobertura antes de escribir: si algún target quedó sin asignar, aborta.
Es la misma garantía que da `submit_mission_plan` server-side, aplicada acá para
no tener que mandar el plan entero a través del modelo.
"""

import argparse
import sys

from pipelib import DATA_DIR, load_json, pos_xyz, save_json


def waypoint(wp_type, position, yaw, target_name=None):
    x, y, z = pos_xyz(position)
    entry = {"type": wp_type, "pos": [x, y, max(z, 0.0)], "yaw": float(yaw)}
    if target_name:
        entry["target_name"] = target_name
    return entry


def build_route(plan_route, blocks, takeoffs, params):
    drone = plan_route["drone_name"]
    takeoff = takeoffs[drone]

    wps = [waypoint("takeoff", takeoff["takeoff"], 0)]
    for ordered in plan_route["ordered_targets"]:
        name = ordered["target_name"]
        by_label = {w["label"]: w for w in blocks[name]["waypoints"]}
        for label in ordered["ordered_labels"]:
            w = by_label[label]
            wps.append(waypoint("inspection", w["position"], w["yaw"], target_name=name))
    wps.append(waypoint("landing", takeoff["landing"], 0))

    targets = ", ".join(o["target_name"] for o in plan_route["ordered_targets"])
    return {
        "name": f"route_{drone}",
        "description": f"Inspection route for {drone}: {targets}",
        "uav": drone,
        "attributes": {"idle_vel": float(params["cruise_speed"]), "mode_yaw": 3},
        "wp": wps,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--targets", default=DATA_DIR / "targets.json")
    parser.add_argument("--origin", default=DATA_DIR / "origin.json")
    parser.add_argument("--waypoints", default=DATA_DIR / "step4_waypoints.json")
    parser.add_argument("--routes", default=DATA_DIR / "step5_route.json")
    parser.add_argument("--strategy", default=DATA_DIR / "strategy_params.json")
    parser.add_argument("--output", default=DATA_DIR / "mission.json")
    parser.add_argument("--description", default="Multi-UAV inspection mission")
    args = parser.parse_args()

    targets = load_json(args.targets)
    origin = load_json(args.origin)
    step4 = load_json(args.waypoints)
    step5 = load_json(args.routes)
    params = load_json(args.strategy)

    blocks = {b["target_name"]: b for b in step4["target_blocks"]}
    takeoffs = {t["drone_name"]: t for t in step4["takeoff_landing"]}

    expected = {t["name"] for t in targets}
    covered = {o["target_name"] for r in step5["routes"] for o in r["ordered_targets"]}
    if expected - covered:
        sys.exit(f"Targets sin asignar: {', '.join(sorted(expected - covered))}. Ningún plan puede omitir un target.")
    if covered - expected:
        sys.exit(f"Targets inventados: {', '.join(sorted(covered - expected))}. Solo se pueden inspeccionar los del briefing.")

    mission = {
        "description": args.description,
        "global_origin": origin["global_origin"],
        "route": [build_route(r, blocks, takeoffs, params) for r in step5["routes"]],
    }
    save_json(args.output, mission)
    print(f"{len(mission['route'])} rutas, {sum(len(r['wp']) for r in mission['route'])} waypoints, {len(expected)} targets cubiertos")


if __name__ == "__main__":
    main()
