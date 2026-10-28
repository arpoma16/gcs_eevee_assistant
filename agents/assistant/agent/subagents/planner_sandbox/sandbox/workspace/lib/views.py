"""De candidato a waypoint de inspección: validar, reparar y escribir views.json.

    from lib.world import World
    from lib.patterns import inspect
    from lib.views import Camera, Safety, solve_all, write_views

    world, camera, safety = World.load(), Camera(), Safety(min_clearance_m=6)
    views = []
    for t in world.targets_of_type("Wind Turbine"):
        cands = inspect(t.model, camera, {"class": "rotor_blade"}, surfaces=["leading_edge"], safety=safety)
        ok, rejected = solve_all(cands, t, world, camera, safety)
        views += ok
    write_views(views)

Cada candidato se comprueba contra:
  - el modelo COMPLETO del target inspeccionado (clearance >= min_clearance_m,
    línea de visión libre hasta el punto mirado),
  - la geometría SIMPLE de todos los demás elementos (clearance >= transit_clearance_m),
  - altitud (techo de lib/regulation.py, con la excepción de obstáculos altos),
    geovalla (origin.json) y rango del gimbal.
Si la vista nominal falla, se prueba alejarse (hasta max_standoff_m) y girar la
vista (hasta max_incidence_deg) antes de rechazarla.

Un rechazo NO es un número a retocar: trae el motivo de la vista nominal, el del
mejor intento de reparación y los motivos que aparecieron en TODOS los intentos
(`blocking`), con una pista de qué cambio sí puede resolverlo. Si el bloqueo es
la altura o la geovalla, alejarse o girar no sirve: se cambia el pedido (zona,
superficie, estado ajustable) o se informa como no inspeccionable.
"""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass

import numpy as np

from lib.model import compass_from_vec, rot_axis_angle
from lib.regulation import altitude_ceiling
from lib.world import DATA_DIR


@dataclass
class Camera:
    hfov_deg: float = 72.0
    image_width_px: int = 5280
    image_height_px: int = 3956
    vfov_deg: float | None = None

    @property
    def hfov(self):
        return math.radians(self.hfov_deg)

    @property
    def vfov(self):
        if self.vfov_deg is not None:
            return math.radians(self.vfov_deg)
        return 2 * math.atan(math.tan(self.hfov / 2) * self.image_height_px / self.image_width_px)

    def standoff_for_gsd(self, gsd_mm):
        """Distancia a la superficie para lograr `gsd_mm` milímetros por píxel."""
        return gsd_mm / 1000.0 * self.image_width_px / (2 * math.tan(self.hfov / 2))

    def gsd_mm(self, d):
        return d * 2 * math.tan(self.hfov / 2) / self.image_width_px * 1000

    def footprint(self, d):
        """(ancho, alto) en metros de lo que cubre una foto a distancia `d`."""
        return 2 * d * math.tan(self.hfov / 2), 2 * d * math.tan(self.vfov / 2)


@dataclass
class Safety:
    min_clearance_m: float = 5.0          # al target inspeccionado (modelo completo)
    transit_clearance_m: float = 10.0     # a los demás elementos (geometría simple)
    min_altitude_m: float = 5.0
    max_altitude_m: float = 120.0         # techo general (UE 2019/947)
    max_standoff_m: float = 25.0
    max_incidence_deg: float = 45.0
    gimbal_pitch_range_deg: tuple = (-90.0, 30.0)
    # UAS.OPEN.010(2): hasta 15 m sobre un obstáculo de más de 105 m, a menos de 50 m
    # de él, a petición de su responsable. Ver lib/regulation.py.
    tall_obstacle_exception: bool = True


def yaw_from_compass(heading):
    """Rumbo de brújula [0, 360) → yaw de misión [-180, 180] (0 = N, 90 = E, -90 = O)."""
    return round(((heading + 180.0) % 360.0) - 180.0, 1)


# ---------------------------------------------------------------------------
# motivos de rechazo
# ---------------------------------------------------------------------------
# Cada motivo es {"code", "msg"}. El código agrupa; el mensaje trae los números.
HINTS = {
    "altitude_max": "la superficie queda por encima del techo en todas las variantes: alejarse o girar no "
                    "lo arregla. Cambiá un estado ajustable (describe → state.adjustable), otra zona/superficie, "
                    "o informala como no inspeccionable.",
    "altitude_min": "demasiado bajo: acotá el rango (range_m desde más arriba) o usá otra superficie.",
    "geofence": "el punto cae fuera del área de operación: mirá esa cara desde otro lado (otra superficie o "
                "azimuts) o informala como no inspeccionable.",
    "clearance_target": "no hay distancia libre al propio target en ninguna variante: subí max_standoff_m o "
                        "max_incidence_deg si el pedido lo admite, o revisá la superficie elegida.",
    "clearance_other": "un elemento vecino está demasiado cerca de esa cara: otra superficie/azimut, o bajá "
                       "transit_clearance_m solo si el operador lo acepta.",
    "gimbal": "el gimbal no llega al ángulo necesario (la vista mira demasiado arriba o abajo): usá otra "
              "superficie o cara.",
    "line_of_sight": "otra parte tapa la vista: otra superficie, u otro estado ajustable (p.ej. girar el rotor).",
}


