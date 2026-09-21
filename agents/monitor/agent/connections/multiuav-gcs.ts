import { defineMcpClientConnection } from "eve/connections";

// El monitor sólo observa: esta allowlist es su límite real, no una política de
// aprobación. Las tools que llegan a los UAVs (load_mission_to_uav,
// start_mission, send_command) NO están acá, así que no existen para él y no
// hay nada que pueda alucinar. Ese es el punto de darle un agente aparte en vez
// de un schedule dentro del asistente, que comparte su connection.
const READ_ONLY_TOOLS = ["get_fleet_telemetry", "get_devices", "get_registered_objects"];

export default defineMcpClientConnection({
  // Mismo mcp_server que el asistente: el GCS ya es el punto de entrada único
  // hacia los UAVs, no hace falta otro.
  url: process.env.GCS_MCP_URL ?? "http://127.0.0.1:3001/mcp",
  description:
    "Ground Control Station multi-UAV, en modo lectura: telemetría de la flota, " +
    "estado de los dispositivos y objetos registrados en el catálogo.",
  tools: { allow: READ_ONLY_TOOLS },
  // Sin aprobación humana a propósito: el monitor corre por cron, sin nadie
  // mirando, y ninguna de estas tools tiene efecto sobre los UAVs. Si alguna
  // vez se le suma una tool con efecto, esto tiene que volver a "user-approval".
  approval: () => "not-applicable",
});
