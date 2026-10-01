"""Desvíos para los tramos que chocan: A* sobre una rejilla 3D local.

Port de find_via de /home/grvc/work/px4/wtsem/insem/insem.py, con la regla de
colisión en dos niveles del planner. Un TRAMO LÓGICO va de un waypoint que no es
`transit` al siguiente que tampoco lo es; su contexto son los targets de esos
dos extremos (`inspected`):

  - contra el modelo completo de los targets de `inspected`: min_clearance_m
  - contra la geometría simple de todo lo demás:             transit_clearance_m
  - nunca por debajo de min_altitude_m

Los puntos de paso que se insertan heredan ese contexto: tools/validate.py
aplica exactamente la misma regla, así que un tramo que sale de acá libre, se
valida libre.
"""
from __future__ import annotations

import heapq
import math

import numpy as np

SAMPLE_STEP_M = 0.5
MARGIN_M = 0.1          # holgura sobre el mínimo, para no quedar justo en el límite del validador
PAD_XY_M = 50.0         # cuánto se puede apartar un desvío del rectángulo que forman los extremos
PAD_Z_M = 30.0
MAX_CELLS = 3_000_000


class Field:
    """Margen de seguridad (m) de cada punto: >= 0 es libre.

    Guarda las rejillas que construye find_via: todos los tramos de un mismo
    contexto (p.ej. las vistas de una turbina) reutilizan la misma.
    """

    def __init__(self, world, safety, inspected=()):
        self.world = world
        self.safety = safety
        self.inspected = sorted(n for n in inspected if n)
        self.models = []
        for name in self.inspected:
            model = world.target(name).model
            lo, hi = model.aabb(only_inspectable=False)
            pad = safety.min_clearance_m + 1.0
            self.models.append((name, model, lo - pad, hi + pad))
        self.simple = [o for o in world.simple_objects() if o.name not in self.inspected]
        self._grids = []

    def margin(self, P):
        return self._margins(P)[0]

    def _margins(self, P):
        """(margen mínimo por punto, [(nombre, margen por punto)] de cada restricción)."""
        P = np.atleast_2d(np.asarray(P, float))
        parts = [("altitud mínima", P[:, 2] - self.safety.min_altitude_m)]
        for name, model, lo, hi in self.models:
            near = ((P >= lo) & (P <= hi)).all(axis=1)   # lejos de la caja, el modelo no limita
            d = np.full(len(P), np.inf)
            if near.any():
                d[near] = model.sdf_all(P[near])[0] - self.safety.min_clearance_m
            parts.append((f"{name} (modelo, mín {self.safety.min_clearance_m} m)", d))
        for obj in self.simple:
            parts.append((f"{obj.name} (geometría simple, mín {self.safety.transit_clearance_m} m)",
                          obj.sdf(P) - self.safety.transit_clearance_m))
        m = parts[0][1]
        for _, d in parts[1:]:
            m = np.minimum(m, d)
        return m, parts

    def explain(self, p):
        """Qué restricción viola el punto `p`, o None si es libre."""
        m, parts = self._margins(np.asarray(p, float)[None])
        if m[0] >= MARGIN_M:
            return None
        name, d = min(parts, key=lambda x: x[1][0])
        return f"{name}: le faltan {MARGIN_M - d[0]:.1f} m"

    def seg_free(self, A, B):
        A, B = np.asarray(A, float), np.asarray(B, float)
        n = max(2, int(np.linalg.norm(B - A) / SAMPLE_STEP_M) + 1)
        P = A + np.linspace(0, 1, n)[:, None] * (B - A)
        return bool(self.margin(P).min() >= MARGIN_M)

    def grid_for(self, A, B):
        """Una rejilla que contenga A y B: la cacheada si sirve, si no una nueva que cubra también los modelos."""
        for g in self._grids:
            lo, hi = g.lo, g.hi
            if ((np.minimum(A, B) >= lo).all() and (np.maximum(A, B) <= hi).all()):
                return g
        g = Grid(self, A, B)
        self._grids.append(g)
        return g