def _reason(code, msg):
    return {"code": code, "msg": msg}


def _msgs(reasons):
    return [r["msg"] for r in reasons]


# ---------------------------------------------------------------------------
# validación de un punto
# ---------------------------------------------------------------------------
def check_point(pos, target, world, safety, look_at=None, part=None, others=None):
    """(ok, motivos, clearance_al_target, parte_más_cercana, gimbal_pitch). Motivos: [{code, msg}]."""
    others = others if others is not None else world.simple_objects(exclude=[target.name])
    reasons = []
    if pos[2] < safety.min_altitude_m:
        reasons.append(_reason("altitude_min", f"altitud {pos[2]:.1f} m < mínimo {safety.min_altitude_m} m"))
    ceiling, raised_by = altitude_ceiling(pos, safety, target, others)
    if pos[2] > ceiling:
        why = f" (elevado por {raised_by})" if raised_by else ""
        reasons.append(_reason("altitude_max", f"altitud {pos[2]:.1f} m > techo {ceiling:.1f} m{why}"))
    gf = world.geofence()
    if gf is not None and not ((gf[0] <= pos[:2]).all() and (pos[:2] <= gf[1]).all()):
        reasons.append(_reason("geofence", f"({pos[0]:.0f}, {pos[1]:.0f}) fuera de la geovalla"))
    dmin, who, _, _ = target.model.sdf_all(pos[None])
    clearance = float(dmin[0])
    if clearance < safety.min_clearance_m:
        reasons.append(_reason("clearance_target", f"a {clearance:.2f} m de {target.name}/{who[0]} "
                                                   f"(mín {safety.min_clearance_m} m)"))
    for obj in others:
        d = float(obj.sdf(pos[None])[0])
        if d < safety.transit_clearance_m:
            reasons.append(_reason("clearance_other", f"a {d:.1f} m de {obj.name} (mín {safety.transit_clearance_m} m)"))
    gp = None
    if look_at is not None:
        v = look_at - pos
        gp = math.degrees(math.atan2(v[2], math.hypot(v[0], v[1])))
        lo, hi = safety.gimbal_pitch_range_deg
        if not lo <= gp <= hi:
            reasons.append(_reason("gimbal", f"gimbal {gp:.0f}° fuera de [{lo}, {hi}]"))
        if not reasons:
            blk = los_blocker(target.model, pos, look_at, part)
            if blk:
                reasons.append(_reason("line_of_sight", f"línea de visión tapada por {target.name}/{blk}"))
    return not reasons, reasons, clearance, who[0], gp


def los_blocker(model, pos, look_at, part):
    v = look_at - pos
    n = max(4, int(np.linalg.norm(v) / 0.25))
    ts = np.linspace(0, 1, n)[:-1]
    _, _, D, names = model.sdf_all(pos + ts[:, None] * v)
    for i, nm in enumerate(names):
        if nm == part:
            if (D[i][: int(0.85 * len(ts))] < 0).any():
                return nm
        elif (D[i] < 0.2).any():
            return nm
    return None


