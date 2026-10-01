"""Modelo caracterizado de un tipo de elemento (formato insem/0.2).

Port de la parte de modelo de /home/grvc/work/px4/wtsem/insem/insem.py: expresiones
seguras, primitivas con su SDF, cinemática de links y el resumen `describe`. El
código no sabe qué es una turbina: solo conoce

  primitivas     box, sphere, cylinder (troncocónico), capsule, beam, swept_box
  articulaciones fixed, revolute (grados), prismatic (metros)
  patrones       sweep, orbit, face_grid, point  (los genera lib/patterns.py)

Diferencias con insem:

- `parameters` son FIJOS por tipo. Una instancia solo puede pisar claves de
  `state` (el `attributes` del target: rumbo de la góndola, azimut del rotor...).
  Lo que no es estado declarado se ignora y queda en `Model.ignored_state`.
- La instancia se ubica con `origin` (ENU, metros) y `azim_front` (brújula,
  0 = Norte, horario), que rota el marco base del modelo. El marco del modelo
  está alineado a ENU cuando azim_front = 0 (x = Este, y = Norte, z = Arriba).
"""
from __future__ import annotations

import ast
import fnmatch
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import yaml

FORMAT = "insem/0.2"

# =====================================================================
# Expresiones seguras
# =====================================================================
_FUNCS = {k: getattr(math, k) for k in
          ("sin", "cos", "tan", "asin", "acos", "atan", "atan2", "radians",
           "degrees", "sqrt", "hypot", "floor", "ceil")}
_FUNCS.update(min=min, max=max, abs=abs, pi=math.pi)
_OK_NODES = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant, ast.Name,
             ast.Load, ast.Call, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow,
             ast.Mod, ast.USub, ast.UAdd, ast.FloorDiv)
_SKIP_KEYS = {"type", "id", "class", "description", "name", "pattern", "prim",
              "on_surface", "face", "priority", "material", "table", "notes", "unit"}
_KEYWORDS = {"half_width", "half_depth", "radius"}
_AXIS_RE = re.compile(r"^[+-][xyz]$")


def ev(x, ns):
    """Evalúa números/expresiones de forma recursiva (dict, list, str)."""
    if isinstance(x, bool) or x is None:
        return x
    if isinstance(x, (int, float)):
        return float(x)
    if isinstance(x, str):
        if x in _KEYWORDS or _AXIS_RE.match(x):
            return x
        tree = ast.parse(x, mode="eval")
        for n in ast.walk(tree):
            if not isinstance(n, _OK_NODES):
                raise ValueError(f"Expresión no permitida: {x!r}")
            if isinstance(n, ast.Call) and not (isinstance(n.func, ast.Name) and n.func.id in _FUNCS):
                raise ValueError(f"Función no permitida en {x!r}")
        try:
            return float(eval(compile(tree, "<expr>", "eval"), {"__builtins__": {}}, {**_FUNCS, **ns}))
        except NameError as e:
            raise ValueError(f"En la expresión {x!r}: {e}") from None
    if isinstance(x, list):
        return [ev(v, ns) for v in x]
    if isinstance(x, dict):
        return {k: (v if k in _SKIP_KEYS else ev(v, ns)) for k, v in x.items()}
    return x


# =====================================================================
# Álgebra
# =====================================================================
def rot_axis_angle(axis, ang):
    a = np.asarray(axis, float)
    a = a / np.linalg.norm(a)
    K = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
    return np.eye(3) + math.sin(ang) * K + (1 - math.cos(ang)) * K @ K


def rpy_matrix(r, p, y):
    return rot_axis_angle([0, 0, 1], y) @ rot_axis_angle([0, 1, 0], p) @ rot_axis_angle([1, 0, 0], r)


def H(R=np.eye(3), t=(0, 0, 0)):
    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = t
    return T


def pose_T(p):
    p = p or {}
    rpy = [math.radians(a) for a in p.get("rpy_deg", [0, 0, 0])]
    return H(rpy_matrix(*rpy), p.get("xyz", [0, 0, 0]))


def unit(v):
    v = np.asarray(v, float)
    n = np.linalg.norm(v)
    return v / n if n > 1e-12 else v


