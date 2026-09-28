"""Paso 1 del vuelo: qué drone inspecciona qué, y en qué orden.

Corre ANTES de generar un solo waypoint, porque el orden depende de dónde están
los targets, no de dónde caerán las cámaras. Con las posiciones alcanza, y
resolverlo acá deja la generación de puntos de inspección independiente: cada
target se genera después, por separado, sin afectar al plan de ruta.

Objetivo: **mínimo makespan** — la ruta individual más larga, no la suma. Dos
asignaciones con la misma distancia total no valen igual; gana la que termina
antes, porque los drones vuelan en paralelo.

Asigna por el más cercano con control de carga, ordena cada ruta por vecino más
cercano y la mejora con 2-opt. Si ya existe `step3_assignment.json` (porque la
asignación la decidiste vos), la respeta y solo ordena.

Escribe route_plan.json: `{routes: [{drone_name, target_names, legs_m, makespan_m}]}`.
"""

import argparse
import math

from pipelib import DATA_DIR, dist3, load_json, save_json


def route_length(start, names, positions):
    """Largo del recorrido centro-a-centro: despegue → targets en orden → vuelta."""
    points = [start] + [positions[n] for n in names] + [start]
    return sum(dist3(a, b) for a, b in zip(points, points[1:]))


def assign(targets, drones, positions):
    """Cada target al drone más cercano, sin dejar que uno se quede con todo.

    El tope por drone es el reparto parejo redondeado hacia arriba: sin él, un
    drone bien ubicado se lleva el campo entero y el makespan es su ruta.
    """
    cap = math.ceil(len(targets) / len(drones))
    buckets = {d["name"]: [] for d in drones}

    # Los targets más lejanos primero: los difíciles eligen mientras hay lugar.
    def hardest_first(target):
        return -min(dist3(target["position"], d["position"]) for d in drones)

    for target in sorted(targets, key=hardest_first):
        options = [d for d in drones if len(buckets[d["name"]]) < cap]
        nearest = min(options, key=lambda d: dist3(target["position"], d["position"]))
        buckets[nearest["name"]].append(target["name"])
    return buckets


def order(start, names, positions):
    """Vecino más cercano desde el despegue, y después un 2-opt hasta converger."""
    remaining, ordered, cursor = list(names), [], start
    while remaining:
        nxt = min(remaining, key=lambda n: dist3(cursor, positions[n]))
        ordered.append(nxt)
        cursor = positions[remaining.pop(remaining.index(nxt))]

    improved = True
    while improved and len(ordered) > 3:
        improved = False
        best = route_length(start, ordered, positions)
        for i in range(len(ordered) - 1):
            for j in range(i + 2, len(ordered)):
                candidate = ordered[:i + 1] + ordered[i + 1:j + 1][::-1] + ordered[j + 1:]
                length = route_length(start, candidate, positions)
                if length < best - 1e-6:
                    ordered, best, improved = candidate, length, True
    return ordered


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--targets", default=DATA_DIR / "targets.json")
    parser.add_argument("--devices", default=DATA_DIR / "devices.json")
    parser.add_argument("--assignment", default=DATA_DIR / "step3_assignment.json")
    parser.add_argument("--output", default=DATA_DIR / "route_plan.json")
    args = parser.parse_args()

    targets = load_json(args.targets)
    drones = load_json(args.devices)
    positions = {t["name"]: t["position"] for t in targets}

    try:  # una asignación tuya manda sobre la automática
        buckets = {
            a["drone_name"]: list(a["target_names"]) for a in load_json(args.assignment)["assignments"]
        }
        source = "step3_assignment.json"
    except (FileNotFoundError, KeyError):
        buckets = assign(targets, drones, positions)
        source = "reparto automático por cercanía"

    routes = []
    for drone in drones:
        names = buckets.get(drone["name"]) or []
        if not names:  # un drone sin targets no vuela
            continue
        ordered = order(drone["position"], names, positions)
        routes.append(
            {
                "drone_name": drone["name"],
                "target_names": ordered,
                "legs_m": round(route_length(drone["position"], ordered, positions), 1),
            }
        )

    makespan = max((r["legs_m"] for r in routes), default=0.0)
    save_json(args.output, {"routes": routes, "makespan_m": makespan, "assignment_source": source})
    for r in routes:
        print(f"{r['drone_name']}: {' -> '.join(r['target_names'])}  ({r['legs_m']} m)")
    print(f"makespan {makespan} m · asignación: {source}")


if __name__ == "__main__":
    main()
