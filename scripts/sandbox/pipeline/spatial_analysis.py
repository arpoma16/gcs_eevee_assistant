"""Step 2 del plan de misión: análisis espacial MEDIDO (nunca estimado por el modelo).

Lee mission_input.json y escribe step2_spatial_analysis.json con la forma del
esquema `Step2SpatialAnalysisSchema` de mcp_server. Los campos narrativos
(`approach_notes`) quedan vacíos: los redacta el planner leyendo estos números.
"""

import argparse
import statistics
import sys
from itertools import combinations

from pipelib import DATA_DIR, dist3, load_json, pos_xyz, save_json


def ranked_targets(origin, targets, count, reverse=False):
    ranked = sorted(targets, key=lambda t: dist3(origin, t["position"]), reverse=reverse)
    return [
        {"target_name": t["name"], "distance": round(dist3(origin, t["position"]), 1)}
        for t in ranked[:count]
    ]


def bounding_box(targets):
    xs = [pos_xyz(t["position"])[0] for t in targets]
    ys = [pos_xyz(t["position"])[1] for t in targets]
    return min(xs), max(xs), min(ys), max(ys)


def standing_of(drone, targets):
    x, y, _ = pos_xyz(drone["position"])
    min_x, max_x, min_y, max_y = bounding_box(targets)
    inside = min_x <= x <= max_x and min_y <= y <= max_y
    cx, cy = (min_x + max_x) / 2, (min_y + max_y) / 2
    ns = "north" if y > cy else "south"
    ew = "east" if x > cx else "west"
    return f"{ns}-{ew}, {'inside' if inside else 'outside'} the field"


def extreme_pair(targets, largest):
    pair = (max if largest else min)(
        combinations(targets, 2), key=lambda p: dist3(p[0]["position"], p[1]["position"])
    )
    separation = round(dist3(pair[0]["position"], pair[1]["position"]), 1)
    return [{"target_name": t["name"], "distance": separation} for t in pair]


def typical_spacing(targets):
    nearest = [
        min(dist3(t["position"], o["position"]) for o in targets if o is not t)
        for t in targets
    ]
    return round(statistics.median(nearest), 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=DATA_DIR / "mission_input.json")
    parser.add_argument("--output", default=DATA_DIR / "step2_spatial_analysis.json")
    args = parser.parse_args()

    mission = load_json(args.input)
    targets = mission["targets"]
    if len(targets) < 2:
        sys.exit("se requieren al menos 2 targets para el análisis espacial")

    min_x, max_x, min_y, max_y = bounding_box(targets)
    spacing = typical_spacing(targets)

    step2 = {
        "drones": [
            {
                "drone_name": d["name"],
                "position": {k: round(v, 1) for k, v in zip("xyz", pos_xyz(d["position"]))},
                "standing": standing_of(d, targets),
                "nearest_targets": ranked_targets(d["position"], targets, 3),
                "farthest_targets": ranked_targets(d["position"], targets, 3, reverse=True),
            }
            for d in mission["drones"]
        ],
        "target_field": {
            "span": {"x": round(max_x - min_x, 1), "y": round(max_y - min_y, 1)},
            "typical_spacing": spacing,
            "closest_pair": extreme_pair(targets, largest=False),
            "farthest_pair": extreme_pair(targets, largest=True),
            "layout": (
                f"{len(targets)} targets over {round(max_x - min_x)}x{round(max_y - min_y)} m, "
                f"typical spacing {spacing} m (measured; describe the shape from these numbers)"
            ),
        },
        "approach_notes": "",
    }
    save_json(args.output, step2)


if __name__ == "__main__":
    main()
