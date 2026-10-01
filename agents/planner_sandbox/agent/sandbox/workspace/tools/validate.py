"""Valida data/mission.json. Es el MISMO código que corre el gate (validate_and_persist).

Qué comprueba:

  estructura   formato v3, global_origin, primer wp takeoff / último landing, tipos
               de waypoint, yaw en [-180, 180], drones existentes, task_id únicos,
               depends_on existentes y sin ciclos, un mismo dron sin dos rutas a la vez
  cobertura    cada target del briefing tiene al menos una vista; ninguna vista de
               un elemento que no sea target
  altitud      mínimo en todo el recorrido; techo de lib/regulation.py (120 m o la
               excepción de elementos de más de 105 m) en todo el recorrido
  geovalla     cada waypoint dentro de los límites de origin.json
  colisión     cada tramo muestreado cada 0.5 m, en dos niveles:
                 - contra el MODELO COMPLETO de los targets de su tramo lógico (los
                   waypoints no-transit que lo encierran, ver lib/transit.py),
                   con --min-clearance (acercarse es el trabajo)
                 - contra la GEOMETRÍA SIMPLE de todos los demás elementos, con
                   --transit-clearance (pasar a distancia prudente)

No comprueba (pendiente): separación entre drones que vuelan a la vez.

Los límites son del validador, no del script de inspección: el gate lo corre con
los valores por defecto. Sale con código 0 si la misión es válida, 1 si no, y
escribe el informe en data/validation.json.

    python3 tools/validate.py
    python3 tools/validate.py --json
"""
import argparse
import json
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKSPACE))

import numpy as np  # noqa: E402

from lib import mission as fmt  # noqa: E402
from lib.regulation import altitude_ceiling  # noqa: E402
from lib.transit import leg_context  # noqa: E402
from lib.views import Safety  # noqa: E402
from lib.world import World  # noqa: E402

SAMPLE_STEP_M = 0.5

HINTS = {
    "format": "mission.json se genera con tools/build_mission.py; corregí la entrada (views/assignment), "
              "nunca el archivo.",
    "coverage": "falta inspeccionar un target: revisá PLAN en scripts/inspection.py y las vistas rechazadas.",
    "depends_on": "revisá task_id/depends_on en assignment.json.",
    "uav": "un dron no puede volar dos rutas a la vez: encadenalas con depends_on o juntalas en una.",
    "altitude_min": "el recorrido baja del mínimo: revisá el rango (range_m) de las vistas o la altura de "
                    "despegue/aterrizaje.",
    "altitude_max": "el recorrido pasa el techo: es una vista (cambiá qué se inspecciona) o un tramo entre dos "
                    "puntos altos (reordená para no cruzar lejos de la estructura a esa altura).",
    "geofence": "un waypoint cae fuera del área: esa cara no se puede mirar desde ahí.",
    "clearance_target": "un tramo atraviesa la estructura y build_mission no encontró desvío: en el script, "
                        "no encadenes caras opuestas en el mismo bloque, o partilo en bloques y reordená.",
    "clearance_other": "un tramo pasa demasiado cerca de otro elemento y build_mission no encontró desvío: "
                       "cambiá el orden o el reparto de bloques (assignment.json + tools/assign.py --keep).",
}


class Report:
    def __init__(self):
        self.findings = []
        self._worst = {}

    def add(self, code, msg, route=None, where=None, **extra):
        self.findings.append({"code": code, "route": route, "where": where, "msg": msg, **extra})

    def add_worst(self, key, value, code, msg, **extra):
        """Una sola entrada por clave (tramo+obstáculo), la de menor `value`."""
        if key not in self._worst or value < self._worst[key][0]:
            self._worst[key] = (value, {"code": code, "msg": msg, **extra})

    def all(self):
        return self.findings + [f for _, f in self._worst.values()]


