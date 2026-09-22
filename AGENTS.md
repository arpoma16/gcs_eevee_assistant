# eve Agent App

This project is an **eve workspace**: every directory under `agents/<name>/` that holds agent files and has no `package.json` of its own is a separate root agent, and eve compiles and runs each one. `agents/<name>/` is the app root, `agents/<name>/agent/` is the agent root (eve calls this the nested layout). A child with its own `package.json` stops being a workspace member, so do not add one.

| agent | role | tier | tool surface |
| --- | --- | --- | --- |
| `agents/assistant/` | operator-facing assistant; delegates planning to its `planner` and `planner_sandbox` subagents | `medium` (planners `high`) | full GCS allowlist, flight-critical tools behind `user-approval` |
| `agents/monitor/` | autonomous telemetry watch; wakes on its own clock | `low` | read-only GCS allowlist, `defaultTools: false` (no built-in tools at all) |

Schedules and channels are root-only in eve, which is why the monitor is its own root agent and not a subagent of the assistant.

eve requires **Node.js >= 24** and refuses to start on anything older; `.nvmrc` pins it. Each agent needs a `.env` at its own app root, because eve loads the app root's `.env` and never looks upward. Both are gitignored symlinks to the repo-root `.env`, so recreate them after a fresh clone:

```sh
ln -s ../../.env agents/assistant/.env
ln -s ../../.env agents/monitor/.env
```

For a content-only change to an agent's identity, purpose, tone, or response guidelines, edit its authored instructions at `agents/<name>/agent/instructions.md` (an agent may instead use `instructions.ts` or files under `instructions/`). You do not need to read the framework docs for that. Preserve `agents/<name>/agent/agent.ts` unless the user asks to change the model.

## Run it

Most `eve` commands are agent-specific: from the workspace root pass `--agent <name>`, or omit it and an interactive command opens a picker while a non-interactive one lists the available agents and exits. `build`, `link` and `deploy` are project-level and take no `--agent`.

| command | starts | routes |
| --- | --- | --- |
| `npm run dev` | picker, one agent | `/eve/v1/*` |
| `npm run dev:assistant` | assistant on `:2000` | `/eve/v1/*` |
| `npm run dev:monitor` | monitor on `:2001` | `/eve/v1/*` |
| `npm run dev:all` | every workspace member behind one origin | `/eve/assistant/v1/*`, `/eve/monitor/v1/*` |

Both route shapes are real; which one applies depends on the command that started the process. `dev:all` runs `vercel dev --local` against the root `vercel.ts`, with the CLI version pinned in the script because that mode needs Vercel CLI >= 59.16.0. The Vercel CLI is deliberately **not** a dependency: it is never imported from code, eve does not declare it, and production here is `eve start` behind a proxy.

Internally `dev:all` starts one `eve dev --no-ui` per member with `EVE_PUBLIC_ROUTE_PREFIX` set to that member's mount. A self-hosted reverse proxy has to reproduce exactly that, and must forward both `/eve/` and `/.well-known/workflow/` without rewriting their paths — a proxy limited to `/eve/` lets a session start and then stalls when the workflow callback cannot get back.

`dev:all` is also the only mode that enables the default workspace transport: with it, `defineWorkspaceAgent({ name })` under `agents/<caller>/agent/subagents/` lets one agent call another with no URL and no credentials. Under `eve dev` a peer needs an explicit `transport: { url, auth }`.

`eve info --agent <name>` confirms discovery and prints diagnostics without booting a server — the cheapest check after changing authored files. It does **not** load `.env`.

## Model selection

`shared/models.ts` is the single source of truth: a provider-by-tier table plus the provider cascade and one explicit error when no credential is present. An agent declares the capability it needs, never a model id:

```ts
import { resolveModel } from "#shared/models";
// tiers: "high" (planners), "medium" (assistant), "low" (monitor)
```

