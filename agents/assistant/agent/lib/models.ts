import { google } from "@ai-sdk/google";
import { createOpenAI, openai } from "@ai-sdk/openai";
import type { LanguageModel } from "ai";

/**
 * Catálogo de modelos: un agente declara el NIVEL de capacidad que necesita,
 * no el modelo concreto. El provider se resuelve una sola vez, acá, según las
 * credenciales disponibles — así cambiar de proveedor no toca ningún agent.ts.
 */

/** Qué tan capaz tiene que ser el modelo para la responsabilidad del agente. */
export type Tier = "high" | "medium" | "low";

/** Proveedores soportados, en orden de precedencia cuando no se fuerza uno. */
export type Provider = "llamacpp" | "google" | "openai";

/**
 * Lo que consume `defineAgent`. En config estática va como campos hermanos de
 * `model`; en un `defineDynamic` va como el objeto que devuelve el handler
 * (ahí `modelContextWindowTokens` no puede ser hermano: el tipo lo marca
 * `never`, ver eve/dist/src/shared/agent-definition.d.ts).
 */
export type ModelSelection = {
  model: LanguageModel;
  modelContextWindowTokens?: number;
};

type ProviderEntry = {
  /** Qué env var habilita este provider. */
  enabled: () => boolean;
  /** Para el mensaje de error cuando no hay ningún provider disponible. */
  requires: string;
  /** El id nativo del modelo de este provider, por tier. */
  models: Record<Tier, string>;
  /** Construye el LanguageModel del AI SDK para un id de este provider. */
  build: (modelId: string) => LanguageModel;
  /**
   * Context window, sólo para modelos que no están en el catálogo de AI
   * Gateway: sin esto eve intenta resolverlo contra ese catálogo y falla.
   */
  contextWindowTokens?: () => number;
};

const CATALOG: Record<Provider, ProviderEntry> = {
  // llama.cpp local: un servidor sirve UN modelo cargado, así que los tres
  // tiers apuntan al mismo salvo que se corran varios servidores y se separen
  // con los overrides por tier de abajo.
  // OJO: `high` acá es el planner (geometría 3D, reparación de colisiones
  // contra el validador). Un modelo local chico va a generar planes que el
  // validador rechaza en loop; forzá un provider cloud para vuelo real.
  llamacpp: {
    enabled: () => Boolean(process.env.LLAMACPP_BASE_URL),
    requires: "LLAMACPP_BASE_URL",
    models: {
      high: process.env.LLAMACPP_MODEL ?? "local-model",
      medium: process.env.LLAMACPP_MODEL ?? "local-model",
      low: process.env.LLAMACPP_MODEL ?? "local-model",
    },
    build: (modelId) =>
      createOpenAI({
        baseURL: process.env.LLAMACPP_BASE_URL,
        apiKey: "llamacpp-local", // el SDK exige un valor, llama.cpp lo ignora
      })
        // .chat() fuerza /v1/chat/completions. El default de createOpenAI()
        // usa la Responses API (/v1/responses), que llama.cpp sólo soporta
        // parcialmente y rompe la validación de tipos del SDK.
        .chat(modelId),
    contextWindowTokens: () => Number(process.env.LLAMACPP_CONTEXT_WINDOW ?? 8192),
  },

  google: {
    enabled: () => Boolean(process.env.GOOGLE_GENERATIVE_AI_API_KEY),
    requires: "GOOGLE_GENERATIVE_AI_API_KEY",
    models: {
      high: "gemini-3.1-pro-preview",
      medium: "gemini-2.5-flash",
      // Sin dato de un modelo más barato en uso: repetido a propósito en vez
      // de inventar un id. Ajustalo si tenés un flash-lite habilitado.
      low: "gemini-2.5-flash",
    },
    build: (modelId) => google(modelId),
  },

  openai: {
    enabled: () => Boolean(process.env.OPENAI_API_KEY),
    requires: "OPENAI_API_KEY",
    models: {
      high: "gpt-5.1",
      // Ídem: mismo id en los tres tiers hasta confirmar qué modelos más
      // baratos tenés habilitados en la cuenta.
      medium: "gpt-5.1",
      low: "gpt-5.1",
    },
    build: (modelId) => openai(modelId),
  },
};

/** Orden de precedencia cuando EVE_PROVIDER no fuerza uno. */
const PRECEDENCE: Provider[] = ["llamacpp", "google", "openai"];

/**
 * Override del id del modelo por tier: `EVE_MODEL_HIGH`, `EVE_MODEL_MEDIUM`,
 * `EVE_MODEL_LOW`. Los nombres viejos (`EVE_MODEL` para el orquestador,
 * `EVE_PLANNER_MODEL` para los planners) siguen funcionando como fallback.
 */
function modelOverride(tier: Tier): string | undefined {
  const byTier = process.env[`EVE_MODEL_${tier.toUpperCase()}`];
  if (byTier) return byTier;
  if (tier === "high") return process.env.EVE_PLANNER_MODEL;
  if (tier === "medium") return process.env.EVE_MODEL;
  return undefined;
}

function resolveProvider(): Provider {
  const forced = process.env.EVE_PROVIDER as Provider | undefined;

  if (forced) {
    const entry = CATALOG[forced];
    if (!entry) {
      throw new Error(
        `EVE_PROVIDER="${forced}" no es un provider conocido. Opciones: ${PRECEDENCE.join(", ")}`,
      );
    }
    if (!entry.enabled()) {
      throw new Error(
        `EVE_PROVIDER="${forced}" está forzado pero falta ${entry.requires} en .env`,
      );
    }
    return forced;
  }

  const available = PRECEDENCE.find((provider) => CATALOG[provider].enabled());
  if (!available) {
    const options = PRECEDENCE.map((p) => CATALOG[p].requires).join(", ");
    throw new Error(
      `Falta la credencial del modelo: definí una de ${options} en .env, ` +
        "o forzá un provider con EVE_PROVIDER",
    );
  }
  return available;
}

/**
 * Resuelve el modelo para un tier contra el provider activo.
 *
 * Tira si no hay ningún provider disponible: preferimos fallar al arrancar,
 * con el nombre de la env var que falta, antes que fallar en la llamada al
 * provider recién cuando el orquestador delega al planner.
 */
export function resolveModel(tier: Tier): ModelSelection {
  const provider = resolveProvider();
  const entry = CATALOG[provider];
  const modelId = modelOverride(tier) ?? entry.models[tier];

  const contextWindowTokens = entry.contextWindowTokens?.();

  return contextWindowTokens === undefined
    ? { model: entry.build(modelId) }
    : { model: entry.build(modelId), modelContextWindowTokens: contextWindowTokens };
}
