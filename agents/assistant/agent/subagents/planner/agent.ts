import { defineAgent, defineDynamic } from "eve";
import { resolveModel } from "#shared/models";

// Planificación es la tarea de razonamiento más pesada del sistema (capability:
// high en multiuav_gcs): geometría 3D, coste de rutas y reparación iterativa
// contra el validador. Usa el modelo más capaz disponible, no el rápido.
export default defineAgent({
  description:
    "Planificador de misiones multi-UAV. Recibe targets, drones y estrategia de inspección, " +
    "y construye un plan de vuelo en coordenadas XYZ: modela obstáculos, asigna targets a drones, " +
    "genera waypoints de inspección, ordena rutas por coste y repara colisiones hasta que el " +
    "validador lo acepta. Delegá acá toda creación de plan de misión: no calcules waypoints vos mismo.",
  model: defineDynamic({
    events: {
      "step.started": () => resolveModel("high"),
    },
  }),
});
