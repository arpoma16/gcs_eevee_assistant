"""Step 1: expande la geometría por tipo y la une con las posiciones del GCS.

El catálogo guarda las características físicas en la descripción del GRUPO, así
que una sola entrada por TIPO cubre todos sus elementos: dieciséis turbinas
comparten una geometría. Este script toma tu `geometry.json` (por tipo, sin
coordenadas), lo expande a cada elemento y lo une con su posición real.

Escribe collision_objects.json con la forma exacta que espera el validador.
"""

import argparse
import sys

from pipelib import DATA_DIR, load_json, save_json


def resolve(element, geometry):
    """Geometría de un elemento: override por nombre si existe, si no por tipo."""
    by_name = geometry.get("by_name") or {}
    by_type = geometry.get("by_type") or {}
    return by_name.get(element["name"]) or by_type.get(element.get("type") or "unknown")


def build(element, dims):
    geometry_type = dims.get("geometry_type", "circle")
    if geometry_type == "circle":
        dimensions = {"radius": float(dims["radius"])}
    else:
        dimensions = {"width": float(dims["width"]), "length": float(dims["length"])}

    position = element["position"]
    return {
        "obstacle_id": str(element.get("id", element["name"])),
        "obstacle_name": element["name"],
        "geometry_type": geometry_type,
        # z es el nivel del SUELO: la altura se extiende hacia arriba desde ahí.
        "position": {"x": position["x"], "y": position["y"], "z": position.get("z", 0.0)},
        "dimensions": dimensions,
        "safety_margin": float(dims["safety_margin"]),
        "height": float(dims["height"]),
        "yaw": float(dims.get("yaw", 0.0)),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--targets", default=DATA_DIR / "targets.json")
    parser.add_argument("--obstacles", default=DATA_DIR / "obstacles.json")
    parser.add_argument("--geometry", default=DATA_DIR / "geometry.json")
    parser.add_argument("--output", default=DATA_DIR / "collision_objects.json")
    args = parser.parse_args()

    geometry = load_json(args.geometry)
    # Los targets también son obstáculos: son objetos sólidos que hay que esquivar.
    elements = load_json(args.targets) + load_json(args.obstacles)

    resolved = [(e, resolve(e, geometry)) for e in elements]
    missing = sorted({f"{e['name']} (type: {e.get('type')})" for e, dims in resolved if not dims})
    if missing:
        sys.exit(
            "Sin geometría para: "
            + ", ".join(missing)
            + ".\nAgregá su tipo en by_type (o el elemento en by_name) dentro de geometry.json."
        )

    save_json(args.output, [build(e, dims) for e, dims in resolved])
    print(f"{len(resolved)} objetos de colisión desde {len(geometry.get('by_type') or {})} tipo(s)")


if __name__ == "__main__":
    main()
