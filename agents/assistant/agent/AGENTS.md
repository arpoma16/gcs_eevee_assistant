# assistant agent

Operator-facing orchestrator, tier `medium` (`agent.ts`). It routes, queries telemetry and delegates —
it does not do the heavy reasoning itself. That lives in its two `subagents/`, both tier `high`.

## Two planners, not one

| subagent | strategy |
| --- | --- |
| `subagents/planner/` | reasons the geometry directly, no sandbox |
| `subagents/planner_sandbox/` | delegates geometry to a deterministic Python pipeline running in its own sandbox — see its own `AGENTS.md` |

Which one gets called is a mission-shape decision made in `tools/request_mission_plan.ts`, not a model
preference — read that file before assuming either planner is dead code.

## `request_mission_plan.ts` is a background workflow tool

`defineWorkflowTool({ execution: "background" })` that runs `await ctx.agent(planner_sandbox, ...)` (or
`planner`) inside a `"use workflow"` function. Two things to know before touching it:

- **Cross-realm data after `await`.** Anything read from `input` and used after the `await` on the
  subagent call is rehydrated by eve's durable-execution runtime and fails identity checks like
  `Object.getPrototypeOf(x) === Object.prototype` (structurally fine, `===` on the prototype is not).
  `@toon-format/toon`'s `encode()` silently emits `null` for such values instead of throwing — see
  `toPlainObject()` in this file and the root `AGENTS.md` ("`"use workflow"` gotcha" section) for the
  full mechanism before adding another `encode()` call on post-`await` data.
- **Known upstream bug, currently open on the pinned eve version (`0.64.1`, see root `package.json`).**
  Background workflow tools under this repo's required `agents/<name>/` layout (no `package.json` at the
  app root — see root `AGENTS.md`) can get a `workflowId` mismatch between registration and dispatch,
  failing with `Tool "request_mission_plan" is not registered as a workflow in this deployment`. Full
  root-cause trace (two separate compile passes disagreeing on the app root) is in `docs/issue2.md`
  (eve GH #3628/#3629), reproduced on both `0.64.1` and `0.65.0`. **Read that file first** if
  `request_mission_plan` dispatch fails this way — do not re-derive the call chain from scratch.

## This agent's own sandbox

`sandbox/sandbox.ts` opens a `DefaultSandbox` seeded from `sandbox/workspace/{tools,pipeline,data}`.
This is **the assistant's own sandbox** — a different one from `planner_sandbox`'s nested sandbox at
`subagents/planner_sandbox/sandbox/`. Each agent identity gets its own `/workspace`; don't assume a file
written by one is visible to the other.

## Connections

`connections/multiuav-gcs.ts` is the GCS MCP tool surface, with flight-critical tools gated behind
`user-approval` (root `AGENTS.md` table). Approval prompts for this agent's own session render in
`client/src/Chat.tsx` (main thread); for a subagent's session they render in `client/src/SubagentPanel.tsx`
— see `subagents/planner_sandbox/AGENTS.md` for how that attach mechanism works, since today it's the
only subagent wired into the client UI that way.
