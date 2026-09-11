"""Helpers compartidos del pipeline: I/O de /workspace/data y geometría básica."""

import json
import math
from pathlib import Path

DATA_DIR = Path("/workspace/data")


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
    """Yaw en grados hacia to_pos, convención de la plataforma: 0=Norte, 90=Este."""
    fx, fy, _ = pos_xyz(from_pos)
    tx, ty, _ = pos_xyz(to_pos)
    return round(math.degrees(math.atan2(tx - fx, ty - fy)) % 360.0, 1)


def footprint_radius(dimensions):
    """Radio del footprint real: radius si es circular, media diagonal si es rectangular."""
    if not dimensions:
        return 0.0
    if dimensions.get("radius") is not None:
        return float(dimensions["radius"])
    width = float(dimensions.get("width", 0.0))
    length = float(dimensions.get("length", 0.0))
    return math.hypot(width, length) / 2.0
