// Offline tests for planner_sandbox's TypeScript side: the model synthesizer and the validation gate.
// No GCS and no eve: the sandbox is faked over a temporary /workspace and `fetch` is mocked.
//
//   npx tsx --test test/planner.test.mts
import assert from "node:assert/strict";
import { execFileSync, execSync } from "node:child_process";
import { chmodSync, cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { after, before, describe, test } from "node:test";

import { synthesizeModel } from "../agents/planner_sandbox/agent/lib/insem_model.ts";
import validateAndPersist from "../agents/planner_sandbox/agent/tools/validate_and_persist.ts";

const REPO = join(import.meta.dirname, "..");
const SEED = join(REPO, "agents/planner_sandbox/agent/sandbox/workspace");
const TEST_DATA = join(REPO, "test/workspace/data");
const python = (cwd: string, ...args: string[]) =>
  execFileSync("python3", args, { cwd, encoding: "utf8", env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1" } });

/** A /workspace copy (seed + test data) under a fresh temp dir. */
function workspace(root: string) {
  const ws = join(root, "workspace");
  cpSync(SEED, ws, { recursive: true, filter: (src) => !src.includes("__pycache__") });
  cpSync(TEST_DATA, join(ws, "data"), { recursive: true });
  return ws;
}

describe("synthesizeModel", () => {
  test("circle → cylinder with an orbit surface", () => {
    const out = synthesizeModel("Wind Turbine", { geometry_type: "circle", dimensions: { radius: 28, height: 108 } });
    assert.ok("yaml" in out);
    assert.match(out.yaml, /type: cylinder, radius: 28, length: 108/);
    assert.match(out.yaml, /pattern: orbit/);
  });

  test("rectangle → box with five face_grid surfaces", () => {
    const out = synthesizeModel("Building", {
      geometry_type: "rectangle",
      dimensions: { width: 20, length: 40, height: 30 },
    });
    assert.ok("yaml" in out);
    assert.match(out.yaml, /size: \[20, 40, 30\], pose: \{xyz: \[0, 0, 15\]\}/);
    assert.equal(out.yaml.match(/pattern: face_grid/g)?.length, 5);
  });

  test("incomplete geometry is an error, not a model", () => {
    assert.ok("error" in synthesizeModel("Tree", { geometry_type: "circle", dimensions: { radius: 3 } }));
    assert.ok("error" in synthesizeModel("Wall", { geometry_type: "rectangle", dimensions: { width: 3, height: 2 } }));
    assert.ok("error" in synthesizeModel("Blob", { geometry_type: "polygon", dimensions: { height: 2 } }));
    assert.ok("error" in synthesizeModel("None", null));
  });

  test("generated models load and describe in the sandbox library", (t) => {
    const root = mkdtempSync(join(tmpdir(), "planner-synth-"));
    t.after(() => rmSync(root, { recursive: true, force: true }));
    const ws = workspace(root);
    const turbine = synthesizeModel("Wind Turbine", { geometry_type: "circle", dimensions: { radius: 28, height: 108 } });
    const building = synthesizeModel("Building", {
      geometry_type: "rectangle",
      dimensions: { width: 20, length: 40, height: 30 },
    });
    assert.ok("yaml" in turbine && "yaml" in building);
    writeFileSync(join(ws, "data/models/wind_turbine.insem.yaml"), turbine.yaml);
    writeFileSync(join(ws, "data/models/building.insem.yaml"), building.yaml);
    const targets = JSON.parse(readFileSync(join(ws, "data/targets.json"), "utf8"));
    targets.push({ id: 9, name: "B1", type: "Building", position: { x: -900, y: 150, z: 0 }, azimFront: 30 });
    writeFileSync(join(ws, "data/targets.json"), JSON.stringify(targets));
    writeFileSync(
      join(ws, "data/element_types.json"),
      JSON.stringify([
        { type: "Wind Turbine", model_file: "data/models/wind_turbine.insem.yaml", model_source: "generated",
          geometry: { geometry_type: "circle", dimensions: { radius: 28, height: 108 } } },
        { type: "Building", model_file: "data/models/building.insem.yaml", model_source: "generated",
          geometry: { geometry_type: "rectangle", dimensions: { width: 20, length: 40, height: 30 } } },
      ]),
    );
    const [b1] = JSON.parse(python(ws, "tools/describe.py", "--target", "B1", "--json"));
    assert.equal(b1.azim_front, 30);
    assert.deepEqual(b1.parts.body.surfaces.map((s: { id: string }) => s.id), ["front", "back", "right", "left", "top"]);
    const [a3] = JSON.parse(python(ws, "tools/describe.py", "--target", "A3", "--json"));
    assert.deepEqual(a3.parts.body.surfaces.map((s: { pattern: string }) => s.pattern), ["orbit"]);
    assert.ok("rotor_azimuth_deg" in a3.ignored_state, "a generated model has no state to apply");
  });
});

describe("validate_and_persist (gate)", () => {
  let root: string;
  let gate: string;
  const realFetch = globalThis.fetch;
  let calls: { path: string; body: any }[] = [];

  before(() => {
    root = mkdtempSync(join(tmpdir(), "planner-gate-"));
    // the gate's protected copy, as sandbox.ts `prepare` builds it: lib/ + tools/validate.py, read-only
    gate = join(root, "gate");
    mkdirSync(join(gate, "tools"), { recursive: true });
    cpSync(join(SEED, "lib"), join(gate, "lib"), { recursive: true, filter: (src) => !src.includes("__pycache__") });
    cpSync(join(SEED, "tools/validate.py"), join(gate, "tools/validate.py"));
    execSync(`chmod -R a-w ${gate}`);
    globalThis.fetch = (async (url: string, init: RequestInit) => {
      const path = url.replace(/^.*\/api/, "");
      const body = JSON.parse(String(init.body));
      calls.push({ path, body });
      return new Response(JSON.stringify(path === "/missions/plans" ? { id: 42 } : body), { status: 200 });
    }) as typeof fetch;
  });

  after(() => {
    globalThis.fetch = realFetch;
    execSync(`chmod -R u+w ${root}`);
    rmSync(root, { recursive: true, force: true });
  });

  /** Builds a mission in a fresh workspace and returns a fake sandbox over it. */
  function sandboxFor(name: string, mutate?: (data: string) => void) {
    const ws = workspace(join(root, name));
    mutate?.(join(ws, "data"));
    mkdirSync(join(ws, "scripts"));
    cpSync(join(ws, "examples/inspect_example.py"), join(ws, "scripts/inspection.py"));
    python(ws, "scripts/inspection.py");
    python(ws, "tools/assign.py");
    python(ws, "tools/build_mission.py", "--speed", "5");
    const sandbox = {
      readTextFile: async ({ path }: { path: string }) => {
        const file = join(ws, path);
        return existsSync(file) ? readFileSync(file, "utf8") : null;
      },
      run: async ({ command }: { command: string }) => {
        const local = command.replace("/opt/planner_gate", gate).replace("/workspace/data", join(ws, "data"));
        try {
          return { exitCode: 0, stdout: execSync(local, { encoding: "utf8" }), stderr: "" };
        } catch (error: any) {
          return { exitCode: error.status, stdout: String(error.stdout), stderr: String(error.stderr) };
        }
      },
    };
    return { ws, ctx: { getSandbox: async () => sandbox } };
  }

  const execute = (input: { is_final_attempt?: boolean }, ctx: unknown) =>
    (validateAndPersist as any).execute(input, ctx) as Promise<Record<string, any>>;

  test("a valid mission is converted and persisted", async () => {
    calls = [];
    const { ctx } = sandboxFor("valid");
    const out = await execute({}, ctx);
    assert.equal(out.valid, true);
    assert.equal(out.missionPlanId, 42);
    assert.match(out.report, /planID 42/);
    assert.deepEqual(calls.map((c) => c.path), ["/missions/convert/xyz-to-geodetic", "/missions/plans"]);
    const sent = calls[0].body;
    assert.equal(sent.version, "4");
    assert.ok(sent.global_origin);
    assert.equal(sent.tasks[0].task_id, "T1");
    assert.deepEqual(sent.tasks[0].depends_on, []);
    assert.ok(sent.tasks[0].wp.some((w: { type: string }) => w.type === "transit"));
  });

  test("an invalid mission never reaches the GCS, unless it is the final attempt", async () => {
    const { ctx } = sandboxFor("invalid", (data) => {
      const devices = JSON.parse(readFileSync(join(data, "devices.json"), "utf8"));
      devices[0].position = { x: -996, y: -140, z: 0 };   // base inside A2's safety zone
      writeFileSync(join(data, "devices.json"), JSON.stringify(devices));
    });
    calls = [];
    const out = await execute({}, ctx);
    assert.equal(out.valid, false);
    assert.ok(out.totalCollisions > 0);
    assert.equal(out.missionPlanId, undefined);
    assert.equal(calls.length, 0);

    const last = await execute({ is_final_attempt: true }, ctx);
    assert.equal(last.valid, false);
    assert.equal(last.missionPlanId, 42);
    assert.match(last.report, /Saved as-is with planID 42/);
  });

  test("the gate ignores edits to /workspace/tools/validate.py", async () => {
    const { ws, ctx } = sandboxFor("tampered", (data) => {
      const devices = JSON.parse(readFileSync(join(data, "devices.json"), "utf8"));
      devices[0].position = { x: -996, y: -140, z: 0 };
      writeFileSync(join(data, "devices.json"), JSON.stringify(devices));
    });
    chmodSync(join(ws, "tools/validate.py"), 0o644);
    writeFileSync(join(ws, "tools/validate.py"), "import sys; print('MISIÓN VÁLIDA'); sys.exit(0)\n");
    const out = await execute({}, ctx);
    assert.equal(out.valid, false);
  });

  test("a mission that was never built is an error", async () => {
    const ws = workspace(join(root, "empty"));
    const ctx = { getSandbox: async () => ({ readTextFile: async () => null, run: async () => ({}) }) };
    await assert.rejects(execute({}, ctx), /mission\.json does not exist yet/);
    assert.ok(existsSync(ws));
  });
});
