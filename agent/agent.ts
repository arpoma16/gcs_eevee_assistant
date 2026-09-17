import { defineAgent, defineDynamic } from "eve";
import { google } from "@ai-sdk/google";
import { openai, createOpenAI } from "@ai-sdk/openai";

// Provider directo con API key propia (sin Vercel AI Gateway).
// La key define el provider; EVE_MODEL permite cambiar de modelo sin tocar código.
// Nota: un LanguageModel de provider directo no es serializable, así que la
// selección durable ("session.started") no aplica — debe resolverse por step.
export default defineAgent({
  model: defineDynamic({
    events: {
      "step.started": () => {
        // llama.cpp local: expone API compatible con OpenAI en /v1.
        // Gateada por LLAMACPP_BASE_URL (no por una API key, porque no hay
        // una key real que validar contra un servidor local).
        if (process.env.LLAMACPP_BASE_URL) {
          const llamacpp = createOpenAI({
            baseURL: process.env.LLAMACPP_BASE_URL,
            apiKey: "llamacpp-local", // el SDK exige un valor, llama.cpp lo ignora
          });
          return {
            // .chat() fuerza /v1/chat/completions. El default de createOpenAI()
            // (sin .chat) usa la Responses API (/v1/responses), que llama.cpp
            // sólo soporta parcialmente y rompe la validación de tipos del SDK.
            model: llamacpp.chat(process.env.EVE_MODEL ?? "local-model"),
            // Modelo no listado en el catálogo de AI Gateway: sin esto eve
            // intenta resolver el context window contra ese catálogo y falla.
            modelContextWindowTokens: Number(
              process.env.LLAMACPP_CONTEXT_WINDOW ?? 8192,
            ),
          };
        }
        if (process.env.GOOGLE_GENERATIVE_AI_API_KEY) {
          return google(process.env.EVE_MODEL ?? "gemini-2.5-flash");
        }
        if (process.env.OPENAI_API_KEY) {
          return openai(process.env.EVE_MODEL ?? "gpt-5.1");
        }
        throw new Error(
          "Falta la API key del modelo: definí LLAMACPP_BASE_URL, GOOGLE_GENERATIVE_AI_API_KEY u OPENAI_API_KEY en .env (ver .env.example)",
        );
      },
    },
  }),
});
