"""Asignación básica: qué dron vuela cada bloque de views.json, y en qué orden.

La unidad es el BLOQUE (campo `block` de cada vista), no el target: un script
de inspección que parte un target en varios bloques permite que lo compartan
varios drones. Objetivo: mínimo makespan (la ruta más larga, no la suma).

  1. Estima el costo de cada bloque: su recorrido interno (vista a vista) más la
     distancia al resto de la ruta, medida entre centroides.
  2. Reparte los bloques de mayor a menor costo, cada uno al dron cuya ruta
     estimada queda más corta al sumarlo.
  3. Ordena cada ruta por vecino más cercano desde el despegue y la mejora con
     2-opt (volviendo al despegue).

Escribe data/assignment.json:
    {"routes": [{"uav", "task_id", "depends_on", "blocks", "est_length_m"}], "makespan_m"}

Cuando el pedido se sale de esto (dos drones sobre el mismo target en secuencia,
un dron reservado, dependencias entre tareas), escribí tu propio
scripts/assignment.py con la MISMA salida. Si solo querés fijar quién vuela qué
y dejar el orden a este script, escribí assignment.json y corré con --keep.

    python3 tools/assign.py            # reparto automático
    python3 tools/assign.py --keep     # respeta uav/blocks/task_id/depends_on, solo reordena
"""
import argparse
import json
import math
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKSPACE))

import numpy as np  # noqa: E402

from lib.mission import finish_times, sequenced  # noqa: E402
from lib.world import World  # noqa: E402


def load_blocks(views):
    """{block: {"target", "centroid", "internal_m", "n"}} en el orden de aparición."""
    grouped = {}
    for v in views:
        grouped.setdefault(v["block"], []).append(v)
    blocks = {}
    for name, vs in grouped.items():
        P = np.array([v["pos"] for v in vs], float)
        blocks[name] = {
            "target": vs[0]["target"],
            "centroid": P.mean(axis=0),
            "internal_m": float(np.linalg.norm(np.diff(P, axis=0), axis=1).sum()) if len(P) > 1 else 0.0,
            "n": len(vs),
        }
    return blocks


def route_length(start, names, blocks):
    points = [start] + [blocks[n]["centroid"] for n in names] + [start]
    legs = sum(float(np.linalg.norm(b - a)) for a, b in zip(points, points[1:]))
    return legs + sum(blocks[n]["internal_m"] for n in names)


def order(start, names, blocks):
    """Vecino más cercano desde el despegue y 2-opt hasta converger."""
    remaining, ordered, cursor = list(names), [], start
    while remaining:
        nxt = min(remaining, key=lambda n: float(np.linalg.norm(blocks[n]["centroid"] - cursor)))
        ordered.append(nxt)
        remaining.remove(nxt)
        cursor = blocks[nxt]["centroid"]
    improved = True
    while improved and len(ordered) > 2:
        improved = False
        best = route_length(start, ordered, blocks)
        for i in range(len(ordered) - 1):
            for j in range(i + 1, len(ordered)):
                candidate = ordered[:i] + ordered[i:j + 1][::-1] + ordered[j + 1:]
                length = route_length(start, candidate, blocks)
                if length < best - 1e-6:
                    ordered, best, improved = candidate, length, True
    return ordered


def assign(blocks, starts):
    """Bloques de mayor a menor costo, cada uno al dron que menos alarga su ruta estimada."""
    buckets = {uav: [] for uav in starts}

    def cost(name):
        return blocks[name]["internal_m"] + 2 * min(float(np.linalg.norm(blocks[name]["centroid"] - s))
                                                    for s in starts.values())

    for name in sorted(blocks, key=cost, reverse=True):
        uav = min(starts, key=lambda u: route_length(starts[u], order(starts[u], buckets[u] + [name], blocks),
                                                     blocks))
        buckets[uav].append(name)
    return buckets


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--keep", action="store_true", help="respetar data/assignment.json y solo reordenar")
    parser.add_argument("--data", type=Path, default=WORKSPACE / "data")
    args = parser.parse_args()

    world = World.load(args.data)
    views = json.loads((args.data / "views.json").read_text())["views"]
    blocks = load_blocks(views)
    starts = {d["name"]: world.device_position(d["name"]) for d in world.devices}
    out_path = args.data / "assignment.json"

    if args.keep:
        given = json.loads(out_path.read_text())["routes"]
        unknown = [b for r in given for b in r["blocks"] if b not in blocks]
        if unknown:
            sys.exit(f"Bloques que no existen en views.json: {', '.join(unknown)}")
        routes = [{**r, "blocks": order(starts[r["uav"]], r["blocks"], blocks)} for r in given]
        source = "assignment.json (--keep)"
    else:
        buckets = assign(blocks, starts)
        routes = [{"uav": uav, "task_id": f"T{i + 1}", "depends_on": [], "blocks": order(starts[uav], names, blocks)}
                  for i, (uav, names) in enumerate((u, n) for u, n in buckets.items() if n)]
        source = "reparto automático"

    for r in routes:
        r["est_length_m"] = round(route_length(starts[r["uav"]], r["blocks"], blocks), 1)
    deps = {r["task_id"]: list(r.get("depends_on", [])) for r in routes}
    try:
        # con depends_on, una tarea arranca cuando termina la anterior: ruta crítica, no el máximo
        finish = finish_times({r["task_id"]: r["est_length_m"] for r in routes}, deps)
    except ValueError as e:
        sys.exit(str(e))
    makespan = round(max(finish.values(), default=0.0), 1)
    out_path.write_text(json.dumps({"routes": routes, "makespan_m": makespan, "source": source},
                                   indent=1, ensure_ascii=False))

    for r in routes:
        deps_txt = f" (después de {', '.join(r['depends_on'])}, termina en ~{finish[r['task_id']]:.0f} m)" \
            if r.get("depends_on") else ""
        print(f"{r['task_id']} {r['uav']}: {' -> '.join(r['blocks'])}  ~{r['est_length_m']} m{deps_txt}")
    tasks_by_target = {}
    for r in routes:
        for b in r["blocks"]:
            tasks_by_target.setdefault(blocks[b]["target"], set()).add((r["task_id"], r["uav"]))
    for target, tasks in tasks_by_target.items():
        tasks = sorted(tasks)
        overlap = [(a, b) for i, a in enumerate(tasks) for b in tasks[i + 1:]
                   if a[1] != b[1] and not sequenced(a[0], b[0], deps)]
        if overlap:
            pairs = ", ".join(f"{a[1]}({a[0]})/{b[1]}({b[0]})" for a, b in overlap)
            print(f"AVISO {target} lo pueden inspeccionar a la vez {pairs}: la separación entre drones no se "
                  f"valida todavía; encadenalos con depends_on si no deben coincidir.")
    print(f"makespan estimado {makespan} m (ruta crítica) · {source} -> {out_path}")


if __name__ == "__main__":
    main()
