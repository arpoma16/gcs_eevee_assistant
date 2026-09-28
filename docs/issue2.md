 https://github.com/vercel/eve/issues/3628
Re-opening — thanks for the fast turnaround on #3629, but the fix is incomplete: the same `agents/<name>/` workspace layout still reproduces this exact error, unchanged.

Reproduces identically on `0.64.1` and `0.65.0` (checked both).

## Reproduction on 0.64.1

Same app as before (`agents/<name>/agent/` layout, no `package.json` at the agent app root), `request_mission_plan` (a `defineWorkflowTool({ execution: "background" })`), invoked with `eve dev --agent assistant` from the workspace root — the way `eve dev`'s own `--agent` flag is documented to be used from a workspace. Every dispatch still fails with:

```
Tool "request_mission_plan" is not registered as a workflow in this deployment
(workflow//./agents/assistant/agent/tools/request_mission_plan//execute).
The tool was renamed or removed after this run started.
```

## What's actually happening (instrumented `readRegisteredWorkflow`)

```
[DEBUG] requested=  "workflow//./agents/assistant/agent/tools/request_mission_plan//execute"
[DEBUG] registered= [..., "workflow//./agent/tools/request_mission_plan//execute"]
```

The **registration side is correct** now — `workflow//./agent/tools/request_mission_plan//execute` is exactly what's in `__private_workflows`, thanks to #3629's `appRoot` threading through `bundleAuthoredModuleMapForGeneration` / `development-generation.ts`. But the **dispatch side still asks for the old, over-prefixed id**. Registration and dispatch disagree the same way they did before the fix — just for a different reason now.

## Where the remaining half lives

#3629 touched `authored-module-loader.ts`, `authored-runtime-modules.ts`, `internal/nitro/development-generation.ts`, and `internal/application/compiled-artifacts.ts` — all on the "generation" path that builds the runtime workflow bundle (`bundleAuthoredModuleMapForGeneration`).

It didn't touch `compiler/load-binding-namespace.ts` → `loadAuthoredModuleNamespace` → `bundleAuthoredModuleCode`. That's a **separate** compile pass used to load and inspect each tool module during agent normalization (`compiler/normalize-tool.ts:104`, `readWorkflowFunctionId(entry.definition.execute)` reads `.workflowId` stamped on the function by *this* pass). `bundleAuthoredModuleCode` still computes its root with the original `resolveAuthoredPackageRoot(modulePath)` — walking up from the individual file looking for the nearest ancestor `package.json` — which lands on the workspace root for the same reason as before: an `agents/<name>/` member deliberately has none of its own.

`definition.workflowId` (read by `harness/tools.ts::requireBackgroundWorkflowId`, and what ends up as `task.workflowId` at dispatch) comes from this second, still-unfixed pass — so it's still the workspace-root-prefixed id, while the runtime bundle now correctly registers the app-root-relative one.

## Why this didn't show up in #3629's tests

`bundleAuthoredModuleCode` doesn't currently receive an app-identity hint at all — it's only given the individual file's absolute path, so there's no `appRoot` to thread in without a signature change. Its existing "nearest ancestor `package.json`" behavior is also legitimately correct for its *other* use there (the package-boundary/tsconfig plugins want the workspace root for dependency resolution in a workspace) — so this isn't a one-line fix like #3629 was; it needs a new, explicit app-root parameter that only the workflow-id stamping cares about, threaded from wherever `createCompiledBindingNamespaceLoader` is instantiated (that's where the compiled manifest's `appRoot` is already in scope).

Happy to open a PR for this half too if useful — I have the exact call chain mapped out, just wanted to confirm and report before assuming #3629 was the whole fix.