# ---------------------------------------------------------------------------
# estructura y cobertura
# ---------------------------------------------------------------------------
def check_structure(m, world, rep):
    if str(m.get("version")) != fmt.VERSION:
        rep.add("format", f"version {m.get('version')!r}, se espera {fmt.VERSION!r}")
    if not m.get("global_origin"):
        rep.add("format", "falta global_origin (hace falta para convertir a geodésico)")
    routes = m.get("route") or []
    if not routes:
        rep.add("format", "la misión no tiene rutas")
        return
    device_names = {d["name"] for d in world.devices}
    target_names = {t.name for t in world.targets}
    task_ids = [r.get("task_id") for r in routes]
    for t in sorted({t for t in task_ids if task_ids.count(t) > 1}, key=str):
        rep.add("depends_on", f"task_id {t} repetido")
    deps = {r.get("task_id"): [d for d in r.get("depends_on") or [] if d in task_ids] for r in routes}
    for r in routes:
        tid = r.get("task_id")
        for d in r.get("depends_on") or []:
            if d not in task_ids:
                rep.add("depends_on", f"depende de {d}, que no existe", route=tid)
        if r.get("uav") not in device_names:
            rep.add("uav", f"dron {r.get('uav')!r} no está en la misión", route=tid)
        wps = r.get("wp") or []
        if len(wps) < 2:
            rep.add("format", "ruta con menos de 2 waypoints", route=tid)
            continue
        if wps[0].get("type") != "takeoff":
            rep.add("format", "el primer waypoint no es takeoff", route=tid, where="wp 0")
        if wps[-1].get("type") != "landing":
            rep.add("format", "el último waypoint no es landing", route=tid, where=f"wp {len(wps) - 1}")
        for i, w in enumerate(wps):
            pos = w.get("pos")
            if not (isinstance(pos, list) and len(pos) == 3 and all(isinstance(v, (int, float)) for v in pos)):
                rep.add("format", f"pos inválida {pos!r}", route=tid, where=f"wp {i}")
            if w.get("type") not in fmt.WAYPOINT_TYPES:
                rep.add("format", f"type {w.get('type')!r} no válido", route=tid, where=f"wp {i}")
            yaw = w.get("yaw")
            if yaw is not None and not -180 <= yaw <= 180:
                rep.add("format", f"yaw {yaw} fuera de [-180, 180]", route=tid, where=f"wp {i}")
            if w.get("type") == "inspection":
                if w.get("target") not in target_names:
                    rep.add("coverage", f"inspecciona {w.get('target')!r}, que no es target de la misión",
                            route=tid, where=f"wp {i}")
                if not w.get("tag"):
                    rep.add("format", "waypoint de inspección sin tag", route=tid, where=f"wp {i}")
    try:
        fmt.finish_times({t: 0.0 for t in task_ids}, deps)
    except ValueError as e:
        rep.add("depends_on", str(e))
    by_uav = {}
    for r in routes:
        by_uav.setdefault(r.get("uav"), []).append(r.get("task_id"))
    for uav, tids in by_uav.items():
        for i, a in enumerate(tids):
            for b in tids[i + 1:]:
                if not fmt.sequenced(a, b, deps):
                    rep.add("uav", f"{uav} tiene {a} y {b} sin depends_on entre ellas")
    covered = {w.get("target") for r in routes for w in r.get("wp") or [] if w.get("type") == "inspection"}
    for t in world.targets:
        if t.name not in covered:
            rep.add("coverage", f"el target {t.name} no tiene ninguna vista")


# ---------------------------------------------------------------------------
# geometría
# ---------------------------------------------------------------------------
def samples(a, b):
    n = max(2, int(np.linalg.norm(b - a) / SAMPLE_STEP_M) + 1)
    return a + np.linspace(0, 1, n)[:, None] * (b - a)


def check_route(r, world, safety, simple, rep):
    tid, wps = r.get("task_id"), r.get("wp") or []
    gf = world.geofence()
    for i, w in enumerate(wps):
        p = np.asarray(w["pos"], float)
        if gf is not None and not ((gf[0] <= p[:2]).all() and (p[:2] <= gf[1]).all()):
            rep.add("geofence", f"({p[0]:.0f}, {p[1]:.0f}) fuera de la geovalla", route=tid, where=f"wp {i}",
                    tag=w.get("tag"))

    for i in range(len(wps) - 1):
        a, b = wps[i], wps[i + 1]
        A, B = np.asarray(a["pos"], float), np.asarray(b["pos"], float)
        P = samples(A, B)
        where = f"tramo {i}→{i + 1}"
        ctx = {"route": tid, "where": where, "from": a.get("tag") or a["type"], "to": b.get("tag") or b["type"]}
        inspected = sorted(leg_context(wps, i))

        # altitud mínima (los extremos takeoff/landing son la altura que eligió build_mission)
        k = int(P[:, 2].argmin())
        if P[k, 2] < safety.min_altitude_m - 1e-6:
            rep.add_worst((tid, i, "alt_min"), P[k, 2], "altitude_min",
                          f"baja a {P[k, 2]:.1f} m (mín {safety.min_altitude_m} m)", at=_r(P[k]), **ctx)

        # techo: solo se evalúa donde se supera el general
        high = P[P[:, 2] > safety.max_altitude_m]
        for q in high:
            ceiling, raised_by = altitude_ceiling(q, safety, others=simple_all(world, simple),
                                                  targets=world.targets)
            if q[2] > ceiling + 1e-6:
                why = f" (elevado por {raised_by})" if raised_by else ""
                rep.add_worst((tid, i, "alt_max"), -q[2], "altitude_max",
                              f"sube a {q[2]:.1f} m, techo {ceiling:.1f} m{why}", at=_r(q), **ctx)

        # modelo completo de los targets que se inspeccionan en este tramo
        for name in inspected:
            model = world.target(name).model
            d, who, _, _ = model.sdf_all(P)
            k = int(d.argmin())
            if d[k] < safety.min_clearance_m - 1e-6:
                rep.add_worst((tid, i, name), d[k], "clearance_target",
                              f"a {d[k]:.2f} m de {name}/{who[k]} (mín {safety.min_clearance_m} m)",
                              at=_r(P[k]), obstacle=f"{name}/{who[k]}", **ctx)

        # geometría simple de todo lo demás
        for obj in simple:
            if obj.name in inspected:
                continue
            d = obj.sdf(P)
            k = int(d.argmin())
            if d[k] < safety.transit_clearance_m - 1e-6:
                what = "ATRAVIESA" if d[k] < 0 else "pasa a"
                rep.add_worst((tid, i, obj.name), d[k], "clearance_other",
                              f"{what} {max(d[k], 0):.1f} m de {obj.name} (mín {safety.transit_clearance_m} m)",
                              at=_r(P[k]), obstacle=obj.name, **ctx)


