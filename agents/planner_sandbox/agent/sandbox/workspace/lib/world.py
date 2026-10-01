"""El escenario de la misión, leído de /workspace/data.

    from lib.world import World
    world = World.load()
    for target in world.targets_of_type("Wind Turbine"):
        model = target.model          # modelo INSEM con el estado y la pose de ESTE target
        others = world.simple_objects(exclude=[target.name])

Dos representaciones de un elemento, según para qué:

- `Target.model`: el modelo caracterizado completo. Solo para el target que se
  está inspeccionando (acercarse a una pala exige la geometría real).
- `SimpleObject`: la geometría simple del catálogo (`geometry` de
  element_types.json: circle o rectangle con altura), en su posición y orientada
  por su azimFront. Para todo lo demás: obstáculos y targets que no estás
  inspeccionando en ese momento. Los obstáculos nunca tienen modelo ni estado.

Convenciones: ENU en metros (x = Este, y = Norte, z = Arriba), `position` es el
centro de la huella a nivel del suelo; azimFront en grados de brújula (0 = N,
horario). Un `rectangle` con azimFront = 0 tiene `width` sobre X y `length` sobre Y.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

import numpy as np

from lib.model import Model

WORKSPACE = Path(__file__).resolve().parents[1]
DATA_DIR = WORKSPACE / "data"


def _load_json(path):
    return json.loads(Path(path).read_text())


def _xyz(p):
    return np.array([p["x"], p["y"], p["z"]], float) if isinstance(p, dict) else np.asarray(p, float)


@dataclass
class SimpleObject:
    """Prisma vertical: cilindro (circle) o caja orientada (rectangle), desde el suelo hasta `height`."""
    name: str
    type: str
    kind: str                 # "circle" | "rectangle"
    position: np.ndarray      # centro de la huella, a nivel del suelo
    azim_front: float
    height: float
    radius: float = 0.0
    width: float = 0.0        # extensión sobre X local (Este con azimFront = 0)
    length: float = 0.0       # extensión sobre Y local (Norte con azimFront = 0)

    @classmethod
    def from_catalog(cls, element, geometry):
        g = geometry or {}
        dims = g.get("dimensions") or {}
        kind = g.get("geometry_type")
        height = dims.get("height", g.get("height"))
        if kind not in ("circle", "rectangle") or height is None:
            raise ValueError(f"{element['name']} ({element['type']}): geometría de catálogo incompleta {geometry!r}")
        return cls(element["name"], element["type"], kind, _xyz(element["position"]),
                   float(element.get("azimFront") or 0.0), float(height),
                   radius=float(dims.get("radius", 0.0)), width=float(dims.get("width", 0.0)),
                   length=float(dims.get("length", 0.0)))

    def _dxy(self, P):
        """Distancia firmada en planta (P ya relativo a `position`)."""
        if self.kind == "circle":
            return np.hypot(P[:, 0], P[:, 1]) - self.radius
        # al marco local: rotar por +azimFront (brújula horario == ENU antihorario negativo)
        th = math.radians(self.azim_front)
        lx = P[:, 0] * math.cos(th) - P[:, 1] * math.sin(th)
        ly = P[:, 0] * math.sin(th) + P[:, 1] * math.cos(th)
        qx, qy = np.abs(lx) - self.width / 2, np.abs(ly) - self.length / 2
        return np.hypot(np.maximum(qx, 0), np.maximum(qy, 0)) + np.minimum(np.maximum(qx, qy), 0)

    def horizontal_distance(self, xy):
        """Distancia en planta de `xy` a la huella (0 si está encima)."""
        P = np.array([[xy[0] - self.position[0], xy[1] - self.position[1], 0.0]])
        return max(0.0, float(self._dxy(P)[0]))

    def sdf(self, P):
        """Distancia firmada (mundo, N×3). Negativa dentro."""
        P = np.atleast_2d(np.asarray(P, float)) - self.position
        z = P[:, 2]
        dxy = self._dxy(P)
        dz = np.maximum(-z, z - self.height)            # >0 fuera en vertical
        outside = np.hypot(np.maximum(dxy, 0), np.maximum(dz, 0))
        inside = np.minimum(np.maximum(dxy, dz), 0)
        return outside + inside


@dataclass
class Target:
    id: int | str
    name: str
    type: str
    position: np.ndarray
    azim_front: float
    attributes: dict
    model_file: Path | None
    raw: dict = field(repr=False, default_factory=dict)

    @cached_property
    def model(self) -> Model:
        if self.model_file is None:
            raise ValueError(f"{self.name} ({self.type}) no tiene model_file")
        return Model(self.model_file, state=self.attributes, origin=self.position, azim_front=self.azim_front)


class World:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        origin = _load_json(self.data_dir / "origin.json")
        self.global_origin = origin["global_origin"]
        self.boundaries = origin.get("boundaries")
        self.devices = _load_json(self.data_dir / "devices.json")
        self.element_types = {t["type"]: t for t in _load_json(self.data_dir / "element_types.json")}
        self._targets_raw = _load_json(self.data_dir / "targets.json")
        self._obstacles_raw = _load_json(self.data_dir / "obstacles.json")
        self.targets = [self._target(t) for t in self._targets_raw]
        self._by_name = {t.name: t for t in self.targets}

    @classmethod
    def load(cls, data_dir=DATA_DIR):
        return cls(data_dir)

    def _model_path(self, type_name):
        entry = self.element_types.get(type_name) or {}
        mf = entry.get("model_file")
        if not mf:
            return None
        path = Path(mf)
        return path if path.is_absolute() else self.data_dir.parent / path

    def _target(self, t):
        return Target(t["id"], t["name"], t["type"], _xyz(t["position"]), float(t.get("azimFront") or 0.0),
                      dict(t.get("attributes") or {}), self._model_path(t["type"]), t)

    # ------------------------------------------------------------------
    def target(self, name) -> Target:
        if name not in self._by_name:
            raise KeyError(f"{name!r} no es un target. Targets: {', '.join(self._by_name)}")
        return self._by_name[name]

    def targets_of_type(self, type_name):
        return [t for t in self.targets if t.type == type_name]

    def device(self, name):
        for d in self.devices:
            if d["name"] == name:
                return d
        raise KeyError(f"{name!r} no es un dron de la misión")

    def device_position(self, name):
        return _xyz(self.device(name)["position"])

    def simple_objects(self, exclude=()):
        """Todos los elementos (targets + obstáculos) con su geometría simple de catálogo, menos `exclude`."""
        out = []
        for e in self._targets_raw + self._obstacles_raw:
            if e["name"] in exclude:
                continue
            geometry = (self.element_types.get(e["type"]) or {}).get("geometry")
            out.append(SimpleObject.from_catalog(e, geometry))
        return out

    def geofence(self):
        """(min_xy, max_xy) de origin.json, o None si no hay límites."""
        b = self.boundaries
        if not b:
            return None
        return (np.array([b["min"]["x"], b["min"]["y"]], float), np.array([b["max"]["x"], b["max"]["y"]], float))
