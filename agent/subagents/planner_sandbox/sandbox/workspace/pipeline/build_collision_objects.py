"""Step 1: merge the dimensions YOU derived with the positions the GCS resolved.

The catalog carries each element's physical characteristics as prose inside
`description`, so extracting them is a reading task and it is yours. Positions
are already in the briefing and must never be retyped: this script takes your
`target_dimensions.json` (keyed by element name, no coordinates) and joins it
with the XYZ positions from `mission_input.json`.

Writes collision_objects.json in the exact shape validate_mission expects.
"""

import argparse
import sys

from pipelib import DATA_DIR, load_json, save_json


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
        # z is GROUND level: height extends upward from it.
        "position": {"x": position["x"], "y": position["y"], "z": position.get("z", 0.0)},
        "dimensions": dimensions,
        "safety_margin": float(dims["safety_margin"]),
        "height": float(dims["height"]),
        "yaw": float(dims.get("yaw", 0.0)),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=DATA_DIR / "mission_input.json")
    parser.add_argument("--dimensions", default=DATA_DIR / "target_dimensions.json")
    parser.add_argument("--output", default=DATA_DIR / "collision_objects.json")
    args = parser.parse_args()

    mission = load_json(args.input)
    dimensions = load_json(args.dimensions)

    # Inspection targets are obstacles too — they are solid objects to fly around.
    elements = list(mission["targets"]) + list(mission.get("obstacles") or [])

    missing = [e["name"] for e in elements if e["name"] not in dimensions]
    if missing:
        sys.exit(
            "No dimensions provided for: "
            + ", ".join(missing)
            + ". Every target AND every obstacle needs an entry in target_dimensions.json."
        )

    save_json(args.output, [build(e, dimensions[e["name"]]) for e in elements])


if __name__ == "__main__":
    main()
