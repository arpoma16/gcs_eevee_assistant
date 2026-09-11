import { defineAgent, defineDynamic } from "eve";
import { google } from "@ai-sdk/google";
import { openai } from "@ai-sdk/openai";

// Provider directo con API key propia (sin Vercel AI Gateway).
// La key define el provider; EVE_MODEL permite cambiar de modelo sin tocar código.
// Nota: un LanguageModel de provider directo no es serializable, así que la
// selección durable ("session.started") no aplica — debe resolverse por step.
export default defineAgent({
  model: defineDynamic({
    events: {
      "step.started": () => {
        if (process.env.GOOGLE_GENERATIVE_AI_API_KEY) {
          return google(process.env.EVE_MODEL ?? "gemini-2.5-flash");
        }
        if (process.env.OPENAI_API_KEY) {
          return openai(process.env.EVE_MODEL ?? "gpt-5.1");
        }
        throw new Error(
          "Falta la API key del modelo: definí GOOGLE_GENERATIVE_AI_API_KEY u OPENAI_API_KEY en .env (ver .env.example)",
        );
      },
    },
  }),
});
