 https://github.com/vercel/eve/issues/3628
# defineWorkflowTool background dispatch resolves the wrong `workflowId` when the app lives under a workspace's `agents/<name>/` layout

## Summary

A `defineWorkflowTool` with `execution: "background"` fails on every dispatch with:

```
Tool "<name>" is not registered as a workflow in this deployment (<workflowId>).
The tool was renamed or removed after this run started.
```

...even on a freshly compiled app that has never renamed or removed anything. This reproduces consistently when the agent app lives under a workspace's `agents/<name>/agent/` layout (as documented in the "eve workspace" pattern — multiple `agents/<name>/` app roots sharing one repo).

## Environment

- `eve` 0.63.0
- Node v24.21.0
- Linux x86_64, Ubuntu 24.04
- Local dev only (`eve dev`, and `vercel dev --local` via a root `vercel.ts`); not tried on a Vercel deployment
- App layout: workspace root with `agents/assistant/` and `agents/monitor/` as sibling app roots, each with its own `agent/` directory, `#shared/*` subpath import declared in the root `package.json`

## Reproduction

The failing tool, `agents/assistant/agent/tools/request_mission_plan.ts`:

```ts
export default defineWorkflowTool({
  execution: "background",
  inputSchema: z.object({ /* ... */ }),
  async execute(input, ctx) {
    "use workflow";
    // ...
    return await ctx.agent("planner", { message: /* ... */ });
  },
});
```

Reproduced identically in **three** invocation modes:

1. `eve dev --agent assistant` from the workspace root.
2. `eve dev` run with cwd inside `agents/assistant/` directly (ruling out cwd as the variable).
3. `npm run dev:all` → `vercel dev --local` serving every workspace member behind one origin.

Steps: send any message that causes the model to call `request_mission_plan`. The tool call returns a normal background receipt (`{"status":"working","taskId":"..."}`), then the task fails immediately with the error above. A full `.eve` wipe + restart does not change the outcome.

## Root cause (traced in the published source)

- `packages/eve/src/execution/tools/workflow/body.ts` → `resolveWorkflowToolExecute` calls `readRegisteredWorkflow(input.workflowId)` against the global `__private_workflows` map and throws the error above when the lookup misses.
- That map is populated by the Workflow bundle transform in `packages/eve/src/internal/workflow-bundle/workflow-transformer.ts`, keyed by the id `createWorkflowId(idBase, fn.name)` computes (line ~184), where:

  ```ts
  const defaultIdBase = input.moduleSpecifier ?? `./${stripJavaScriptExtension(input.filename)}`;
  ```

- Inspecting the **locally compiled dev-host manifest** (`agents/assistant/.eve/dev-hosts/<id>/workflow/manifest.json`) for this app shows the tool correctly registered as:

  ```
  "workflowId": "workflow//./agent/tools/request_mission_plan//execute"
  ```

  (i.e. `moduleSpecifier` was supplied, relative to the **agent app root**, `agents/assistant/`).

- But the error message at dispatch time names a **different** id:

  ```
  workflow//./agents/assistant/agent/tools/request_mission_plan//execute
  ```

  — the same logical path, but with an extra `agents/assistant/` segment prepended, as if `moduleSpecifier` was *not* passed on this path and `input.filename` fell back to a path relative to the **workspace root** instead of the agent app root.

- `definition.workflowId`, read in `packages/eve/src/harness/tools.ts` (`requireBackgroundWorkflowId`), is what ends up in the dispatched task (via `startWorkflowTask` in `packages/eve/src/execution/tools/workflow/start.ts`, which forwards `task.workflowId` verbatim). That value diverges from what's actually registered in `__private_workflows`.

So there appear to be (at least) two separate compile passes producing a `workflowId` for the same authored source file — one for the local Workflow-World bundle used by the dev host (correct, app-root-relative), one that ends up on the harness-compiled tool definition served to live traffic (wrong, workspace-root-relative). In a single, non-workspace eve app the two roots coincide and the bug never shows; in the documented `agents/<name>/agent/` workspace layout they diverge.

## Expected

Both compile passes should agree on the same `workflowId` for a given authored workflow tool, anchored consistently to the agent app root regardless of whether the app is a workspace member.

## Additional notes

I don't have a minimal standalone reproduction repo yet — this was found and traced in a private project — but the mechanism above should reproduce with any `defineWorkflowTool({ execution: "background" })` placed under `agents/<name>/agent/tools/` in a multi-agent workspace. Happy to put together a minimal repro if useful.
