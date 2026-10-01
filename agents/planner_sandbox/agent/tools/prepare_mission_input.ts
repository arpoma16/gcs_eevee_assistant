import { defineTool } from "eve/tools";
import { z } from "zod";

import { type CatalogGeometry, slugify, synthesizeModel } from "../lib/insem_model";

const GCS_API_URL = process.env.MUAV_API_URL ?? "http://localhost:4000/api";

const Identifier = z.union([z.string(), z.number()]);

type XYZ = { x: number; y: number; z: number };

type Element = {
  id: string | number;
  name: string;
  type: string | null;
  position: XYZ;
  azimFront?: number | null;
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

// Obstacles are avoided with the catalog's simple geometry, never their model:
// position and azimFront (which orients a rectangle) are all they need.
const placeable = ({ id, name, type, position, azimFront }: Element) => ({
  id,
  name,
  type,
  position,
  azimFront: azimFront ?? 0,
});

type CatalogType = {
  id: number;
  name: string;
  definitionYaml?: string | null;
  attributes?: { geometry?: unknown } | null;
  description?: string | null;
};

/** The GCS catalog is the source of truth for a type's geometry, keyed by the same name the briefing carries. */
async function fetchCatalogTypes(): Promise<Map<string, CatalogType>> {
  const response = await fetch(`${GCS_API_URL}/markers/types`);
  if (!response.ok) {
    throw new Error(`Element type catalog request failed (HTTP ${response.status})`);
  }
  const catalog = (await response.json()) as CatalogType[];
  return new Map(catalog.map((entry) => [entry.name, entry]));
}

/**
 * One entry per element TYPE, not per element: the catalog stores physical
 * characteristics on the type, so sixteen turbines share one geometry.
 * Only the types present in the mission are kept. This is the only file the
 * model reads, and it deliberately carries no coordinates — there is nothing
 * here it could corrupt.
 */
function elementTypes(
  elements: Element[],
  catalog: Map<string, CatalogType>,
  models: Map<string, { path: string; source: "gcs" | "generated" }>,
) {
  const byType = new Map<string, { type: string; descriptions: Set<string>; elements: string[] }>();

  for (const element of elements) {
    const type = element.type ?? "unknown";
    const entry = byType.get(type) ?? { type, descriptions: new Set<string>(), elements: [] };
    const description = element.description ?? element.groupdescription;
    if (description) entry.descriptions.add(description);
    entry.elements.push(element.name);
    byType.set(type, entry);
  }

  // Same database as the briefing, so this should not happen; if it does,
  // stop rather than let the model invent dimensions for the type.
  const missing = [...byType.keys()].filter((type) => !catalog.has(type));
  if (missing.length > 0) {
    throw new Error(`Types missing from the GCS catalog (GET /markers/types): ${missing.join(", ")}`);
  }

  return [...byType.values()].map(({ type, descriptions, elements: names }) => ({
    type,
    model_file: models.get(type)?.path ?? null,
    model_source: models.get(type)?.source ?? null,
    geometry: catalog.get(type)?.attributes?.geometry ?? null,
    description: catalog.get(type)?.description ?? null,
    elements: names,
    element_count: names.length,
  }));
}

/**
 * One characterised INSEM model per TARGET type, written to data/models/<slug>.insem.yaml. Obstacle-only
 * types get none: an obstacle is avoided with the catalog's simple geometry, never with its model.
 *
 *   - `definitionYaml` in the catalog → downloaded verbatim (anchors and merge keys survive).
 *   - no definition, or the download failed → a minimal model synthesized from the catalog geometry
 *     (lib/insem_model.ts), so every target type goes through the same engine in the sandbox.
 *
 * Only a type with neither a definition nor a usable geometry ends up without a model; that is reported,
 * not thrown, and the sandbox's describe.py names it.
 */
async function resolveModels(
  targetTypes: Set<string>,
  catalog: Map<string, CatalogType>,
  write: (path: string, content: string) => PromiseLike<unknown>,
) {
  const files = new Map<string, { path: string; source: "gcs" | "generated" }>();
  const notes: { type: string; note: string }[] = [];

  await Promise.all(
    [...targetTypes].map(async (type) => {
      const entry = catalog.get(type);
      const path = `data/models/${slugify(type)}.insem.yaml`;
      if (entry?.definitionYaml) {
        try {
          const response = await fetch(`${GCS_API_URL}/markers/types/${entry.id}/definition`);
          if (!response.ok) throw new Error(`HTTP ${response.status}`);
          await write(path, await response.text());
          files.set(type, { path, source: "gcs" });
          return;
        } catch (error) {
          notes.push({ type, note: `definition download failed (${String(error)}); using a generated model` });
        }
      }
      const synthesized = synthesizeModel(type, entry?.attributes?.geometry as CatalogGeometry | undefined);
      if ("error" in synthesized) {
        notes.push({ type, note: `no model: ${synthesized.error}` });
        return;
      }
      await write(path, synthesized.yaml);
      files.set(type, { path, source: "generated" });
    }),
  );

  return { files, notes };
}

export default defineTool({
  description:
    "Resolve the mission briefing and lay it out as files in /workspace/data, ready for the pipeline. " +
    "Call this FIRST, before anything else. Pass the target and device identifiers exactly as they " +
    "appear in your briefing message. Positions, ids and boundaries are written straight to disk and " +
    "never enter your context; the only file you need to read is element_types.json, which carries " +
    "each element TYPE with its catalog geometry, description and model_file, and no coordinates. " +
    "Every TARGET type gets an INSEM model under /workspace/data/models/: the GCS definition when the " +
    "catalog has one, otherwise a minimal one generated from the catalog geometry (model_source says " +
    "which). Read models through `python3 tools/describe.py`, not by opening the YAML.",
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
    const elements = [...briefing.targets, ...briefing.obstacles];
    const catalog = await fetchCatalogTypes();
    const models = await resolveModels(
      new Set(briefing.targets.map((target) => target.type ?? "unknown")),
      catalog,
      (path, content) => sandbox.writeTextFile({ path, content }),
    );
    const types = elementTypes(elements, catalog, models.files);

    const files: Record<string, unknown> = {
      "data/origin.json": { global_origin: briefing.global_origin, boundaries: briefing.boundaries },
      "data/devices.json": devices,
      "data/targets.json": briefing.targets,
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
      types: types.map(({ type, element_count, model_file, model_source }) => ({
        type,
        element_count,
        model_file,
        model_source,
      })),
      model_notes: models.notes,
    };
  },
});