class Grid:
    """Rejilla 3D de celdas libres, indexada en plano para que el A* sea rápido en Python."""

    def __init__(self, field, A, B):
        safety = field.safety
        lo, hi = np.minimum(A, B), np.maximum(A, B)
        for _, _, mlo, mhi in field.models:   # cubrir el target entero: los demás tramos la reutilizan
            lo, hi = np.minimum(lo, mlo), np.maximum(hi, mhi)
        lo = lo - [PAD_XY_M, PAD_XY_M, 0]
        hi = hi + [PAD_XY_M, PAD_XY_M, PAD_Z_M]
        lo[2] = safety.min_altitude_m
        hi[2] = max(safety.max_altitude_m, A[2], B[2])
        gf = field.world.geofence()
        if gf is not None:
            lo[:2] = np.maximum(lo[:2], gf[0])
            hi[:2] = np.minimum(hi[:2], gf[1])
        res = 2.0
        while np.prod(np.ceil((hi - lo) / res) + 1) > MAX_CELLS:
            res *= 1.5
        shape = np.ceil((hi - lo) / res).astype(int) + 1
        P = lo + np.indices(shape).reshape(3, -1).T * res
        free = field.margin(P) >= MARGIN_M + 0.5 * res
        self.lo, self.res = lo, res
        self.hi = lo + (shape - 1) * res
        self.shape = tuple(int(x) for x in shape)
        self.free = free.tobytes()           # 1 byte por celda, índice plano i*sy*sz + j*sz + k

    def index(self, c):
        return (c[0] * self.shape[1] + c[1]) * self.shape[2] + c[2]

    def coords(self, n):
        sy, sz = self.shape[1], self.shape[2]
        return n // (sy * sz), (n // sz) % sy, n % sz

    def point(self, n):
        return self.lo + np.array(self.coords(n)) * self.res

    def snap(self, field, p):
        base = np.round((p - self.lo) / self.res).astype(int)
        for r in range(0, 5):
            best = None
            for off in np.indices((2 * r + 1,) * 3).reshape(3, -1).T - r:
                c = base + off
                if (c < 0).any() or (c >= self.shape).any() or not self.free[self.index(c)]:
                    continue
                q = self.lo + c * self.res
                dd = float(np.linalg.norm(q - p))
                if (best is None or dd < best[0]) and field.seg_free(p, q):
                    best = (dd, self.index(c))
            if best:
                return best[1]
        return None

    def astar(self, s, g):
        sx, sy, sz = self.shape
        free, res = self.free, self.res
        gi, gj, gk = self.coords(g)
        steps = [(di, dj, dk, (di * sy + dj) * sz + dk, res * math.sqrt(di * di + dj * dj + dk * dk))
                 for di, dj, dk in _NB]

        def h(i, j, k):
            return res * math.sqrt((i - gi) ** 2 + (j - gj) ** 2 + (k - gk) ** 2)

        si, sj, sk = self.coords(s)
        openq, came, cost = [(h(si, sj, sk), 0.0, s, si, sj, sk)], {s: None}, {s: 0.0}
        while openq:
            _, gc, cur, i, j, k = heapq.heappop(openq)
            if cur == g:
                break
            if gc > cost[cur] + 1e-9:
                continue
            for di, dj, dk, doff, step in steps:
                ni, nj, nk = i + di, j + dj, k + dk
                if not (0 <= ni < sx and 0 <= nj < sy and 0 <= nk < sz):
                    continue
                nb = cur + doff
                if not free[nb]:
                    continue
                nc = gc + step
                if nc < cost.get(nb, 1e18):
                    cost[nb], came[nb] = nc, cur
                    heapq.heappush(openq, (nc + h(ni, nj, nk), nc, nb, ni, nj, nk))
        else:
            return None
        path, c = [], g
        while c is not None:
            path.append(self.point(c))
            c = came[c]
        return path[::-1]


_NB = [(i, j, k) for i in (-1, 0, 1) for j in (-1, 0, 1) for k in (-1, 0, 1) if (i, j, k) != (0, 0, 0)]


def find_via(field, A, B, world=None):
    """Puntos de paso intermedios (lista de np.array) que hacen volable A→B, o None si no hay."""
    A, B = np.asarray(A, float), np.asarray(B, float)
    grid = field.grid_for(A, B)
    s, g = grid.snap(field, A), grid.snap(field, B)
    if s is None or g is None:
        return None
    cells = grid.astar(s, g)
    if cells is None:
        return None
    pts = [A] + cells + [B]
    # atajos: del punto actual, al más lejano que se alcanza en línea recta
    out, i = [A], 0
    while i < len(pts) - 1:
        j = len(pts) - 1
        while j > i + 1 and not field.seg_free(pts[i], pts[j]):
            j -= 1
        out.append(pts[j])
        i = j
    return out[1:-1]


def leg_context(wps, i):
    """Targets de contexto del tramo i→i+1: los de los waypoints no-transit que lo encierran."""
    a = i
    while a > 0 and wps[a].get("type") == "transit":
        a -= 1
    b = i + 1
    while b < len(wps) - 1 and wps[b].get("type") == "transit":
        b += 1
    return {t for t in (wps[a].get("target"), wps[b].get("target")) if t}
