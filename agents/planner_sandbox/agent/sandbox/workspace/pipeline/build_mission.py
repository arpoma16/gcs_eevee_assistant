"""Ensambla la misión final, siguiendo el orden que ya decidió plan_routes.py.

El orden de visita viene dado. Lo que sí necesita los waypoints —y por eso se
resuelve acá— es por dónde ENTRA y por dónde SALE la ruta de cada target: el
anillo se recorre entero igual, así que girar para el otro lado no cuesta nada y
deja el último punto del lado por el que hay que irse. Sin eso, la ruta sale por
el punto opuesto y el tramo siguiente cruza el objeto por el centro.

Escribe mission.json con la forma que espera el validador del GCS, y aborta si
algún target quedó sin cubrir o apareció uno que no estaba en el briefing.
"""

import argparse
import math
import sys

from pipelib import DATA_DIR, dist3, load_json, pos_xyz, save_json


def centroid(waypoints):
    points = [pos_xyz(w["position"]) for w in waypoints]
    return {
        "x": sum(p[0] for p in points) / len(points),
        "y": sum(p[1] for p in points) / len(points),
        "z": sum(p[2] for p in points) / len(points),
    }


def walk_block(waypoints, approach, departure):
    """Recorre el bloque entrando por el punto más cercano a `approach`.

    La dirección se elige por dónde queda la SALIDA, para que el tramo siguiente
    arranque del lado correcto.
    """
    entry = min(range(len(waypoints)), key=lambda i: dist3(approach, waypoints[i]["position"]))
    forward = waypoints[entry:] + waypoints[:entry]
    backward = [forward[0]] + list(reversed(forward[1:]))
    return min((forward, backward), key=lambda ring: dist3(departure, ring[-1]["position"]))


def waypoint(wp_type, position, yaw, target_name=None):
    x, y, z = pos_xyz(position)
    entry = {"type": wp_type, "pos": [x, y, max(z, 0.0)], "yaw": float(yaw)}
    if target_name:
        entry["target_name"] = target_name
    return entry


def build_route(plan, blocks, takeoffs, params):
    drone = plan["drone_name"]
    takeoff = takeoffs[drone]
    names = plan["target_names"]

    wps = [waypoint("takeoff", takeoff["takeoff"], 0)]
    path = [takeoff["takeoff"]]

    for index, name in enumerate(names):
        following = names[index + 1:]
        departure = centroid(blocks[following[0]]["waypoints"]) if following else takeoff["landing"]

        for wp in walk_block(blocks[name]["waypoints"], path[-1], departure):
            wps.append(waypoint("inspection", wp["position"], wp["yaw"], target_name=name))
            path.append(wp["position"])

    wps.append(waypoint("landing", takeoff["landing"], 0))
    path.append(takeoff["landing"])

    length = sum(dist3(a, b) for a, b in zip(path, path[1:]))
    return {
        "name": f"route_{drone}",
        "description": f"Inspection route for {drone}: {', '.join(names)}",
        "uav": drone,
        "attributes": {"idle_vel": float(params["cruise_speed"]), "mode_yaw": 3},
        "wp": wps,
    }, length


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--targets", default=DATA_DIR / "targets.json")
    parser.add_argument("--origin", default=DATA_DIR / "origin.json")
    parser.add_argument("--plan", default=DATA_DIR / "route_plan.json")
    parser.add_argument("--waypoints", default=DATA_DIR / "step4_waypoints.json")
    parser.add_argument("--strategy", default=DATA_DIR / "strategy_params.json")
    parser.add_argument("--output", default=DATA_DIR / "mission.json")
    parser.add_argument("--description", default="Multi-UAV inspection mission")
    args = parser.parse_args()

    targets = load_json(args.targets)
    origin = load_json(args.origin)
    plan = load_json(args.plan)
    step4 = load_json(args.waypoints)
    params = load_json(args.strategy)

    blocks = {b["target_name"]: b for b in step4["target_blocks"]}
    takeoffs = {t["drone_name"]: t for t in step4["takeoff_landing"]}

    expected = {t["name"] for t in targets}
    covered = {name for r in plan["routes"] for name in r["target_names"]}
    if expected - covered:
        sys.exit(f"Targets sin asignar: {', '.join(sorted(expected - covered))}. Ningún plan puede omitir un target.")
    if covered - expected:
        sys.exit(f"Targets inventados: {', '.join(sorted(covered - expected))}. Solo se pueden inspeccionar los del briefing.")
    if missing := covered - set(blocks):
        sys.exit(f"Sin waypoints para: {', '.join(sorted(missing))}. Corré generate_waypoints.py primero.")

    routes, lengths = [], {}
    for plan_route in plan["routes"]:
        route, length = build_route(plan_route, blocks, takeoffs, params)
        routes.append(route)
        lengths[route["uav"]] = round(length, 1)

    save_json(args.output, {
        "description": args.description,
        "global_origin": origin["global_origin"],
        "route": routes,
    })

    speed = float(params["cruise_speed"])
    for uav, length in lengths.items():
        print(f"{uav}: {length} m  ({round(length / speed / 60, 1)} min a {speed} m/s)")
    print(
        f"{len(routes)} rutas, {sum(len(r['wp']) for r in routes)} waypoints, "
        f"{len(expected)} targets · makespan {max(lengths.values())} m"
    )


if __name__ == "__main__":
    main()
