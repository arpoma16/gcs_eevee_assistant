import { defineTool } from "eve/tools";
import { z } from "zod";

const GCS_API_URL = process.env.MUAV_API_URL ?? "http://localhost:4000/api";

async function post(path: string, body: unknown) {
  const response = await fetch(`${GCS_API_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload?.error ?? `${path} failed (HTTP ${response.status})`);
  }
  return payload;
}

export default defineTool({
  description:
    "The validation gate. Reads the mission the pipeline built and checks it against the GCS 3D " +
    "obstacle database: collisions with obstacles, collisions between UAVs, route violations and " +
    "mission integrity. When the mission is valid — or when this is the final attempt — the plan is " +
    "persisted and its id returned. Call it after build_mission.py, and again after every repair. " +
    "The mission never passes through your context: it is read straight from /workspace/data.",
  inputSchema: z.object({
    is_final_attempt: z
      .boolean()
      .optional()
      .describe(
        "Set to true ONLY on the last allowed refinement iteration. The still-invalid mission is " +
          "then persisted as-is so the operator has something to look at, instead of losing the work.",
      ),
  }),
  async execute({ is_final_attempt = false }, ctx) {
    const sandbox = await ctx.getSandbox();

    const readJson = async (path: string, producedBy: string) => {
      const raw = await sandbox.readTextFile({ path });
      if (raw === null) {
        throw new Error(`/workspace/${path} does not exist yet — run ${producedBy} before calling the gate.`);
      }
      return JSON.parse(raw);
    };

    const [mission, collision_objects, missionInput] = await Promise.all([
      readJson("data/mission.json", "pipeline/build_mission.py"),
      readJson("data/collision_objects.json", "pipeline/build_collision_objects.py"),
      readJson("data/mission_input.json", "prepare_mission_input"),
    ]);

    const target_ids = missionInput.targets.map((t: { id: string | number }) => String(t.id));

    const result = await post("/missions/validate", { mission, collision_objects, target_ids });

    if (!result.valid && !is_final_attempt) {
      return {
        valid: false,
        totalCollisions: result.totalCollisions,
        report: `MISSION INVALID. See details below:\n${result.report}`,
      };
    }

    // Persist: the plan is stored geodetic, so it goes back through the GCS converter.
    const geodetic = await post("/missions/convert/xyz-to-geodetic", { version: "3", ...mission });
    const saved = await post("/missions/plans", { missionData: geodetic });

    return {
      valid: result.valid,
      totalCollisions: result.totalCollisions,
      missionPlanId: saved.id,
      report: result.valid
        ? `MISSION valid, persisted with planID ${saved.id}\n${result.report}`
        : `MISSION INVALID after exhausting refinement iterations. Saved as-is with planID ${saved.id}.\n${result.report}`,
    };
  },
});
