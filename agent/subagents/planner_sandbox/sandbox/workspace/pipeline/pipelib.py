"""Helpers compartidos del pipeline: I/O de /workspace/data y geometría básica."""

import json
import math
import os
from pathlib import Path

# Dentro del sandbox siempre es /workspace/data; la variable existe para poder
# correr el pipeline contra fixtures fuera del sandbox.
DATA_DIR = Path(os.environ.get("MISSION_DATA_DIR", "/workspace/data"))


def load_json(path):
    return json.loads(Path(path).read_text())


def save_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {path}")


def pos_xyz(p):
    return (float(p["x"]), float(p["y"]), float(p.get("z", 0.0)))


def dist3(a, b):
    return math.dist(pos_xyz(a), pos_xyz(b))


def dist2(a, b):
    ax, ay, _ = pos_xyz(a)
    bx, by, _ = pos_xyz(b)
    return math.hypot(bx - ax, by - ay)


def yaw_towards(from_pos, to_pos):
    """Yaw hacia to_pos: 0=Norte, 90=Este, en el rango [-180, 180] que exige el GCS."""
    fx, fy, _ = pos_xyz(from_pos)
    tx, ty, _ = pos_xyz(to_pos)
    degrees = math.degrees(math.atan2(tx - fx, ty - fy))
    return round((degrees + 180.0) % 360.0 - 180.0, 1)


def footprint_radius(dimensions):
    """Radio del footprint real: radius si es circular, media diagonal si es rectangular."""
    if not dimensions:
        return 0.0
    if dimensions.get("radius") is not None:
        return float(dimensions["radius"])
    width = float(dimensions.get("width", 0.0))
    length = float(dimensions.get("length", 0.0))
    return math.hypot(width, length) / 2.0
