"""Inspección de las palas de un aerogenerador, no de la torre.

Segundo ejemplo de patrón, y el que muestra por qué existen: las palas no están
en el suelo ni alrededor del elemento — están a la altura del buje, en el plano
del rotor, repartidas por igual. Ningún anillo puede expresar eso.

Geometría, en el marco local (origen en el centro de la torre, a nivel del
suelo; +Y hacia donde mira el rotor):

    buje           (0, 0, hub_height)
    plano del rotor  el plano X–Z: perpendicular a la dirección de yaw
    pala k         sale del buje a `blade_angle` grados dentro de ese plano
    viewpoint      delante de la cara del rotor (+Y), a `stand_off` de la pala

Espera en la entrada del tipo, en geometry.json:

    hub_height     altura del buje sobre el suelo, en metros
    blade_length   largo de pala desde el buje
    blade_count    cuántas palas (3 en casi todos)
    blade_samples  puntos por pala, de raíz a punta (por defecto 3)
    stand_off      separación de la cámara a la pala
"""

import math


def viewpoints(element, params):
    hub_height = float(element["hub_height"])
    blade_length = float(element["blade_length"])
    blade_count = int(element.get("blade_count", 3))
    samples = int(element.get("blade_samples", 3))
    stand_off = float(params["stand_off"])

    points = []
    for blade in range(blade_count):
        # 0° = pala hacia arriba; el resto se reparte por igual en el disco.
        angle = math.radians(360.0 * blade / blade_count)

        for sample in range(samples):
            # De raíz a punta, sin llegar al buje ni pasarse de la punta.
            reach = blade_length * (sample + 1) / samples
            bx = reach * math.sin(angle)
            bz = hub_height + reach * math.cos(angle)

            points.append(
                {
                    "label": f"B{blade + 1}-{sample + 1}",
                    # Delante de la cara del rotor, a la altura de ese tramo de pala.
                    "local": (bx, stand_off, bz),
                    # La cámara mira la pala, no el eje de la torre.
                    "yaw_towards": (bx, 0.0, bz),
                }
            )
    return points
