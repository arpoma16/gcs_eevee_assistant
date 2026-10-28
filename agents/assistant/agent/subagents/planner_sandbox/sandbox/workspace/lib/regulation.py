"""Normativa de altura: Reglamento de Ejecución (UE) 2019/947, Anexo Parte A, UAS.OPEN.010.

Techo general: 120 m sobre la superficie. Excepción (UAS.OPEN.010(2)): volando a
menos de 50 m en horizontal de un obstáculo artificial de más de 105 m de altura,
se puede subir hasta 15 m por encima del obstáculo, **a petición de la entidad
responsable del obstáculo**. Una inspección contratada por el titular cumple esa
condición; si no es el caso, desactivala con `Safety(tall_obstacle_exception=False)`.

Ejemplo: aerogenerador con la punta de pala a 130 m → a menos de 50 m de él, el
techo pasa a 145 m. A 60 m de distancia vuelve a ser 120 m.

Las alturas se miden desde la base de cada elemento (su `position.z`), y la del
dron desde el mismo nivel de referencia: se asume terreno llano.
"""
from __future__ import annotations

import numpy as np

GENERAL_CEILING_M = 120.0
TALL_OBSTACLE_MIN_HEIGHT_M = 105.0
TALL_OBSTACLE_EXTRA_M = 15.0
TALL_OBSTACLE_RADIUS_M = 50.0


def model_height(model):
    """Altura real del elemento con SU estado (p.ej. una pala vertical cuenta)."""
    if getattr(model, "_height_m", None) is None:
        _, hi = model.aabb(only_inspectable=False)
        model._height_m = float(hi[2] - model.origin[2])
    return model._height_m


def model_horizontal_distance(model, xy, step=1.0):
    """Distancia horizontal de la vertical que pasa por `xy` al elemento (0 si la atraviesa)."""
    base, top = model.origin[2], model.origin[2] + model_height(model)
    zs = np.arange(base, top + step, step)
    P = np.c_[np.full_like(zs, xy[0]), np.full_like(zs, xy[1]), zs]
    return max(0.0, float(model.sdf_all(P)[0].min()))


def altitude_ceiling(pos, safety, target=None, others=(), targets=()):
    """(techo en m, elemento que lo eleva o None) para el punto `pos`.

    `target`/`targets` se miden con su modelo completo; `others` (SimpleObject)
    con la geometría de catálogo.

    Solo calcula la excepción cuando `pos` supera el techo general: es lo único
    que la cambia, y evita muestrear modelos para cada punto.
    """
    ceiling = safety.max_altitude_m
    if not getattr(safety, "tall_obstacle_exception", False) or pos[2] <= ceiling:
        return ceiling, None
    raised_by = None
    candidates = []
    for t in ([target] if target is not None else []) + list(targets):
        candidates.append((t.name, t.model.origin[2], model_height(t.model),
                           lambda t=t: model_horizontal_distance(t.model, pos[:2])))
    for obj in others:
        candidates.append((obj.name, obj.position[2], obj.height,
                           lambda obj=obj: obj.horizontal_distance(pos[:2])))
    for name, base, height, hdist in candidates:
        if height <= TALL_OBSTACLE_MIN_HEIGHT_M:
            continue
        limit = base + height + TALL_OBSTACLE_EXTRA_M
        if limit > ceiling and hdist() <= TALL_OBSTACLE_RADIUS_M:
            ceiling, raised_by = limit, name
    return ceiling, raised_by