`#shared/*` is a subpath import declared in the root `package.json`, so it resolves from every app root. Always resolve the model inside `defineDynamic({ events: { "step.started": ... } })` rather than at module load: commands that evaluate authored modules without `.env` (`eve info`, and the build) would otherwise hit the catalog's throw and fail discovery outright. This is also required by eve — a direct-provider `LanguageModel` object may only be returned from `step.started`, while session and turn scopes accept string model ids only.

Switch provider with `EVE_PROVIDER`, or override one tier's model id with `EVE_MODEL_HIGH`, `EVE_MODEL_MEDIUM` or `EVE_MODEL_LOW`.

Any `google` or `openai` model id (catalog entry or `EVE_MODEL_*` override) must exist in Vercel AI Gateway's own catalog, not just at the provider. Gateway resolves `modelContextWindowTokens` by looking the id up in its catalog; an id the provider serves but Gateway hasn't listed (e.g. a dated OpenAI snapshot like `gpt-5.1-2025-11-13`, or a shorthand Gateway never published like `gpt-5.1`) fails at session start with `MODEL_SELECTION_FAILED: ... did not provide context window metadata`. Verify an id before using it:

```sh
curl -fsSL https://ai-gateway.vercel.sh/v1/models | jq '.data[] | select(.id | startswith("openai/")) | .id'
```

Swap the `startswith` prefix for `"google/"` to check the other provider. Only `llamacpp` is exempt — it's not on Gateway, which is why its `CATALOG` entry sets `contextWindowTokens` explicitly instead (see `shared/models.ts`).

Telemetry providers live in `agents/<name>/agent/instrumentation/`, one file per provider. A flat `instrumentation.ts` is from an older eve and fails service startup.

## Read the docs before writing code

```sh
ls node_modules/eve/docs
```

Start with `docs/README.md`: it maps each task to the page that covers it. Read that page before authoring tools, connections, channels, skills, subagents, schedules, or deployment. In a workspace or local package install, resolve the installed `eve` package location first. If the package docs are missing, use https://eve.dev/docs.

Use a bounded authoring loop:

1. Read the relevant page and inspect only files you will modify or need to imitate.
2. Stop discovery once the file location, imports, and definition shape are clear. Implement the smallest complete behavior the user requested.
3. Run one narrow verification. Expand investigation only when it fails or the request needs project-specific details.

Follow links or inspect public types only when the routed page leaves the task unanswered. Do not recursively glob `node_modules`, enumerate the entire docs tree, or read unrelated scaffold files when the direct path is known. Package-manager links can hide files from recursive glob tools even though direct reads work.

## Prefer an existing integration

When a task names an external product or service, search the registry before implementing its integration. For a generic capability, author a tool instead.

```sh
eve registry search <query> --json
eve registry view <item>
```

Prefer items whose `implementation` is `native`; use Chat SDK adapters when no native channel fits. `registry view` links the item's documentation.

Install without driving interactive prompts:

```sh
eve add <item> --non-interactive
```

Exit code 0 means setup completed, 1 failed, and 2 needs an answer or a prerequisite. On exit 2, run the `next.command` from the final NDJSON event. For a non-secret question, replace its `<JSON value>` answer placeholder with the answer you collected; string values need JSON quotes. Never pass a secret in `--answer`. See `docs/install-integrations.mdx` for setup prerequisites.

## Use eve for Vercel operations

Use eve to link and deploy Vercel projects:

```sh
eve link --non-interactive --project <name-or-id> [--team <team-id-or-slug>]
eve deploy --non-interactive --yes [--project <name-or-id>]
```

A setup may report `eve link` as a prerequisite; run it, then retry the continuation. When a completed setup event has `deploymentRequired: true`, run the `next` command it reports.

## Test client (`client/`)

`client/` is a standalone Vite + React app that exercises the **assistant** agent through `useEveAgent` from `eve/react`. It is not part of any compiled eve app and is not deployed with them — it has its own `package.json` and `node_modules`, and is not a workspace member.

