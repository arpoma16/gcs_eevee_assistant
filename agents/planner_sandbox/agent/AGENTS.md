# planner_sandbox (standalone debug mirror)

**This is a copy, not the source of truth.** `agent.ts`, `instructions.md`, `sandbox/` and `tools/` here
are a byte-for-byte copy of `agents/assistant/agent/subagents/planner_sandbox/` (see that directory's own
`AGENTS.md` for the actual architecture, the modelo.yaml integration contract, and everything else about
how this pipeline works). Production traffic never reaches this copy — `request_mission_plan.ts` still
delegates to the real subagent. This copy exists for one reason: running it as its own root agent lets you
open a plain chat session against it directly — no delegation, no background workflow tool, no
`await ctx.agent(...)` — so every pipeline step shows up as an ordinary tool call in `eve dev`'s TUI instead
of being collapsed into the parent's turn. It also sidesteps the currently-open upstream `workflowId`
mismatch (`docs/issue2.md`) entirely, since there's no cross-app background-workflow dispatch involved.

## Keeping it in sync

**Nothing automated keeps these two copies in sync.** Whichever one you're actually iterating on, port
the change to the other by hand before you consider the work done — check both directories' `git diff`
before committing. If this copy is still useful once the modelo.yaml work (see the real subagent's
`AGENTS.md`) settles down, consider whether it's worth turning into something less manual (a symlinked
`sandbox/`+`tools/`, a shared package); until then, a plain copy is the least surprising option and the
one that was asked for.

## Running it

```bash
source "$NVM_DIR/nvm.sh" && nvm use && npm run dev:planner_sandbox   # :2002, --tools full --logs sandbox
```

Needs the same `.env` as every other agent app root here (already symlinked: `agents/planner_sandbox/.env`
→ `../../.env`). Talk to it either with the eve TUI that `dev:planner_sandbox` opens, or the test client —
one more terminal, same pairing pattern as `dev`/`dev:assistant`:

```bash
npm run dev:client:planner_sandbox   # from repo root, or: cd client && npm run dev:planner_sandbox
```

It proxies to `:2002` with `VITE_EVE_AGENT` unset, same shape as `assistant`'s default `dev` pairing (this
agent has no name prefix in its own route, `/eve/v1/*` either way) — see the client pairing table in the
root `AGENTS.md`.

Since there's no `request_mission_plan` translating a natural-language ask into target/device identifiers
here, the fastest way to drive a mission is to open the session and call `prepare_mission_input` yourself
with target/device ids you already know, then follow `instructions.md`'s own sequence turn by turn.

## What this copy does NOT have

No `connections/` — both tools (`prepare_mission_input.ts`, `validate_and_persist.ts`) hit the GCS with a
plain `fetch` against `MUAV_API_URL`, not an eve connection, so none was needed even in the original. No
`subagents/` of its own, no `hooks/`, no `schedules/` — this agent only ever does one thing.
