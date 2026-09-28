"""Revisa los puntos de inspección de cada target, uno por uno.

Corre apenas generás los waypoints de un target y ANTES de ensamblar la misión:
un punto mal puesto se arregla acá, barato y aislado, mientras que descubrirlo
en el gate significa gastar una iteración y repasar la misión entera.

Para cada waypoint mide su distancia horizontal al eje de cada objeto de
colisión, y solo cuenta si además se superponen en altura — pasar 5 m por encima
de un techo de 12 m no es chocarlo:

  EXCLUSIÓN  dentro de la geometría real del objeto. Nunca, bajo ningún criterio.
  PRECAUCIÓN dentro del margen de seguridad. Ningún waypoint debería quedar ahí.

Con `--fix` empuja los infractores radialmente hacia afuera, alejándolos del
centro del objeto que invaden hasta despejar su radio de seguridad, y conserva
la altura. Sin `--fix` solo informa: si el patrón está mal pensado, moverlos es
tapar el síntoma — mirá primero POR QUÉ cayeron adentro.
"""

import argparse
import math
import sys

from pipelib import footprint_radius, load_json, pos_xyz, save_json, DATA_DIR

MARGIN = 0.1  # tolerancia de redondeo, en metros


def zones(obstacle):
    footprint = footprint_radius(obstacle["dimensions"])
    return footprint, footprint + float(obstacle["safety_margin"])


def overlaps_vertically(z, obstacle):
    base = float(obstacle["position"].get("z", 0.0))
    return base <= z <= base + float(obstacle["height"])


def offenders(position, obstacles):
    """Objetos cuyo espacio invade este waypoint, del más grave al menos."""
    x, y, z = pos_xyz(position)
    found = []
    for obstacle in obstacles:
        if not overlaps_vertically(z, obstacle):
            continue
        ox, oy, _ = pos_xyz(obstacle["position"])
        distance = math.hypot(x - ox, y - oy)
        footprint, r_safe = zones(obstacle)
        if distance < footprint - MARGIN:
            found.append((obstacle, distance, r_safe, "EXCLUSIÓN"))
        elif distance < r_safe - MARGIN:
            found.append((obstacle, distance, r_safe, "PRECAUCIÓN"))
    return sorted(found, key=lambda f: f[1])


def push_out(position, obstacle, r_safe):
    """Aleja el waypoint del centro del objeto hasta despejar su radio de seguridad."""
    x, y, z = pos_xyz(position)
    ox, oy, _ = pos_xyz(obstacle["position"])
    dx, dy = x - ox, y - oy
    distance = math.hypot(dx, dy)
    if distance < MARGIN:  # justo sobre el eje: no hay dirección, elegimos el Norte
        dx, dy, distance = 0.0, 1.0, 1.0
    scale = (r_safe + MARGIN) / distance
    return {"x": round(ox + dx * scale, 1) + 0.0, "y": round(oy + dy * scale, 1) + 0.0, "z": z}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--waypoints", default=DATA_DIR / "step4_waypoints.json")
    parser.add_argument("--collision-objects", default=DATA_DIR / "collision_objects.json")
    parser.add_argument("--target", help="Revisar un solo target por nombre")
    parser.add_argument("--fix", action="store_true", help="Empujar los infractores fuera del radio de seguridad")
    args = parser.parse_args()

    step4 = load_json(args.waypoints)
    obstacles = load_json(args.collision_objects)

    blocks = step4["target_blocks"]
    if args.target:
        blocks = [b for b in blocks if b["target_name"] == args.target]
        if not blocks:
            sys.exit(f"No hay waypoints para '{args.target}'. ¿Corriste generate_waypoints.py?")

    excluded = caution = fixed = 0
    for block in blocks:
        for wp in block["waypoints"]:
            found = offenders(wp["position"], obstacles)
            if not found:
                continue
            obstacle, distance, r_safe, zone = found[0]
            excluded += zone == "EXCLUSIÓN"
            caution += zone == "PRECAUCIÓN"
            print(
                f"{zone:10} {block['target_name']}/{wp['label']}: a {distance:.1f} m del eje de "
                f"{obstacle['obstacle_name']} (seguro desde {r_safe:.1f} m)"
            )
            if args.fix:
                wp["position"] = push_out(wp["position"], obstacle, r_safe)
                fixed += 1
                print(f"           → movido a ({wp['position']['x']}, {wp['position']['y']}, {wp['position']['z']})")

    total = sum(len(b["waypoints"]) for b in blocks)
    if args.fix and fixed:
        save_json(args.waypoints, step4)

    if not excluded and not caution:
        print(f"{total} waypoints revisados en {len(blocks)} target(s): todos despejados")
        return

    print(f"\n{total} waypoints: {excluded} en exclusión, {caution} en precaución" + (f", {fixed} movidos" if fixed else ""))
    if excluded and not args.fix:
        sys.exit(
            "Hay waypoints dentro de la geometría de un objeto. Revisá el patrón y el modelo de "
            "colisión antes de moverlos: si inspeccionás las PARTES de una estructura, el sólido a "
            "esquivar suele ser su cuerpo, no su envolvente."
        )


if __name__ == "__main__":
    main()
