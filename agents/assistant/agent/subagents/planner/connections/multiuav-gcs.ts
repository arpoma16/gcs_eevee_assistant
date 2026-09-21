import { defineMcpClientConnection } from "eve/connections";

// Los subagentes declarados NO heredan las connections del padre: el planner
// declara la suya, con su propia allowlist. Es lo que impide que planifique con
// tools del operador o que arranque misiones.
export default defineMcpClientConnection({
  url: process.env.GCS_MCP_URL ?? "http://127.0.0.1:3001/mcp",
  description:
    "Ground Control Station multi-UAV: avance de pasos de planificación y validación de " +
    "misiones XYZ contra la base de obstáculos 3D (detección de colisiones y persistencia del plan).",
  tools: { allow: ["mark_step_complete", "validate_mission"] },
  toolCall: {
    // `chat_id` pertenece a la aplicación, no al modelo: eve lo saca del schema
    // que ve el modelo y lo inyecta antes de ejecutar. El mcp_server lo usa para
    // notificar al chat del GCS cuando el plan queda persistido.
    providedArguments: {
      chat_id: () => process.env.GCS_CHAT_ID ?? "",
    },
  },
});
