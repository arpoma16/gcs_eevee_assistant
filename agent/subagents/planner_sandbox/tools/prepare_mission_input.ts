import { defineTool } from "eve/tools";
import { z } from "zod";

const GCS_API_URL = process.env.MUAV_API_URL ?? "http://localhost:4000/api";

const Identifier = z.union([z.string(), z.number()]);

type XYZ = { x: number; y: number; z: number };

type Briefing = {
  global_origin: { lat: number; lng: number; alt: number };
  devices: { id: number; name: string; category: string; location: XYZ }[];
  targets: { id: string; name: string; position: XYZ; description?: string }[];
  obstacles: unknown[];
  boundaries: unknown;
};

export default defineTool({
  description:
    "Resolve the mission briefing and write it into the sandbox as /workspace/data/mission_input.json, " +
    "ready for the pipeline. Call this FIRST, before any other step. Pass the target and device " +
    "identifiers exactly as they appear in your briefing message. The full geometry is written " +
    "straight to the file: it never passes through your context, so read it with the pipeline, " +
    "never by retyping it.",
  inputSchema: z.object({
    targets: z
      .array(z.object({ id: Identifier, name: z.string() }))
      .describe("Every inspection target from the briefing's target list"),
    selected_devices: z
      .array(
        z.object({
          id: Identifier,
          name: z.string(),
          category: z.string(),
          battery_level: z.number(),
        }),
      )
      .describe("Every drone from the briefing's device list"),
  }),
  async execute({ targets, selected_devices }, ctx) {
    const response = await fetch(`${GCS_API_URL}/missions/convert/geodetic-to-xyz`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ selected_devices, targets }),
    });

    const body = await response.json();
    if (!response.ok) {
      throw new Error(body?.error ?? `Mission briefing conversion failed (HTTP ${response.status})`);
    }

    const briefing = body as Briefing;
    const sandbox = await ctx.getSandbox();
    await sandbox.writeTextFile({
      path: "data/mission_input.json",
      content: JSON.stringify(
        {
          global_origin: briefing.global_origin,
          // Devices carry their XYZ under `location`; the pipeline reads
          // `position` for every placeable thing, so normalize it here once.
          drones: briefing.devices.map(({ location, ...device }) => ({ ...device, position: location })),
          targets: briefing.targets,
          obstacles: briefing.obstacles,
          boundaries: briefing.boundaries,
        },
        null,
        2,
      ),
    });

    // Only a receipt: the geometry stays in the file.
    return {
      path: "/workspace/data/mission_input.json",
      global_origin: briefing.global_origin,
      target_count: briefing.targets.length,
      drone_count: briefing.devices.length,
      obstacle_count: briefing.obstacles.length,
      target_ids: briefing.targets.map((target) => target.id),
      target_names: briefing.targets.map((target) => target.name),
      drone_names: briefing.devices.map((device) => device.name),
    };
  },
});
