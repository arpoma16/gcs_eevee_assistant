import { defineAgent, defineDynamic } from "eve";
import { resolveModel } from "#shared/models";

// El orquestador rutea, consulta telemetría y delega: tarea liviana, tier
// medium. El razonamiento pesado vive en los planners (tier high).
//
// Se resuelve por step y no en "session.started" porque los providers directos
// devuelven un LanguageModel vivo, que no es serializable: eve sólo acepta
// objetos de modelo desde "step.started" (ids string en session/turn).
export default defineAgent({
  model: defineDynamic({
    events: {
      "step.started": () => resolveModel("medium"),
    },
  }),
});
