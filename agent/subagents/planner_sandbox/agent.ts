import { defineAgent } from "eve";
import { google } from "@ai-sdk/google";
import { openai } from "@ai-sdk/openai";

const model = process.env.GOOGLE_GENERATIVE_AI_API_KEY
  ? google(process.env.EVE_PLANNER_MODEL ?? "gemini-3.1-pro-preview")
  : openai(process.env.EVE_PLANNER_MODEL ?? "gpt-5.1");

export default defineAgent({
  description:
    "Planificador de misiones multi-UAV que computa la geometría con scripts en el sandbox en vez " +
    "de razonarla: mide la distribución espacial, genera los waypoints de inspección y ordena las " +
    "rutas ejecutando un pipeline Python determinista, y solo decide la estrategia y la reparación " +
    "de colisiones. Variante de `planner` para misiones donde los números no pueden ser estimados.",
  model,
});
