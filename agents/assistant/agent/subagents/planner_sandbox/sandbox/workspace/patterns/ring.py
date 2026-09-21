"""Patrón de referencia: un anillo de viewpoints alrededor del elemento.

Es el patrón por defecto y, sobre todo, el EJEMPLO a imitar cuando escribas uno
propio. Un patrón es un módulo con una función:

    viewpoints(element, params) -> [ {label, local, yaw_towards}, ... ]

donde:

  element  dict con la geometría del elemento que derivaste por tipo:
           `dimensions`, `height`, `safety_margin`, `footprint` (radio real ya
           calculado). NO trae la posición: no la necesitás y no la vas a ver.

  params   los parámetros de vuelo resueltos para este elemento:
           `stand_off`, `altitude_fraction`, `viewpoints`, y cualquier extra que
           hayas puesto en su entrada de geometry.json.

Cada viewpoint se devuelve en el MARCO LOCAL del elemento (origen en el centro
de su huella, a nivel del suelo; +Y hacia donde mira, +Z hacia arriba):

  label        nombre corto y único dentro del elemento
  local        (x, y, z) en metros, relativo al centro
  yaw_towards  (opcional) punto local al que debe apuntar la cámara.
               Por defecto (0, 0, z_del_waypoint): el eje del elemento.

El runner rota el marco por el yaw del elemento, lo traslada a su posición real
y calcula el yaw de cámara. Vos nunca escribís una coordenada del mundo.
"""

import math

COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


def label_for(index, count, angle_deg):
    if count in (4, 8):
        return COMPASS[index * (len(COMPASS) // count)]
    return f"P{index + 1}-{round(angle_deg)}deg"


def viewpoints(element, params):
    radius = max(
        element["footprint"] + float(params["stand_off"]),
        element["footprint"] + float(element["safety_margin"]),  # R_SAFE: la seguridad gana
    )
    z = float(element["height"]) * float(params["altitude_fraction"])
    count = int(params["viewpoints"])

    points = []
    for i in range(count):
        angle = 360.0 * i / count  # 0 = hacia donde mira el elemento, sentido horario
        rad = math.radians(angle)
        points.append(
            {
                "label": label_for(i, count, angle),
                # En el marco local: +Y es la dirección de yaw del elemento.
                "local": (radius * math.sin(rad), radius * math.cos(rad), z),
            }
        )
    return points