def frame_from_axis(a, b, up=None):
    """Marco con z = a->b, x = 'up' proyectado (canto/altura), y = z × x."""
    z = unit(np.asarray(b, float) - np.asarray(a, float))
    if up is None:
        up = [0, 0, 1] if abs(z[2]) < 0.9 else [1, 0, 0]
    x = unit(np.asarray(up, float) - z * np.dot(up, z))
    y = np.cross(z, x)
    return np.c_[x, y, z]


def compass_from_vec(v):
    """Rumbo de brújula (0 = N, 90 = E) de un vector ENU."""
    return (90.0 - math.degrees(math.atan2(v[1], v[0]))) % 360.0


def base_T(origin=(0.0, 0.0, 0.0), azim_front=0.0):
    """Pose de la instancia: traslada a `origin` y gira el marco base por `azim_front` (brújula, horario)."""
    return H(rot_axis_angle([0, 0, 1], math.radians(-float(azim_front))), np.asarray(origin, float))


def axis_vec(s):
    v = np.zeros(3)
    v["xyz".index(s[1])] = 1.0 if s[0] == "+" else -1.0
    return v


def pointing_text(v):
    el = math.degrees(math.asin(max(-1, min(1, v[2]))))
    if el > 60:
        return f"hacia arriba (elev {el:.0f}°)"
    if el < -60:
        return f"hacia abajo (elev {el:.0f}°)"
    return f"rumbo {compass_from_vec(v):.0f}°, elev {el:.0f}°"


# =====================================================================
# SDF de primitivas (en el marco de la primitiva)
# =====================================================================
def sdf_box(p, c, h):
    q = np.abs(p - c) - h
    return np.linalg.norm(np.maximum(q, 0), axis=1) + np.minimum(q.max(axis=1), 0)


def sdf_tapered_cyl(p, rb, rt, L):
    z = p[:, 2]
    rad = np.hypot(p[:, 0], p[:, 1])
    r = rb + (rt - rb) * np.clip(z / L, 0, 1)
    dr = rad - r
    dz = np.where(z < 0, -z, np.where(z > L, z - L, 0.0))
    inside_z = dz == 0
    return np.where(inside_z & (dr < 0), np.maximum(dr, np.maximum(-z, z - L)),
                    np.hypot(np.maximum(dr, 0), dz))


def sdf_capsule_z(p, L, r):
    z = np.clip(p[:, 2], 0, L)
    return np.linalg.norm(p - np.c_[np.zeros_like(z), np.zeros_like(z), z], axis=1) - r


class Table:
    """Función 1D sobre la fracción [0,1] (constante, expresión o tabla por estaciones)."""

    def __init__(self, spec, tables):
        if isinstance(spec, dict) and "table" in spec:
            spec = tables[spec["table"]]
        if isinstance(spec, dict):
            self.x = np.asarray(spec.get("stations", spec.get("x")), float)
            self.y = np.asarray(spec.get("values", spec.get("y")), float)
        else:
            self.x, self.y = np.array([0.0, 1.0]), np.array([float(spec)] * 2)

    def __call__(self, f):
        return float(np.interp(f, self.x, self.y))

    def max(self):
        return float(self.y.max())


# =====================================================================
# Primitivas
# =====================================================================
@dataclass
class Prim:
    kind: str
    id: str
    T: np.ndarray          # prim -> link
    p: dict                # parámetros
    boxes: list = field(default_factory=list)   # swept_box: [(c,h)]

    @property
    def R(self):
        return self.T[:3, :3]

    @property
    def t(self):
        return self.T[:3, 3]

    # eje principal (z del marco de la primitiva)
    @property
    def length(self):
        return self.p.get("L", 0.0)

    def half_width(self, f):
        return self.p["width"](f) / 2 if "width" in self.p else self.p.get("r", 0.0)

    def half_depth(self, f):
        return self.p["depth"](f) / 2 if "depth" in self.p else self.p.get("r", 0.0)

    def radius(self, f):
        if self.kind == "cylinder":
            return self.p["rb"] + (self.p["rt"] - self.p["rb"]) * f
        if self.kind in ("capsule", "sphere"):
            return self.p["r"]
        return max(self.half_width(f), self.half_depth(f))

    def sdf(self, P):
        k = self.kind
        if k == "box" or k == "beam":
            return sdf_box(P, self.p["c"], self.p["h"])
        if k == "sphere":
            return np.linalg.norm(P, axis=1) - self.p["r"]
        if k == "cylinder":
            return sdf_tapered_cyl(P, self.p["rb"], self.p["rt"], self.p["L"])
        if k == "capsule":
            return sdf_capsule_z(P, self.p["L"], self.p["r"])
        if k == "swept_box":
            d = np.full(len(P), np.inf)
            for c, h in self.boxes:
                d = np.minimum(d, sdf_box(P, c, h))
            return d
        raise ValueError(k)

    def collision_boxes(self):
        """(c, h) en marco de la primitiva."""
        if self.kind in ("box", "beam"):
            return [(self.p["c"], self.p["h"])]
        if self.kind == "swept_box":
            return self.boxes
        return []


