// Runs prepare_mission_input's execute() outside eve, with a fake sandbox that
// writes to a local directory. Usage (from the repo root):
//   npx tsx <this file> [outDir]
import { mkdir, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import tool from "../agents/planner_sandbox/agent/tools/prepare_mission_input.ts";

const outDir = process.argv[2] ?? join(import.meta.dirname, "workspace");

const ctx = {
  getSandbox: async () => ({
    writeTextFile: async ({ path, content }: { path: string; content: string }) => {
      const target = join(outDir, path);
      await mkdir(dirname(target), { recursive: true });
      await writeFile(target, content);
    },
  }),
};

// Same input as agents/planner_sandbox/agent/input_msg.md
const input = {
  targets: [{ id: 3, name: "A3" }],
  selected_devices: [{ id: 2, name: "uav_1", category: "px4_ros2", battery_level: 100 }],
};

const receipt = await (tool as any).execute(input, ctx);
console.log(JSON.stringify(receipt, null, 2));
console.log(`\nfiles in ${outDir}/data`);
