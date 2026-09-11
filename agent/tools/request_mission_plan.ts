import { defineWorkflowTool } from "eve/tools";
import { encode } from "@toon-format/toon";
import { z } from "zod";

const GCS_API_URL = process.env.MUAV_API_URL ?? "http://localhost:4000/api";

const TargetSchema = z.object({
  id: z.string().describe("Unique identifier of the element to inspect"),
  name: z.string().describe("Name of the element to inspect"),
  type: z.string().describe("Type of the element to inspect"),
  group: z.string().describe("Group name"),
});

const DeviceSchema = z.object({
  id: z.string().describe("Device identifier"),
  name: z.string().describe("Device name"),
  category: z.string().describe("Device category/type"),
  battery_level: z.number().describe("Battery level percentage"),
});

type Briefing = {
  global_origin: { lat: number; lng: number; alt: number };
  devices: unknown[];
  targets: { id: string }[];
  obstacles: unknown[];
  boundaries: unknown;
};

/**
 * Resolves the briefing against the GCS: every device and target the model
 * named is checked against the database, positions are converted from geodetic
 * to ENU/XYZ around a local origin, and obstacles and boundaries are resolved
 * from the catalog. A hallucinated id, name or category is rejected here — this
 * is the only point where the model's claims meet the real data.
 */
async function resolveBriefing(
  targets: z.infer<typeof TargetSchema>[],
  selected_devices: z.infer<typeof DeviceSchema>[],
): Promise<Briefing> {
  "use step";

  const response = await fetch(`${GCS_API_URL}/missions/convert/geodetic-to-xyz`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ selected_devices, targets }),
  });

  const body = await response.json();
  if (!response.ok) {
    throw new Error(body?.error ?? `Mission briefing conversion failed (HTTP ${response.status})`);
  }
  return body as Briefing;
}

/** The exact section layout the planner's Step 1 reads. */
function formatBriefing(
  input: { user_request: string; mission_strategy: string; mission_strategy_description: string },
  briefing: Briefing,
): string {
  return `Execute the MISSION PLANNING SEQUENCE for solve the user request
${input.user_request} using a ${input.mission_strategy} strategy following the description: ${input.mission_strategy_description}.

## global_origin_coordinates
${JSON.stringify(briefing.global_origin)}
## target_ids
${briefing.targets.map((target) => target.id).join(", ")}
## Devices Information
${encode(briefing.devices)}
## Elements to Inspect
${encode(briefing.targets)}
## obstacles Information
${encode(briefing.obstacles)}
## boundaries the devices must work into the mission area
${encode(briefing.boundaries)}`;
}

export default defineWorkflowTool({
  description:
    "Submit pre-collected and filtered data to the mission planner sub-agent. " +
    "REQUIRES: target elements from get_registered_objects and drone info from get_devices/get_fleet_telemetry. " +
    "Do NOT call this tool without first gathering all required data through the appropriate tools. " +
    "Obstacles and coordinate conversion are resolved server-side — never send obstacles, never convert coordinates yourself. " +
    "The planner works asynchronously: this returns immediately and the plan arrives later.",
  execution: "background",
  inputSchema: z.object({
    user_request: z.string().describe("The intent of the user request that led to this mission"),
    mission_strategy: z
      .string()
      .describe('Name of the mission strategy (e.g. "simple", "circular", "detailed", "custom")'),
    mission_strategy_description: z
      .string()
      .describe(
        "Full operational briefing for the planner: intent, framing rule, viewpoints, altitude rule and " +
          "constraints, ending with the MISSION PARAMETERS block verbatim and last. The planner is a geometry " +
          "executor with no knowledge of inspection strategies: anything omitted here is a rule it will invent.",
      ),
    targets_length: z.number().describe("Number of targets to inspect; must equal targets.length"),
    targets: z.array(TargetSchema).describe("List of elements to inspect"),
    selected_devices: z
      .array(DeviceSchema)
      .describe(
        "Only the devices that will actually fly, after applying the online-status, proximity and workload " +
          "filters. NOT the full fleet: every device widens the mission bounding box and can get the plan rejected.",
      ),
  }),
  async execute(input, ctx) {
    "use workflow";

    if (input.targets_length !== input.targets.length) {
      throw new Error(
        `REJECTED. targets_length (${input.targets_length}) does not match the number of targets provided ` +
          `(${input.targets.length}). Re-check the targets you gathered from get_registered_objects and resubmit ` +
          `with a consistent count.`,
      );
    }

    const briefing = await resolveBriefing(input.targets, input.selected_devices);
    return await ctx.agent("planner", { message: formatBriefing(input, briefing) });
  },
});
