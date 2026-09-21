import { defineAgent } from "eve";
import { resolveModel } from "../../lib/models";

export default defineAgent({
  description:
    "Planificador de misiones multi-UAV que computa la geometría con scripts en el sandbox en vez " +
    "de razonarla: mide la distribución espacial, genera los waypoints de inspección y ordena las " +
    "rutas ejecutando un pipeline Python determinista, y solo decide la estrategia y la reparación " +
    "de colisiones. Variante de `planner` para misiones donde los números no pueden ser estimados.",
  ...resolveModel("high"),
});
