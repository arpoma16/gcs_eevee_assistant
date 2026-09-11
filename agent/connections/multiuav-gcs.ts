import { defineMcpClientConnection } from "eve/connections";

// Tools cuyo efecto llega a los UAVs reales: siempre piden aprobación humana.
const FLIGHT_CRITICAL_TOOLS = ["load_mission_to_uav", "start_mission", "send_command"];

// Allowlist estricta del agente operador (docs/tools.md). Quedan fuera a propósito:
// - request_mission_plan / delegate_mission_plan_generation: rebotan al
//   orquestador viejo del GCS; acá la delegación al planner es nativa de eve.
// - mark_step_complete / validate_mission: son del planner, que declara su
//   propia connection en agent/subagents/planner/connections/.
const ALLOWED_TOOLS = [
  "get_devices",
  "get_fleet_telemetry",
  "get_registered_objects",
  "get_element_groups",
  "get_bases_with_assignments",
  "show_mission_to_user",
  "load_mission_to_uav",
  "start_mission",
];

export default defineMcpClientConnection({
  // mcp_server de multiuav en transporte Streamable HTTP:
  //   cd llm_planner_gcs/mcp_server && npx tsx src/index.ts http
  url: process.env.GCS_MCP_URL ?? "http://127.0.0.1:3001/mcp",
  description:
    "Ground Control Station multi-UAV: estado y telemetría de la flota de drones, " +
    "objetos y bases registrados, visualización y validación de planes de misión, " +
    "carga y arranque de misiones en los UAVs.",
  tools: { allow: ALLOWED_TOOLS },
  approval: ({ toolName }) =>
    FLIGHT_CRITICAL_TOOLS.some((t) => toolName.endsWith(t)) ? "user-approval" : "not-applicable",
});
