"""Formato de misión v4 (grafo de tareas del GCS): el ÚNICO lugar que lo conoce.

    {version: "4", name, description, global_origin, tasks: [
      {task_id, device, action, depends_on, uav_type, name,
       params: {mode_landing, mode_yaw, mode_gimbal, mode_trace, idle_vel, max_vel},
       wp: [{pos, yaw, gimbal, speed, action, type, target, tag}]}]}

Referencia: multiuav_gcs/server/CLAUDE.md › "Mission Planning System". Una tarea
corre en UN dron y arranca cuando terminan las de `depends_on`; el GCS rechaza dos
tareas del mismo dron que el grafo no ordena. `action` es solo semántica (UI, logs).
En el sandbox `pos` es ENU en metros [x, y, z]; el gate lo convierte a geodésico
(lat, lon, alt) al persistir, y para eso necesita `global_origin`. `type`, `target`
y `tag` son los tres campos propios de este planner: tipo de waypoint (takeoff |
transit | inspection | landing), target inspeccionado y una etiqueta de trazabilidad
(parte/superficie/zona/feature).
"""
from __future__ import annotations

import json
from pathlib import Path

VERSION = "4"
WAYPOINT_TYPES = ("takeoff", "transit", "inspection", "landing")
INSPECT_ACTION = "INSPECT"

DEFAULT_PARAMS = {
    "mode_landing": 0,
    "mode_yaw": 3,       # yaw por waypoint
    "mode_gimbal": 0,
    "mode_trace": 0,
    "idle_vel": 2.0,     # velocidad de crucero (m/s)
    "max_vel": 5.0,
}


def waypoint(pos, type, *, yaw=None, gimbal=None, speed=None, action=None, target=None, tag=None):
    if type not in WAYPOINT_TYPES:
        raise ValueError(f"tipo de waypoint {type!r} no válido: {WAYPOINT_TYPES}")
    return {
        "pos": [round(float(v), 3) for v in pos],
        "yaw": None if yaw is None else round(float(yaw), 1),
        "gimbal": None if gimbal is None else round(float(gimbal), 1),
        "speed": speed,
        "action": action,
        "type": type,
        "target": target,
        "tag": tag,
    }


def task(task_id, device, uav_type, wp, *, action=INSPECT_ACTION, name=None, depends_on=(), params=None):
    return {
        "task_id": task_id,
        "device": device,
        "action": action,
        "depends_on": list(depends_on),
        "name": name or f"{task_id}_{device}",
        "uav_type": uav_type,
        "params": {**DEFAULT_PARAMS, **(params or {})},
        "wp": wp,
    }


def mission(tasks, global_origin, *, name="mission", description=""):
    return {
        "version": VERSION,
        "name": name,
        "description": description,
        "global_origin": global_origin,
        "tasks": tasks,
    }


def save(payload, path):
    Path(path).write_text(json.dumps(payload, indent=1, ensure_ascii=False))


def load(path):
    return json.loads(Path(path).read_text())


# ---------------------------------------------------------------------------
# dependencias entre tareas
# ---------------------------------------------------------------------------
def ancestors(task_id, deps):
    """Todas las tareas que tienen que terminar antes de `task_id` (deps: {task_id: [depends_on]})."""
    seen, stack = set(), list(deps.get(task_id, []))
    while stack:
        t = stack.pop()
        if t not in seen:
            seen.add(t)
            stack.extend(deps.get(t, []))
    return seen


def sequenced(a, b, deps):
    """True si una de las dos tareas espera a la otra (directa o transitivamente)."""
    return a in ancestors(b, deps) or b in ancestors(a, deps)


def finish_times(durations, deps):
    """Fin de cada tarea por ruta crítica: arranca cuando terminan sus dependencias.

    Lanza ValueError si hay un ciclo.
    """
    done, visiting = {}, set()

    def finish(t):
        if t in done:
            return done[t]
        if t in visiting:
            raise ValueError(f"ciclo de depends_on que pasa por {t}")
        visiting.add(t)
        start = max((finish(d) for d in deps.get(t, [])), default=0.0)
        visiting.discard(t)
        done[t] = start + durations[t]
        return done[t]

    for t in durations:
        finish(t)
    return done