# ---------------------------------------------------------------------------
# resolver candidatos
# ---------------------------------------------------------------------------
def solve(c, target, world, camera, safety, others=None):
    """Vista válida para el candidato `c`, o el diagnóstico de por qué no la hay.

    Prueba primero la nominal; si falla, variantes ordenadas por cuánto se apartan
    de ella: alejarse de a 1.5 m y girar de a 15° alrededor de `c.rot_axis`.

    Fallo → {"ok": False, "nominal": [...], "best": {standoff_m, incidence_deg, reasons},
             "blocking": [códigos presentes en TODOS los intentos], "tried": n}
    """
    others = others if others is not None else world.simple_objects(exclude=[target.name])
    deltas = [0.0]
    if c.rot_axis is not None:
        for k in range(1, int(safety.max_incidence_deg // 15) + 1):
            deltas += [15.0 * k, -15.0 * k]
    ds = list(np.arange(c.d0, safety.max_standoff_m + 1e-6, 1.5)) or [c.d0]
    variants = sorted(((dl, d) for dl in deltas for d in ds),
                      key=lambda x: abs(x[0]) / 15 + (x[1] - c.d0) / 1.5)
    nominal, best, blocking = None, None, None
    for dl, d in variants:
        n = c.normal if dl == 0 else rot_axis_angle(c.rot_axis, math.radians(dl)) @ c.normal
        look_at = c.axis_pt + n * c.r_surf
        pos = look_at + n * d
        ok, reasons, clr, who, gp = check_point(pos, target, world, safety, look_at, c.part, others)
        if nominal is None:
            nominal = reasons
        if ok:
            repaired = bool(dl != 0 or abs(d - c.d0) > 1e-6)
            return {"ok": True, "position": pos, "look_at": look_at, "standoff_m": float(d),
                    "incidence_deg": dl, "clearance_m": clr, "closest": who, "gimbal_pitch_deg": gp,
                    "heading_deg": compass_from_vec(look_at - pos), "gsd_mm": camera.gsd_mm(d),
                    "repaired": repaired, "nominal_issue": _msgs(nominal) if repaired else None}
        codes = {r["code"] for r in reasons}
        blocking = codes if blocking is None else blocking & codes
        if best is None or len(codes) < len({r["code"] for r in best["reasons"]}):
            best = {"standoff_m": round(float(d), 2), "incidence_deg": dl, "reasons": reasons}
    return {"ok": False, "nominal": nominal, "best": best, "blocking": sorted(blocking or ()),
            "tried": len(variants)}


def tag_of(c):
    """Etiqueta legible de un candidato: parte/superficie[/zona][/feature]."""
    parts = [c.part, c.surface]
    if c.zone:
        parts.append(c.zone)
    feature = c.info.get("feature")
    if feature and feature != c.surface:
        parts.append(feature)
    return "/".join(parts)


def solve_all(candidates, target, world, camera, safety, block=None):
    """Resuelve una lista de candidatos del mismo target.

    Devuelve (views, rejected). `views` son entradas de views.json listas para
    escribir; `block` (por defecto el nombre del target) es la unidad que después
    se asigna a un dron: dale otro nombre para repartir un target entre varios.
    Cada rechazo trae `nominal`, `best_attempt`, `blocking` y `hints` (ver HINTS).
    """
    others = world.simple_objects(exclude=[target.name])
    views, rejected = [], []
    for c in candidates:
        r = solve(c, target, world, camera, safety, others)
        tag = tag_of(c)
        if not r["ok"]:
            rejected.append({
                "target": target.name,
                "block": block or target.name,
                "tag": tag,
                "nominal_pos": _r(c.axis_pt + c.normal * (c.r_surf + c.d0)),
                "nominal": _msgs(r["nominal"]),
                "best_attempt": {**r["best"], "reasons": _msgs(r["best"]["reasons"])},
                "blocking": r["blocking"],
                "tried": r["tried"],
                "hints": {code: HINTS[code] for code in r["blocking"]},
            })
            continue
        views.append({
            "target": target.name,
            "block": block or target.name,
            "tag": tag,
            "pos": _r(r["position"]),
            "yaw": yaw_from_compass(r["heading_deg"]),
            "gimbal": round(r["gimbal_pitch_deg"], 1),
            "part": c.part,
            "surface": c.surface,
            "zone": c.zone,
            "feature": c.info.get("feature"),
            "standoff_m": round(r["standoff_m"], 2),
            "gsd_mm": round(r["gsd_mm"], 2),
            "clearance_m": round(r["clearance_m"], 2),
            "repaired": r["repaired"],
        })
    return views, rejected


def _r(v):
    return [round(float(x), 3) for x in v]


def write_views(views, path=None, rejected=None, camera=None, safety=None):
    """Escribe data/views.json. Imprime un resumen por target/bloque y los rechazos."""
    path = path or DATA_DIR / "views.json"
    payload = {"views": views}
    if rejected:
        payload["rejected"] = rejected
    if camera:
        payload["camera"] = asdict(camera)
    if safety:
        payload["safety"] = asdict(safety)
    path.write_text(json.dumps(payload, indent=1, ensure_ascii=False))
    counts = {}
    for v in views:
        key = (v["target"], v["block"])
        counts[key] = counts.get(key, 0) + 1
    for (t, b), n in counts.items():
        print(f"{t} [{b}]: {n} vistas" + (f" ({sum(v['repaired'] for v in views if v['block'] == b)} reparadas)"))
    by_block = {}
    for r in rejected or []:
        key = (r["target"], tuple(r["blocking"]) or ("ninguno común",))
        by_block.setdefault(key, []).append(r)
    for (t, blocking), items in by_block.items():
        print(f"RECHAZADAS {t}: {len(items)} — bloqueo en todos los intentos: {', '.join(blocking)}")
        for r in items:
            b = r["best_attempt"]
            print(f"  {r['tag']}: nominal [{'; '.join(r['nominal'])}] | mejor intento "
                  f"(standoff {b['standoff_m']} m, giro {b['incidence_deg']}°) [{'; '.join(b['reasons'])}]")
        for code in blocking:
            if code in HINTS:
                print(f"  → {code}: {HINTS[code]}")
    print(f"-> {path}  ({len(views)} vistas, {len(rejected or [])} rechazadas)")