def build_prim(g, idx, tables):
    kind = g["type"]
    pid = g.get("id", f"p{idx}")
    if kind == "box":
        return Prim(kind, pid, pose_T(g.get("pose")),
                    {"c": np.zeros(3), "h": np.asarray(g["size"], float) / 2})
    if kind == "sphere":
        return Prim(kind, pid, pose_T(g.get("pose")), {"r": g["radius"]})
    if kind == "cylinder":   # base en el origen, a lo largo de +z
        rb = g.get("radius_bottom", g.get("radius"))
        rt = g.get("radius_top", g.get("radius"))
        return Prim(kind, pid, pose_T(g.get("pose")), {"rb": rb, "rt": rt, "L": g["length"]})
    if kind in ("capsule", "beam"):
        a, b = np.asarray(g["a"], float), np.asarray(g["b"], float)
        T = H(frame_from_axis(a, b, g.get("up")), a)
        L = float(np.linalg.norm(b - a))
        if kind == "capsule":
            return Prim(kind, pid, T, {"r": g["radius"], "L": L})
        w, d = g["width"], g.get("depth", g["width"])
        return Prim(kind, pid, T, {"c": np.array([0, 0, L / 2]), "h": np.array([d / 2, w / 2, L / 2]),
                                   "L": L, "width": Table(w, tables), "depth": Table(d, tables)})
    if kind == "swept_box":  # a lo largo de +z; x = canto (depth), y = ancho (width)
        L = g["length"]
        W, D = Table(g["width"], tables), Table(g["depth"], tables)
        n = int(g.get("segments", 20))
        zs = np.linspace(0, L, n + 1)
        boxes = []
        for z0, z1 in zip(zs[:-1], zs[1:]):
            w = max(W(z0 / L), W(z1 / L))
            d = max(D(z0 / L), D(z1 / L))
            boxes.append((np.array([0, 0, (z0 + z1) / 2]), np.array([d / 2, w / 2, (z1 - z0) / 2])))
        return Prim(kind, pid, pose_T(g.get("pose")), {"L": L, "width": W, "depth": D}, boxes)
    raise ValueError(f"Primitiva desconocida: {kind}")


# =====================================================================
# Links y modelo
# =====================================================================
@dataclass
class Link:
    name: str
    cls: str
    parent: str
    raw: dict
    inspectable: bool = True
    T: np.ndarray = field(default_factory=lambda: np.eye(4))   # link -> mundo
    prims: list = field(default_factory=list)
    insp: dict = field(default_factory=dict)

    @property
    def R(self):
        return self.T[:3, :3]

    @property
    def t(self):
        return self.T[:3, 3]

    def to_world(self, p):
        return self.R @ np.asarray(p, float) + self.t

    def prim(self, pid):
        if pid is None:
            return self.prims[0]
        for p in self.prims:
            if p.id == pid:
                return p
        raise ValueError(f"{self.name}: primitiva {pid!r} no existe ({[p.id for p in self.prims]})")

    def sdf(self, P):
        d = np.full(len(P), np.inf)
        if not self.prims:
            return d
        Pl = (P - self.t) @ self.R
        for pr in self.prims:
            d = np.minimum(d, pr.sdf((Pl - pr.t) @ pr.R))
        return d

    def aabb(self):
        pts = []
        for pr in self.prims:
            M = self.T @ pr.T
            if pr.kind in ("box", "beam", "swept_box"):
                for c, h in pr.collision_boxes():
                    cs = np.array([[sx, sy, sz] for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)]) * h + c
                    pts.append(cs @ M[:3, :3].T + M[:3, 3])
            else:
                r = pr.radius(0) if pr.kind != "cylinder" else max(pr.p["rb"], pr.p["rt"])
                ends = [M[:3, 3], M[:3, 3] + M[:3, 2] * pr.length]
                for e in ends:
                    pts.append(np.array([e - r, e + r]))
        if not pts:
            return None
        P = np.vstack(pts)
        return P.min(0), P.max(0)


