import { defineTool } from "eve/tools";
import { z } from "zod";

import { GATE_COMMAND } from "../lib/gate";

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

type Finding = { code: string };
type Validation = { valid: boolean; total_findings: number; findings: Finding[] };

const COLLISION_CODES = new Set(["clearance_target", "clearance_other"]);

export default defineTool({
  description:
    "The validation gate. Runs the planner's own validator — a protected copy of tools/validate.py, not " +
    "the one in /workspace — over /workspace/data/mission.json: v3 structure, coverage of every target, " +
    "depends_on, altitude floor and EU 2019/947 ceiling, geofence, and collisions (full model of the " +
    "targets being inspected, simple catalog geometry for everything else). When the mission is valid — " +
    "or when this is the final attempt — the plan is persisted and its id returned. Call it after " +
    "tools/build_mission.py, and again after every repair. The mission never passes through your context.",
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

    const missionRaw = await sandbox.readTextFile({ path: "data/mission.json" });
    if (missionRaw === null) {
      throw new Error("/workspace/data/mission.json does not exist yet — run tools/build_mission.py before the gate.");
    }

    // Exit 0 = valid, 1 = invalid; anything else means the validator itself could not run.
    const run = await sandbox.run({ command: GATE_COMMAND });
    if (run.exitCode !== 0 && run.exitCode !== 1) {
      throw new Error(`The gate's validator failed to run (exit ${run.exitCode}): ${run.stderr || run.stdout}`);
    }
    const validationRaw = await sandbox.readTextFile({ path: "data/validation.json" });
    if (validationRaw === null) {
      throw new Error(`The gate's validator wrote no report: ${run.stderr || run.stdout}`);
    }
    const validation = JSON.parse(validationRaw) as Validation;
    const totalCollisions = validation.findings.filter((f) => COLLISION_CODES.has(f.code)).length;
    const report = run.stdout.trim();

    if (!validation.valid && !is_final_attempt) {
      return {
        valid: false,
        totalCollisions,
        totalFindings: validation.total_findings,
        report: `MISSION INVALID. Details in /workspace/data/validation.json:\n${report}`,
      };
    }

    // Persist: the plan is stored geodetic, so it goes back through the GCS converter (needs global_origin).
    const mission = JSON.parse(missionRaw);
    const geodetic = await post("/missions/convert/xyz-to-geodetic", mission);
    const saved = await post("/missions/plans", { missionData: geodetic });

    return {
      valid: validation.valid,
      totalCollisions,
      totalFindings: validation.total_findings,
      missionPlanId: saved.id,
      report: validation.valid
        ? `MISSION valid, persisted with planID ${saved.id}\n${report}`
        : `MISSION INVALID after exhausting refinement iterations. Saved as-is with planID ${saved.id}.\n${report}`,
    };
  },
});