It reaches eve through a same-origin dev proxy (`vite.config.ts`), so no `host` override on `useEveAgent` and no CORS change on `agents/<name>/agent/channels/eve.ts` is needed locally. The `/eve` prefix covers both route shapes, so only the target and the agent name change between modes:

| client command | pairs with (repo root) | proxy target | `VITE_EVE_AGENT` |
| --- | --- | --- | --- |
| `npm run dev` | `npm run dev:assistant` | `:2000` | unset → `/eve/v1/*` |
| `npm run dev:all` | `npm run dev:all` | `:3300` | `assistant` → `/eve/assistant/v1/*` |

`EVE_DEV_URL` overrides the proxy target; `VITE_EVE_AGENT` feeds `useEveAgent({ agent })`, which must never be combined with `host`.

Both `dev:all` scripts pin port **3300** on purpose. Vercel CLI silently moves to the next free port when the requested one is taken, and the client would then proxy to whatever else is listening there — a Vite app on that port answers `index.html` with HTTP 200 to *every* path, so even a health check looks like it passed while the chat 404s. If 3300 is taken, change it in both `package.json` files together. To confirm the proxy really reaches eve, check that the body is JSON, not HTML:

```sh
curl -s localhost:5173/eve/assistant/v1/health   # {"ok":true,"status":"ready",...}
```

**Keep `client/`'s `eve` dependency on the same version as the root.** The client has its own `node_modules`, so it resolves `eve/react` independently, and the route shape it builds is decided by *its* copy: 0.53.x requests `/eve/agents/<name>/eve/v1/*` while 0.63.x requests `/eve/<name>/v1/*`. A mismatch is silent at install and at `tsc -b`, and only shows up as a 404 on the session POST in the browser console.

Running it end to end needs three processes:

```sh
# 1. GCS MCP server — agents/*/agent/connections/multiuav-gcs.ts depend on it
cd ../llm_planner_gcs/mcp_server && npx tsx src/index.ts http

# 2. the agent (one agent on :2000, or `npm run dev:all` for every member)
npm run dev:assistant

# 3. test client on :5173
cd client && npm run dev
```

Layout:

- `src/lib/threads.ts`: client-only thread index (`id`, `title`, `updatedAt`) persisted in `localStorage`. eve has no server-side "list my sessions" API, so this index — and the mapping from a thread `id` to its eve `sessionId` — exists only in the browser; it is not a durable, cross-device store.
- `src/Chat.tsx`: one chat thread. Mounted with `key={threadId}` so switching threads remounts it with that thread's saved `initialEvents`/`initialSession`. Holds the `agent` option above, HITL approvals (needed for the flight-critical tools gated in the assistant's connection) and turn cancellation via `agent.cancel()`.
- `src/App.tsx`: sidebar shell — thread list plus "Nuevo chat".

Validate a `client/` change with `cd client && npx tsc -b`. Run `npm run build` there only when the change touches bundling (new dependency, Vite config, or anything read through `import.meta.env`) or the user asks for it — the project's "never build after changes" rule targets the eve agents, not this separate package.

`client/` runs on the same Node as the rest of the repo. eve itself hard-fails below Node 24; the client only warns (`EBADENGINE`) and still installs.

## Validate the change

Run the validation the task requests. When it does not establish the behavior you changed, run the narrowest relevant check.

For the agents, in increasing cost:

```sh
npm run typecheck                 # tsc over agents/, shared/ and evals/ (root tsconfig)
npx eve info --agent <name>       # discovery + diagnostics, no server; ignores .env
```

Keep the root `tsconfig.json` `include` in step with the directories that exist — it silently passed over zero files once, after the agent tree moved.

Do not run `eve build` to check a change. Prefer `eve info`, and note that both it and the build evaluate authored modules, so anything that throws at module load breaks them even when the runtime would have been fine.
