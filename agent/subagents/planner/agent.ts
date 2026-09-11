import { defineAgent } from "eve";
import { google } from "@ai-sdk/google";
import { openai } from "@ai-sdk/openai";

// Planificación es la tarea de razonamiento más pesada del sistema (capability:
// high en multiuav_gcs): geometría 3D, coste de rutas y reparación iterativa
// contra el validador. Usa el modelo más capaz disponible, no el rápido.
const model = process.env.GOOGLE_GENERATIVE_AI_API_KEY
  ? google(process.env.EVE_PLANNER_MODEL ?? "gemini-2.5-pro")
  : openai(process.env.EVE_PLANNER_MODEL ?? "gpt-5.1");

export default defineAgent({
  description:
    "Planificador de misiones multi-UAV. Recibe targets, drones y estrategia de inspección, " +
    "y construye un plan de vuelo en coordenadas XYZ: modela obstáculos, asigna targets a drones, " +
    "genera waypoints de inspección, ordena rutas por coste y repara colisiones hasta que el " +
    "validador lo acepta. Delegá acá toda creación de plan de misión: no calcules waypoints vos mismo.",
  model,
});
