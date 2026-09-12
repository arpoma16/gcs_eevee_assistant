"""Step 5 del plan de misión: orden de visita y costo, por vecino más cercano.

Lee step3_assignment.json (decisión del planner), step4_waypoints.json y
strategy_params.json; escribe step5_route.json con la forma del esquema
`Step5RouteSchema` de mcp_server. El orden dentro de cada target block conserva
el anillo, rotado para entrar por el waypoint más cercano al punto de aproximación.
"""

import argparse
import math

from pipelib import DATA_DIR, load_json, pos_xyz, save_json


def centroid(block):
    points = [pos_xyz(w["position"]) for w in block["waypoints"]]
    return {
        "x": sum(p[0] for p in points) / len(points),
        "y": sum(p[1] for p in points) / len(points),
        "z": sum(p[2] for p in points) / len(points),
    }


def order_targets(start, blocks):
    """Vecino más cercano sobre los centroides de los blocks asignados."""
    remaining = dict(blocks)
    ordered, cursor = [], start
    while remaining:
        name = min(remaining, key=lambda n: math.dist(pos_xyz(cursor), pos_xyz(centroid(remaining[n]))))
        ordered.append(name)
        cursor = centroid(remaining.pop(name))
    return ordered


def order_ring(block, approach, departure):
    """Recorre el anillo entrando por el punto más cercano a `approach`.

    La dirección (horaria o antihoraria) se elige por dónde queda la SALIDA: el
    anillo se recorre entero igual, así que girar para el otro lado no cuesta
    nada y deja el último punto del lado por el que hay que irse. Sin eso, la
    ruta sale por el punto opuesto y el tramo siguiente cruza el objeto por el
    centro — la colisión autoinfligida más común.
    """
    waypoints = block["waypoints"]
    entry = min(
        range(len(waypoints)),
        key=lambda i: math.dist(pos_xyz(approach), pos_xyz(waypoints[i]["position"])),
    )
    forward = waypoints[entry:] + waypoints[:entry]
    backward = [forward[0]] + list(reversed(forward[1:]))

    return [
        w["label"]
        for w in min(
            (forward, backward),
            key=lambda ring: math.dist(pos_xyz(departure), pos_xyz(ring[-1]["position"])),
        )
    ]


def route_for(drone_name, target_names, blocks, takeoffs, cruise_speed):
    takeoff = takeoffs[drone_name]
    assigned = {name: blocks[name] for name in target_names}
    visit_order = order_targets(takeoff["takeoff"], assigned)

    ordered_targets, path = [], [takeoff["takeoff"]]
    for index, name in enumerate(visit_order):
        # Hacia dónde hay que irse después de este bloque: el siguiente centroide,
        # o el punto de aterrizaje si es el último.
        following = visit_order[index + 1 :]
        departure = centroid(blocks[following[0]]) if following else takeoff["landing"]

        labels = order_ring(blocks[name], path[-1], departure)
        by_label = {w["label"]: w["position"] for w in blocks[name]["waypoints"]}
        path.extend(by_label[label] for label in labels)
        ordered_targets.append({"target_name": name, "ordered_labels": labels})
    path.append(takeoff["landing"])

    length = sum(math.dist(pos_xyz(a), pos_xyz(b)) for a, b in zip(path, path[1:]))
    return {
        "drone_name": drone_name,
        "ordered_targets": ordered_targets,
        "total_twc": round(length / cruise_speed, 1),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assignment", default=DATA_DIR / "step3_assignment.json")
    parser.add_argument("--waypoints", default=DATA_DIR / "step4_waypoints.json")
    parser.add_argument("--strategy", default=DATA_DIR / "strategy_params.json")
    parser.add_argument("--output", default=DATA_DIR / "step5_route.json")
    args = parser.parse_args()

    assignment = load_json(args.assignment)
    step4 = load_json(args.waypoints)
    cruise_speed = float(load_json(args.strategy)["cruise_speed"])

    blocks = {b["target_name"]: b for b in step4["target_blocks"]}
    takeoffs = {t["drone_name"]: t for t in step4["takeoff_landing"]}

    step5 = {
        "routes": [
            route_for(a["drone_name"], a["target_names"], blocks, takeoffs, cruise_speed)
            for a in assignment["assignments"]
        ]
    }
    save_json(args.output, step5)


if __name__ == "__main__":
    main()
