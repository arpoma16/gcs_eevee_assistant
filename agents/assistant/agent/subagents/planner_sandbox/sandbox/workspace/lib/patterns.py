"""Los 4 patrones de inspección: generan CANDIDATOS, no waypoints.

Un candidato es "mirar este punto de la superficie desde esta dirección a esta
distancia". Todavía no se comprobó nada: `lib/views.py` lo valida (clearance,
altitud, gimbal, línea de visión), lo repara si hace falta y lo convierte en
waypoint. Todo sale en coordenadas mundo (ENU) porque el modelo ya está
instanciado en la posición y orientación del target.

  sweep      estaciones a lo largo del eje de una primitiva, mirando en `direction`
  orbit      anillos alrededor de un eje (torre, poste, pila)
  face_grid  rejilla en serpentina sobre una cara de un box/beam
  point      una vista por dirección sobre un punto

Dos formas de usarlo desde un script:

    # 1. atajo con la semántica de una tarea de insem
    cands = inspect(model, camera, {"class": "rotor_blade"}, surfaces=["leading_edge"], zones=["tip"], gsd_mm=1.0)
    cands = inspect(model, camera, "blade_*", features=["lightning_receptor"], gsd_mm=1.5)

    # 2. superficie por superficie, cuando necesitás controlar cada una
    cands = surface(model, camera, "tower", "shell", standoff=12, range_m=[10, None])
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from lib.model import Table, axis_vec, rot_axis_angle, unit


@dataclass
class Candidate:
    part: str                   # link del modelo
    surface: str                # id de la superficie (o de la feature, en point)
    zone: str | None
    axis_pt: np.ndarray         # punto del eje / de la cara (mundo)
    normal: np.ndarray          # dirección de vista hacia afuera (mundo)
    r_surf: float               # distancia del eje a la superficie
    rot_axis: np.ndarray | None  # eje para girar la vista si hay que repararla
    d0: float                   # standoff nominal
    info: dict = field(default_factory=dict)   # s_m, s_frac, azimuth_deg, feature...


# ---------------------------------------------------------------------------
# helpers de rango y offset
# ---------------------------------------------------------------------------
def _range(L, length, zones=None, range_frac=None, range_m=None):
    """Intervalo [f0, f1] en fracción del eje, o None si las zonas pedidas no existen."""
    defined = L.insp.get("zones", {})
    if zones:
        zs = [defined[z]["range"] for z in zones if z in defined]
        if not zs:
            return None
        return min(z[0] for z in zs), max(z[1] for z in zs)
    if range_m is not None:
        a, b = range_m
        a = 0 if a is None else a
        b = length if b is None else b
        return max(0, a / length), min(1, b / length)
    r = range_frac if range_frac is not None else [0.0, 1.0]
    return r[0], r[1]


def _stations(f0, f1, length, step):
    if f1 - f0 < 1e-9:
        return [f0]
    n = max(1, math.ceil((f1 - f0) * length / step - 1e-9))
    return [f0 + (f1 - f0) * (i + 0.5) / n for i in range(n)]


def _zone(L, f):
    for k, z in L.insp.get("zones", {}).items():
        if z["range"][0] <= f <= z["range"][1]:
            return k
    return None


def _offset(model, L, s, f):
    off = s.get("offset", "radius")
    if isinstance(off, (int, float)):
        return float(off)
    if isinstance(off, dict):
        return Table(off, model.tables)(f)
    pr = L.prim(s.get("prim"))
    return {"half_width": pr.half_width, "half_depth": pr.half_depth, "radius": pr.radius}[off](f)


def _surface_def(model, part, surface_id):
    L = model.links[part]
    for s in L.insp.get("surfaces", []):
        if s["id"] == surface_id:
            return L, s
    ids = [s["id"] for s in L.insp.get("surfaces", [])]
    raise ValueError(f"{part}: superficie {surface_id!r} no existe ({ids})")


# ---------------------------------------------------------------------------
# patrones
# ---------------------------------------------------------------------------
def sweep(model, camera, L, s, standoff, *, zones=None, range_frac=None, range_m=None, overlap=0.3,
          reverse=False, feature=None):
    W, _ = camera.footprint(standoff)
    a, b = model.surface_axis(L, s)
    length = float(np.linalg.norm(b - a))
    rng = _range(L, length, zones, range_frac, range_m)
    if rng is None:
        return []
    f0, f1 = rng
    nrm = model.surface_normal(L, s)
    ax_w = L.R @ unit(b - a)
    stations = _stations(f0, f1, length, W * (1 - overlap))
    if reverse:
        stations = stations[::-1]
    return [Candidate(L.name, s["id"], _zone(L, f), L.to_world(a + f * (b - a)), nrm,
                      _offset(model, L, s, f), ax_w, standoff,
                      {"s_m": round(f * length, 2), "s_frac": round(f, 3), "feature": feature})
            for f in stations]


def orbit(model, camera, L, s, standoff, *, zones=None, range_frac=None, range_m=None, overlap=0.3,
          azimuth_range_deg=(0, 360), azimuths_deg=None, min_views=None, min_altitude=0.0,
          min_clearance=0.0, feature=None):
    """Anillos alrededor del eje. Con eje vertical, los azimuts son rumbos de brújula."""
    W, Hh = camera.footprint(standoff)
    a, b = model.surface_axis(L, s)
    length = float(np.linalg.norm(b - a))
    rng = _range(L, length, zones, range_frac, range_m)
    if rng is None:
        return []
    f0, f1 = rng
    A, B = L.to_world(a), L.to_world(b)
    ax_w = unit(B - A)
    vertical = abs(ax_w[2]) > 0.95
    # sin rango explícito, no se generan anillos por debajo de la altitud mínima
    if vertical and range_m is None and not zones and f0 != f1:
        fz = (min_altitude - A[2]) / (B[2] - A[2])
        f0 = max(f0, min(1, fz))
    rmean = _offset(model, L, s, (f0 + f1) / 2)
    R = rmean + standoff
    az0, az1 = azimuth_range_deg
    full = (az1 - az0) % 360 == 0 and az1 != az0
    span = 360.0 if full else (az1 - az0) % 360
    dth = min(W * (1 - overlap) / max(rmean, 0.1), 2 * math.acos(rmean / R) * (1 - overlap))
    n = max(min_views or (4 if full else 1), math.ceil(math.radians(span) / dth))
    # en un anillo completo, la cuerda entre vistas no puede acercarse a la superficie
    while full and R * math.cos(math.pi / n) - rmean < min_clearance and n < 72:
        n += 1
    azs = list(azimuths_deg) if azimuths_deg else (
        [az0 + i * 360.0 / n for i in range(n)] if full else [az0 + span * (i + 0.5) / n for i in range(n)])
    if vertical:
        ref = lambda az: np.array([math.cos(math.radians(90 - az)), math.sin(math.radians(90 - az)), 0.0])
    else:
        pr = L.prim(s.get("prim")) if "prim" in s or "axis" not in s else None
        x0 = L.R @ (pr.R[:, 0] if pr else unit(np.cross(unit(b - a), [0, 0, 1])))
        ref = lambda az: rot_axis_angle(ax_w, math.radians(az)) @ x0
    out = []
    for k, f in enumerate(_stations(f0, f1, length, Hh * (1 - overlap))):
        ring = azs[::-1] if k % 2 else azs
        for az in ring:
            out.append(Candidate(L.name, s["id"], _zone(L, f), A + f * (B - A), ref(az),
                                 _offset(model, L, s, f), ax_w, standoff,
                                 {"s_m": round(f * length, 2), "azimuth_deg": round(az % 360, 1),
                                  "feature": feature}))
    return out


def face_grid(model, camera, L, s, standoff, *, zones=None, range_frac=None, range_m=None, overlap=0.3,
              feature=None):
    W, Hh = camera.footprint(standoff)
    pr = L.prim(s.get("prim"))
    if pr.kind not in ("box", "beam"):
        raise ValueError(f"{L.name}/{s['id']}: face_grid requiere box o beam")
    c, h = pr.p["c"], pr.p["h"]
    nl = axis_vec(s["face"])
    ax = int(np.argmax(np.abs(nl)))
    others = sorted((i for i in range(3) if i != ax), key=lambda i: -h[i])   # u = lado más largo
    u, v = others
    rng = _range(L, 2 * h[u], zones, range_frac, range_m)
    f0, f1 = rng if rng else (0, 1)
    nu = max(1, math.ceil((f1 - f0) * 2 * h[u] / (W * (1 - overlap)) - 1e-9))
    nv = max(1, math.ceil(2 * h[v] / (Hh * (1 - overlap)) - 1e-9))
    M = L.T @ pr.T
    Rw = M[:3, :3]
    out = []
    for iv in range(nv):
        seq = range(nu) if iv % 2 == 0 else range(nu - 1, -1, -1)
        for iu in seq:
            p = c.copy()
            p[ax] += nl[ax] * h[ax]
            fu = f0 + (f1 - f0) * (iu + 0.5) / nu
            p[u] += -h[u] + 2 * h[u] * fu
            p[v] += -h[v] + 2 * h[v] * (iv + 0.5) / nv
            ev_u = np.zeros(3)
            ev_u[u] = 1
            out.append(Candidate(L.name, s["id"], _zone(L, fu), Rw @ p + M[:3, 3], Rw @ nl, 0.0,
                                 Rw @ ev_u, standoff, {"u_frac": round(fu, 3), "v_frac": round((iv + 0.5) / nv, 3),
                                                       "feature": feature}))
    return out


def point(model, camera, L, s, standoff, *, feature=None, **_):
    """Una vista por dirección de `views` (marco del link) sobre `position`."""
    pos = L.to_world(s["position"])
    out = []
    for i, v in enumerate(s.get("views", [[0, 0, 1]])):
        n = L.R @ unit(v)
        ra = unit(np.cross(n, [0, 0, 1])) if abs(n[2]) < 0.95 else unit(np.cross(n, [1, 0, 0]))
        out.append(Candidate(L.name, feature or s["id"], None, pos, n, float(s.get("offset", 0.0)), ra,
                             standoff, {"view": i, "feature": feature}))
    return out


PATTERNS = {"sweep": sweep, "orbit": orbit, "face_grid": face_grid, "point": point}


# ---------------------------------------------------------------------------
# entradas de alto nivel
# ---------------------------------------------------------------------------
def surface(model, camera, part, surface_id, standoff, **kw):
    """Candidatos de UNA superficie de UNA parte, con el patrón que declara el modelo."""
    L, s = _surface_def(model, part, surface_id)
    return PATTERNS[s["pattern"]](model, camera, L, s, standoff, **kw)


def feature_candidates(model, camera, part, wanted, standoff, *, surfaces=None, **kw):
    """Candidatos de las features de una parte, por id o por clase (`wanted`)."""
    L = model.links[part]
    defined = {s["id"]: s for s in L.insp.get("surfaces", [])}
    out = []
    for f in L.insp.get("features", []):
        if f["id"] not in wanted and f.get("class") not in wanted:
            continue
        if "position" in f:
            out += point(model, camera, L, {"id": f["id"], "position": f["position"],
                                            "views": f.get("views", [[0, 0, 1]]),
                                            "offset": f.get("offset", 0.0)}, standoff, feature=f["id"])
        for sid in f.get("on_surface", []):
            if surfaces and sid not in surfaces:
                continue
            s = defined[sid]
            at = f.get("at", f.get("at_m"))
            at = at if isinstance(at, list) else [at, at]
            extra = {"range_frac": at} if "at" in f else {"range_m": at}
            if "azimuth_deg" in f and s["pattern"] == "orbit":
                extra["azimuths_deg"] = [f["azimuth_deg"]]
            fn = PATTERNS[s["pattern"]]
            out += fn(model, camera, L, s, standoff, **_accepted(fn, {**kw, **extra}), feature=f["id"])
    return out


def inspect(model, camera, target, *, surfaces=None, zones=None, features=None, gsd_mm=None,
            standoff_m=None, safety=None, **kw):
    """Equivalente a una tarea de insem: `target` es glob de parte, lista de globs o {class, name}.

    Sin `surfaces` recorre todas las de cada parte; con `features` (ids o clases) solo esas features.
    El standoff sale de `standoff_m`, o del GSD (`gsd_mm`, o el `recommended` de la parte),
    y nunca baja de `safety.min_clearance_m`.
    """
    names = model.select(target)
    if not names:
        parts = ", ".join(f"{n} (class {L.cls})" for n, L in model.links.items() if L.inspectable)
        raise ValueError(f"target {target!r} no coincide con ninguna parte inspeccionable de "
                         f"{model.asset.get('name', model.path.name)}. Partes: {parts}. "
                         f"Revisalo con tools/describe.py")
    out, reverse = [], False
    for n in names:
        L = model.links[n]
        d = standoff_m if standoff_m is not None else camera.standoff_for_gsd(
            gsd_mm or L.insp.get("recommended", {}).get("gsd_mm", 2.0))
        if safety is not None:
            d = max(d, safety.min_clearance_m)
            kw.setdefault("min_altitude", safety.min_altitude_m)
            kw.setdefault("min_clearance", safety.min_clearance_m)
        if features:
            out += feature_candidates(model, camera, n, features, d, surfaces=surfaces, **kw)
            continue
        for s in L.insp.get("surfaces", []):
            if surfaces and s["id"] not in surfaces:
                continue
            fn = PATTERNS[s["pattern"]]
            args = dict(kw, zones=zones)
            if fn is sweep:
                args["reverse"] = reverse
                reverse = not reverse   # serpentina entre superficies consecutivas
            out += fn(model, camera, L, s, d, **_accepted(fn, args))
    return out


_ACCEPTS = {
    sweep: {"zones", "range_frac", "range_m", "overlap", "reverse"},
    orbit: {"zones", "range_frac", "range_m", "overlap", "azimuth_range_deg", "azimuths_deg", "min_views",
            "min_altitude", "min_clearance"},
    face_grid: {"zones", "range_frac", "range_m", "overlap"},
    point: set(),
}


def _accepted(fn, kw):
    return {k: v for k, v in kw.items() if k in _ACCEPTS[fn]}
