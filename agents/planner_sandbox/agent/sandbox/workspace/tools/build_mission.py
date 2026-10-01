"""Ensambla data/mission.json (formato v3) a partir de views.json y assignment.json.

Por cada ruta de assignment.json: despegue sobre la posición del dron → cada
bloque en el orden dado → aterrizaje en el mismo punto. Las vistas de un bloque
se recorren en el orden en que las generó el script de inspección (los patrones
ya van en serpentina); lo único que se decide acá es el SENTIDO: hacia adelante
o al revés, el que deja la entrada más cerca de donde viene el dron y la salida
más cerca de hacia donde va.

Cada tramo que no es volable en línea recta se desvía con A* (lib/transit.py) y
los puntos de paso se insertan como waypoints `transit`, con la misma regla de
colisión que tools/validate.py: modelo completo de los targets que se
inspeccionan en los extremos del tramo, geometría simple del resto. Si un tramo
no tiene desvío posible, queda recto, se avisa, y el validador lo va a reportar.

Aborta si un target quedó sin cubrir, si un bloque está asignado dos veces o a
nadie, o si un depends_on apunta a una tarea que no existe. Nunca edites
mission.json a mano: se regenera entero cada vez.

    python3 tools/build_mission.py --speed 5 --name "Inspección palas A3"
"""
import argparse
import json
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKSPACE))

import numpy as np  # noqa: E402

from lib import mission as fmt  # noqa: E402
from lib.transit import Field, find_via  # noqa: E402
from lib.views import Safety  # noqa: E402
from lib.world import World  # noqa: E402


def dist(a, b):
    return float(np.linalg.norm(np.asarray(a, float) - np.asarray(b, float)))


def centroid(views):
    return np.mean([v["pos"] for v in views], axis=0)


def oriented(views, came_from, going_to):
    """El bloque hacia adelante o al revés, el que menos cuesta entrar y salir."""
    forward, backward = views, views[::-1]
    cost = lambda seq: dist(came_from, seq[0]["pos"]) + dist(seq[-1]["pos"], going_to)
    return min((forward, backward), key=cost)


def check(views_by_block, routes, world):
    errors = []
    assigned = [b for r in routes for b in r["blocks"]]
    for b in sorted(set(assigned)):
        if assigned.count(b) > 1:
            errors.append(f"bloque {b} asignado {assigned.count(b)} veces")
    unknown = sorted(set(assigned) - set(views_by_block))
    if unknown:
        errors.append(f"bloques que no existen en views.json: {', '.join(unknown)}")
    missing_blocks = sorted(set(views_by_block) - set(assigned))
    if missing_blocks:
        errors.append(f"bloques sin dron: {', '.join(missing_blocks)}")
    covered = {views_by_block[b][0]["target"] for b in assigned if b in views_by_block}
    missing_targets = [t.name for t in world.targets if t.name not in covered]
    if missing_targets:
        errors.append(f"targets sin cubrir: {', '.join(missing_targets)}. Ningún plan puede omitir un target")
    task_ids = [r["task_id"] for r in routes]
    if len(set(task_ids)) != len(task_ids):
        errors.append(f"task_id repetidos: {task_ids}")
    try:  # ciclos; las dependencias inexistentes se informan abajo
        fmt.finish_times({t: 0.0 for t in task_ids},
                         {r["task_id"]: [d for d in r.get("depends_on", []) if d in task_ids] for r in routes})
    except ValueError as e:
        errors.append(str(e))
    for r in routes:
        bad = [d for d in r.get("depends_on", []) if d not in task_ids]
        if bad:
            errors.append(f"{r['task_id']} depende de tareas inexistentes: {', '.join(bad)}")
        try:
            world.device(r["uav"])
        except KeyError as e:
            errors.append(str(e))
    return errors


def build_route(index, r, views_by_block, world, args):
    device = world.device(r["uav"])
    home = world.device_position(r["uav"])
    takeoff = home + [0, 0, args.takeoff_alt]
    landing = home + [0, 0, args.landing_alt]

    wps = [fmt.waypoint(takeoff, "takeoff", yaw=0)]
    cursor = takeoff
    blocks = r["blocks"]
    for i, name in enumerate(blocks):
        going_to = centroid(views_by_block[blocks[i + 1]]) if i + 1 < len(blocks) else landing
        for v in oriented(views_by_block[name], cursor, going_to):
            wps.append(fmt.waypoint(v["pos"], "inspection", yaw=v["yaw"], gimbal=v["gimbal"],
                                    target=v["target"], tag=v["tag"]))
            cursor = v["pos"]
    wps.append(fmt.waypoint(landing, "landing", yaw=0))
    wps, vias, failed = add_transits(wps, world, args.safety)

    attributes = {"idle_vel": args.speed, "max_vel": max(args.max_speed, args.speed)}
    route = fmt.route(index, r["uav"], device.get("category"), r["task_id"], wps,
                      depends_on=r.get("depends_on", []), attributes=attributes)
    length = sum(dist(a["pos"], b["pos"]) for a, b in zip(wps, wps[1:]))
    return route, length, vias, failed