def simple_all(world, simple):
    """Para la regla de techo: los obstáculos con geometría simple (los targets van con su modelo)."""
    names = {t.name for t in world.targets}
    return [o for o in simple if o.name not in names]


def _r(v):
    return [round(float(x), 2) for x in v]


# ---------------------------------------------------------------------------
def validate(m, world, safety):
    rep = Report()
    check_structure(m, world, rep)
    if not any(f["code"] == "format" for f in rep.findings):
        simple = world.simple_objects()
        for r in m.get("route") or []:
            check_route(r, world, safety, simple, rep)
    findings = rep.all()
    return {
        "valid": not findings,
        "total_findings": len(findings),
        "findings": findings,
        "hints": {c: HINTS[c] for c in sorted({f["code"] for f in findings})},
        "limits": {"min_clearance_m": safety.min_clearance_m, "transit_clearance_m": safety.transit_clearance_m,
                   "min_altitude_m": safety.min_altitude_m, "max_altitude_m": safety.max_altitude_m,
                   "tall_obstacle_exception": safety.tall_obstacle_exception},
        "not_checked": ["separación entre drones que vuelan a la vez"],
    }


def print_report(result, m):
    for r in m.get("route") or []:
        own = [f for f in result["findings"] if f.get("route") == r.get("task_id")]
        status = "OK" if not own else f"{len(own)} hallazgos"
        print(f"{r.get('task_id')} {r.get('uav')}: {len(r.get('wp') or [])} wp · {status}")
        for f in own:
            loc = f" {f['from']} → {f['to']}" if "from" in f else ""
            at = f" en {f['at']}" if "at" in f else ""
            print(f"  [{f['code']}] {f['where'] or ''}{loc}: {f['msg']}{at}")
    for f in result["findings"]:
        if f.get("route") is None:
            print(f"  [{f['code']}] {f['msg']}")
    for code, hint in result["hints"].items():
        print(f"  → {code}: {hint}")
    print(f"NO COMPROBADO: {'; '.join(result['not_checked'])}")
    print("MISIÓN VÁLIDA" if result["valid"] else f"MISIÓN INVÁLIDA ({result['total_findings']} hallazgos)")


def main():
    defaults = Safety()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--min-clearance", type=float, default=defaults.min_clearance_m,
                        help="al modelo completo del target inspeccionado")
    parser.add_argument("--transit-clearance", type=float, default=defaults.transit_clearance_m,
                        help="a la geometría simple del resto")
    parser.add_argument("--min-altitude", type=float, default=defaults.min_altitude_m)
    parser.add_argument("--max-altitude", type=float, default=defaults.max_altitude_m)
    parser.add_argument("--no-tall-obstacle-exception", action="store_true",
                        help="sin la excepción UE 2019/947 de +15 m junto a elementos de más de 105 m")
    parser.add_argument("--json", action="store_true", help="imprimir el informe en JSON")
    parser.add_argument("--data", type=Path, default=WORKSPACE / "data")
    parser.add_argument("--mission", type=Path, help="por defecto <data>/mission.json")
    args = parser.parse_args()

    safety = Safety(min_clearance_m=args.min_clearance, transit_clearance_m=args.transit_clearance,
                    min_altitude_m=args.min_altitude, max_altitude_m=args.max_altitude,
                    tall_obstacle_exception=not args.no_tall_obstacle_exception)
    world = World.load(args.data)
    m = fmt.load(args.mission or args.data / "mission.json")
    result = validate(m, world, safety)
    (args.data / "validation.json").write_text(json.dumps(result, indent=1, ensure_ascii=False))
    if args.json:
        print(json.dumps(result, indent=1, ensure_ascii=False))
    else:
        print_report(result, m)
    sys.exit(0 if result["valid"] else 1)


if __name__ == "__main__":
    main()