class Model:
    """Un tipo de elemento instanciado con el estado y la pose de UNA instancia.

    model = Model("data/models/wind_turbine.insem.yaml",
                  state=target["attributes"], origin=[x, y, z], azim_front=target["azimFront"])
    """

    def __init__(self, path, state=None, origin=(0.0, 0.0, 0.0), azim_front=0.0):
        self.path = Path(path)
        doc = yaml.safe_load(self.path.read_text())
        if not str(doc.get("format", "")).startswith("insem/"):
            raise ValueError(f"{path}: no es un fichero {FORMAT}")
        self.doc = doc
        self.asset = doc.get("asset", {})
        self.params = {k: float(v) for k, v in (doc.get("parameters") or {}).items()}
        # estado: escalar o {value, limits, adjustable, unit, description}
        self.state_spec = {}
        for k, v in (doc.get("state") or {}).items():
            self.state_spec[k] = v if isinstance(v, dict) else {"value": v}
        overrides = dict(state or {})
        # Solo el estado declarado es por instancia; los parámetros son del tipo.
        self.ignored_state = {k: v for k, v in overrides.items() if k not in self.state_spec}
        self.state = {k: s.get("value") for k, s in self.state_spec.items()}
        self.state.update({k: v for k, v in overrides.items() if k in self.state_spec})
        self.origin = np.asarray(origin, float)
        self.azim_front = float(azim_front or 0.0)
        ns = {**self.params, **{k: float(v) for k, v in self.state.items()
                                if isinstance(v, (int, float)) and not isinstance(v, bool)}}
        self.derived = {}
        for k, expr in (doc.get("derived") or {}).items():
            ns[k] = self.derived[k] = ev(expr, ns)
        self.ns = ns
        self.tables = {k: ev(v, ns) for k, v in (doc.get("tables") or {}).items()}
        self.links: dict[str, Link] = {}
        for raw in doc["links"]:
            cls = raw.get("class", "generic")
            self.links[raw["name"]] = Link(raw["name"], cls, raw.get("parent", "world"), raw,
                                           inspectable=raw.get("inspectable", cls != "environment"))
        self._kinematics()
        for L in self.links.values():
            geo = L.raw.get("geometry") or []
            geo = [geo] if isinstance(geo, dict) else geo
            L.prims = [build_prim(ev(g, ns), i, self.tables) for i, g in enumerate(geo)]
            L.insp = ev(L.raw.get("inspection") or {}, ns)

    def _kinematics(self):
        done = {"world": base_T(self.origin, self.azim_front)}
        pending = list(self.links.values())
        while pending:
            prog = False
            for L in list(pending):
                if L.parent not in done:
                    continue
                j = ev(L.raw.get("joint") or {}, self.ns)
                T = done[L.parent] @ pose_T(j.get("origin"))
                jt = j.get("type", "fixed")
                if jt == "revolute":
                    T = T @ H(rot_axis_angle(j.get("axis", [0, 0, 1]), math.radians(j.get("value", 0))))
                elif jt == "prismatic":
                    T = T @ H(t=unit(j.get("axis", [1, 0, 0])) * j.get("value", 0))
                elif jt != "fixed":
                    raise ValueError(f"{L.name}: joint {jt} no soportado")
                L.T = T
                done[L.name] = T
                pending.remove(L)
                prog = True
            if not prog:
                raise ValueError(f"Padres no resueltos: {[l.name for l in pending]}")

    # ------------------------------------------------------------------
    def sdf_all(self, P):
        """Distancia firmada de cada punto (N×3, mundo) a la parte más cercana.

        Devuelve (d_min, nombre_parte_más_cercana, matriz_d_por_parte, nombres).
        """
        P = np.atleast_2d(np.asarray(P, float))
        names = [n for n, L in self.links.items() if L.prims]
        D = np.stack([self.links[n].sdf(P) for n in names])
        i = D.argmin(axis=0)
        return D.min(axis=0), [names[k] for k in i], D, names

    def select(self, target):
        """Partes inspeccionables: glob de nombre, lista de globs, o {class: glob, name: glob}."""
        if isinstance(target, dict):
            out = [n for n, L in self.links.items()
                   if fnmatch.fnmatch(L.cls, target.get("class", "*"))
                   and fnmatch.fnmatch(n, target.get("name", "*"))]
        else:
            pats = target if isinstance(target, list) else [target]
            out = [n for p in pats for n in self.links if fnmatch.fnmatch(n, p)]
        return [n for n in dict.fromkeys(out) if self.links[n].inspectable]

    def aabb(self, only_inspectable=True):
        bs = [L.aabb() for L in self.links.values() if L.prims and (L.inspectable or not only_inspectable)]
        bs = [b for b in bs if b]
        return np.min([b[0] for b in bs], 0), np.max([b[1] for b in bs], 0)

    # ------------------------------------------------------------------
    def surface_axis(self, L, s):
        """(p0, p1) en marco link para superficies sweep/orbit."""
        if "axis" in s:
            return np.asarray(s["axis"][0], float), np.asarray(s["axis"][1], float)
        pr = L.prim(s.get("prim"))
        return (pr.T @ [0, 0, 0, 1])[:3], (pr.T @ [0, 0, pr.length, 1])[:3]

    def surface_normal(self, L, s):
        """Dirección de vista (mundo) de una superficie sweep/face_grid."""
        if s["pattern"] == "face_grid":
            pr = L.prim(s.get("prim"))
            return L.R @ pr.R @ axis_vec(s["face"])
        d = s["direction"]
        if isinstance(d, str):
            pr = L.prim(s.get("prim"))
            return L.R @ pr.R @ axis_vec(d)
        return L.R @ unit(d)

    def describe(self, part=None):
        """Resumen semántico para el LLM, relativo a la base del elemento.

        Las coordenadas se expresan respecto de `origin` (nunca posiciones
        absolutas) en ejes ENU: con azim_front aplicado, los rumbos son reales.
        """
        r2 = lambda v: [round(float(x), 2) for x in v]
        rel = lambda p: r2(np.asarray(p, float) - self.origin)
        out = {"asset": {k: v for k, v in self.asset.items() if k not in ("geo", "plot")},
               "frame": "ejes ENU (x=Este, y=Norte, z=Arriba) con origen en la base del elemento; "
                        "metros; rumbos de brújula 0=N 90=E",
               "azim_front": self.azim_front,
               "parameters": {k: round(v, 3) for k, v in self.params.items()},
               "derived": {k: round(v, 3) for k, v in self.derived.items()},
               "state": {k: {**{kk: vv for kk, vv in s.items() if kk != "value"}, "value": self.state[k]}
                         for k, s in self.state_spec.items()},
               "parts": {}}
        if self.ignored_state:
            out["ignored_state"] = self.ignored_state
        for L in self.links.values():
            if part and not fnmatch.fnmatch(L.name, part):
                continue
            sem = L.raw.get("semantic") or {}
            p = {"class": L.cls, "parent": L.parent, "inspectable": L.inspectable}
            for k, v in sem.items():
                p[k] = " ".join(v.split()) if isinstance(v, str) else v
            p["primitives"] = [{"id": pr.id, "type": pr.kind} for pr in L.prims]
            bb = L.aabb()
            if bb:
                p["aabb"] = {"min": rel(bb[0]), "max": rel(bb[1])}
            surfs = []
            for s in L.insp.get("surfaces", []):
                d = {"id": s["id"], "pattern": s["pattern"]}
                if s.get("description"):
                    d["description"] = s["description"]
                if s["pattern"] in ("sweep", "orbit"):
                    a, b = self.surface_axis(L, s)
                    A, B = L.to_world(a), L.to_world(b)
                    d["axis"] = [rel(A), rel(B)]
                    d["length"] = round(float(np.linalg.norm(B - A)), 2)
                    d["axis_pointing"] = pointing_text(unit(B - A))
                if s["pattern"] in ("sweep", "face_grid"):
                    n = self.surface_normal(L, s)
                    d["view_normal"] = r2(n)
                    d["view_pointing"] = pointing_text(unit(n))
                surfs.append(d)
            if surfs:
                p["surfaces"] = surfs
            if L.insp.get("zones"):
                p["zones"] = L.insp["zones"]
            if L.insp.get("recommended"):
                p["recommended"] = L.insp["recommended"]
            feats = []
            for f in L.insp.get("features", []):
                f2 = {k: v for k, v in f.items() if k not in ("views",)}
                if "position" in f:
                    f2["position"] = rel(L.to_world(f["position"]))
                feats.append(f2)
            if feats:
                p["features"] = feats
            out["parts"][L.name] = p
        return out
