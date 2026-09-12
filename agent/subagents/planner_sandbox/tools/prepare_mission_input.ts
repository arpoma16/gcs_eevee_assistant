import { defineTool } from "eve/tools";
import { z } from "zod";

const GCS_API_URL = process.env.MUAV_API_URL ?? "http://localhost:4000/api";

const Identifier = z.union([z.string(), z.number()]);

type XYZ = { x: number; y: number; z: number };

type Element = {
  id: string | number;
  name: string;
  type: string | null;
  position: XYZ;
  description: string | null;
  groupdescription: string | null;
};

type Briefing = {
  global_origin: { lat: number; lng: number; alt: number };
  devices: { id: number; name: string; category: string; location: XYZ }[];
  targets: Element[];
  obstacles: Element[];
  boundaries: unknown;
};

const placeable = ({ id, name, type, position }: Element) => ({ id, name, type, position });

/**
 * One entry per element TYPE, not per element: the catalog stores physical
 * characteristics on the group, so sixteen turbines share one description.
 * This is the only file the model reads, and it deliberately carries no
 * coordinates — there is nothing here it could corrupt.
 */
function elementTypes(elements: Element[]) {
  const byType = new Map<string, { type: string; descriptions: Set<string>; elements: string[] }>();

  for (const element of elements) {
    const type = element.type ?? "unknown";
    const entry = byType.get(type) ?? { type, descriptions: new Set<string>(), elements: [] };
    const description = element.description ?? element.groupdescription;
    if (description) entry.descriptions.add(description);
    entry.elements.push(element.name);
    byType.set(type, entry);
  }

  return [...byType.values()].map(({ type, descriptions, elements: names }) => ({
    type,
    descriptions: [...descriptions],
    elements: names,
    element_count: names.length,
  }));
}

export default defineTool({
  description:
    "Resolve the mission briefing and lay it out as files in /workspace/data, ready for the pipeline. " +
    "Call this FIRST, before anything else. Pass the target and device identifiers exactly as they " +
    "appear in your briefing message. Positions, ids and boundaries are written straight to disk and " +
    "never enter your context; the only file you need to read is element_types.json, which carries " +
    "each element TYPE and its description with no coordinates.",
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

    // Devices carry their XYZ under `location`; the pipeline reads `position`
    // for every placeable thing, so normalize it here once.
    const devices = briefing.devices.map(({ location, ...device }) => ({ ...device, position: location }));
    const types = elementTypes([...briefing.targets, ...briefing.obstacles]);

    const files: Record<string, unknown> = {
      "data/origin.json": { global_origin: briefing.global_origin, boundaries: briefing.boundaries },
      "data/devices.json": devices,
      "data/targets.json": briefing.targets.map(placeable),
      "data/obstacles.json": briefing.obstacles.map(placeable),
      "data/element_types.json": types,
    };

    await Promise.all(
      Object.entries(files).map(([path, content]) =>
        sandbox.writeTextFile({ path, content: JSON.stringify(content, null, 2) }),
      ),
    );

    // Only a receipt: the geometry stays in the files.
    return {
      written: Object.keys(files).map((path) => `/workspace/${path}`),
      read_this_one: "/workspace/data/element_types.json",
      global_origin: briefing.global_origin,
      target_count: briefing.targets.length,
      obstacle_count: briefing.obstacles.length,
      drone_names: devices.map((device) => device.name),
      types: types.map(({ type, element_count }) => ({ type, element_count })),
    };
  },
});