def add_transits(wps, world, safety):
    """Inserta puntos de paso donde el tramo recto no es volable. (wps, n_insertados, tramos_sin_desvío)."""
    fields, out, vias, failed = {}, [wps[0]], 0, []
    for a, b in zip(wps, wps[1:]):
        context = tuple(sorted(t for t in (a.get("target"), b.get("target")) if t))
        field = fields.get(context) or fields.setdefault(context, Field(world, safety, context))
        if not field.seg_free(a["pos"], b["pos"]):
            points = find_via(field, a["pos"], b["pos"])
            if points is None:
                why = [f"{end} dentro de zona prohibida por {w}"
                       for end, w in (("el origen", field.explain(a["pos"])), ("el destino", field.explain(b["pos"])))
                       if w] or ["no hay camino libre dentro de la rejilla (obstáculos o geovalla lo cierran)"]
                failed.append(f"{a.get('tag') or a['type']} → {b.get('tag') or b['type']}: {'; '.join(why)}")
            else:
                # la cámara ya llega orientada hacia la próxima vista
                out += [fmt.waypoint(p, "transit", yaw=b["yaw"]) for p in points]
                vias += len(points)
        out.append(b)
    return out, vias, failed


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--speed", type=float, default=fmt.DEFAULT_ATTRIBUTES["idle_vel"],
                        help="velocidad de crucero (idle_vel), de MISSION PARAMETERS")
    parser.add_argument("--max-speed", type=float, default=fmt.DEFAULT_ATTRIBUTES["max_vel"])
    parser.add_argument("--takeoff-alt", type=float, default=10.0, help="altura del waypoint de despegue")
    parser.add_argument("--landing-alt", type=float, default=10.0,
                        help="altura del waypoint de aterrizaje; el dron hace su propia secuencia de descenso")
    parser.add_argument("--hover-s", type=float, default=2.0, help="segundos por foto, solo para la estimación")
    parser.add_argument("--name", default="inspection mission")
    parser.add_argument("--description", default="")
    parser.add_argument("--data", type=Path, default=WORKSPACE / "data")
    args = parser.parse_args()
    args.safety = Safety()   # los mismos límites que usa tools/validate.py por defecto

    world = World.load(args.data)
    views = json.loads((args.data / "views.json").read_text())["views"]
    routes_in = json.loads((args.data / "assignment.json").read_text())["routes"]

    views_by_block = {}
    for v in views:
        views_by_block.setdefault(v["block"], []).append(v)

    errors = check(views_by_block, routes_in, world)
    if errors:
        sys.exit("No se puede ensamblar:\n  - " + "\n  - ".join(errors))

    routes, report = [], []
    for i, r in enumerate(routes_in):
        route, length, vias, failed = build_route(i, r, views_by_block, world, args)
        routes.append(route)
        if vias:
            print(f"{route['task_id']}: {vias} puntos de paso insertados")
        for f in failed:
            print(f"{route['task_id']}: SIN DESVÍO POSIBLE {f} (queda recto; el validador lo va a reportar)")
        photos = sum(w["type"] == "inspection" for w in route["wp"])
        minutes = (length / args.speed + photos * args.hover_s) / 60
        report.append((route, length, photos, minutes))

    fmt.save(fmt.mission(routes, world.global_origin, name=args.name, description=args.description),
             args.data / "mission.json")

    finish = fmt.finish_times({r["task_id"]: m for r, _, _, m in report},
                              {r["task_id"]: r["depends_on"] for r, _, _, _ in report})
    for route, length, photos, minutes in report:
        deps = f", después de {', '.join(route['depends_on'])}" if route["depends_on"] else ""
        print(f"{route['task_id']} {route['uav']}: {len(route['wp'])} wp ({photos} fotos), "
              f"{length:.0f} m, ~{minutes:.1f} min a {args.speed} m/s{deps} · termina ~{finish[route['task_id']]:.1f} min")
    print(f"{len(routes)} rutas, {len(world.targets)} targets · duración total ~{max(finish.values()):.1f} min "
          f"(ruta crítica) -> {args.data / 'mission.json'}")


if __name__ == "__main__":
    main()
