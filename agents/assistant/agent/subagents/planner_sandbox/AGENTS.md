# planner_sandbox subagent

## Objective

Plan a multi-UAV inspection mission — waypoints, drone-to-target assignment, route order, mission JSON — **without letting the model invent a single coordinate**. Geometry (distances, ring positions, yaw angles, route costs) always comes out of a deterministic Python pipeline that runs inside a sandbox, never out of the model's own estimate. The model's job is exactly the part a script cannot do: read each element's physical description — prose today, and increasingly a structured model the GCS authors, see "modelo.yaml integration" below — choose the inspection strategy, assign targets to drones when the default assignment is wrong for this mission, and repair whatever the validator rejects.

This is a variant of `planner` for missions where geometry can't be safely eyeballed by the model. The full behavioral protocol the LLM follows — constants, the 6-step planning sequence, the validation gate, the `CHANGES` log format for repairs — is authored in `instructions.md`; that file **is** the system prompt, not documentation about it. This file documents the code around it: the end-to-end flow, what to touch when the pipeline's contract changes, and how this subagent's session reaches the operator through the client UI.

## End-to-end flow

**Input:** a natural-language request from the operator plus target/device identifiers, resolved against the GCS. **Output:** a persisted mission plan (`missionPlanId`) whose every waypoint has been checked against the real 3D obstacle model.

**This is the target architecture, not a description of the shipped pipeline.** The sequence below inverts the order the pipeline scripts currently implement (see "Current pipeline vs. this design" below) — it is the foundation to build `plan_routes.py` / `generate_waypoints.py` against, not documentation of what they already do. Do not assume a script named here matches its current behavior until that section says so.

**Why the order inverts:** the old sequence assigned whole targets to drones (`plan_routes.py`) *before* any waypoint existed, on the assumption that one target always belongs to exactly one drone. That assumption breaks the moment the operator asks for something like "two drones inspect this same target" — split by component, by side, or by whatever the request and the target's own geometry call for. There is no fixed rule for that split (not "front half / back half", not "even count") — it depends on what was asked and on the element's structure, and only the model can read that out of the request. So the split cannot happen before waypoints exist: **inspection waypoints must be generated first, per target, and clustering/assignment happens over those waypoints, not over target centers.**

1. **STEP 0 — Load the briefing.** `prepare_mission_input` resolves the briefing against the GCS and writes five files to `/workspace/data/`: `origin.json`, `devices.json`, `targets.json`, `obstacles.json` (all carrying real XYZ positions — the model never opens these) and `element_types.json` (per element **type** — the one file the model reads; prose `descriptions` today, plus a structured `model` field for types the GCS has migrated, see "modelo.yaml integration" below).

2. **STEP 1 — Geometry per element type, not per element.** The model reads `element_types.json` and writes `geometry.json`: for each *type* (not each individual element — sixteen wind turbines share one entry), what the element physically is (footprint, height, yaw) and how to fly around it (stand-off derived from `camera_fov`, altitude fraction, viewpoint count). This is where "the same element type repeated at different positions/orientations" is handled — the catalog defines geometry once per type, and `build_collision_objects.py` expands it over every concrete element using the positions already on disk.

   **When a type's entry carries `model` (Phase 1 of the modelo.yaml integration), this step is extraction, not inference:** the model reads `radius`/`width`/`length`/`height`/`yaw`/`safety_margin` straight out of `model.parameters` and the matching `model.links[].geometry` entry instead of parsing prose, and still derives `stand_off`/`altitude_fraction`/`viewpoints` with the same formulas as today — the inputs are exact now, the math doesn't change. A type with no `model` field keeps getting the prose treatment; this is a per-type fallback, not a mission-wide switch.

3. **STEP 2 — Author the inspection pattern per element type, then generate waypoints for every target.** For each element type, the model authors — or reuses — an inspection **pattern**: a plain function of the element's local frame (`ring.py` ships as the reference example — N points evenly spaced around the element). The model writes this itself whenever the operator's request or the element's structure calls for something a ring can't express (blade-by-blade sampling, a facade sweep, stacked rings), using the helper functions the sandbox provides for local-frame math so it never hand-derives a coordinate. One pattern file covers every element of that type: the runner instantiates it at each concrete element's real position and yaw, iterating over every target of that type, and produces every target's inspection waypoints — **before any drone is assigned to any of them.** See `sandbox/workspace/patterns/` below.

4. **STEP 3 — Cluster and assign at the waypoint level, then order each route.** Only now, with every target's actual inspection waypoints on disk, does assignment happen. Default case: a target's whole waypoint set goes to its nearest drone, same as today. When the request implies sharing — multiple drones on one target — the model decides the split (which waypoints, or which named component of the element, goes to which drone) from the request and the element's geometry; there is no default split to fall back on. A clustering/ordering script then takes whatever waypoint-to-drone assignment resulted (whole targets or partial sets) and produces each drone's visit order and route length — the same minimum-makespan objective `plan_routes.py` already implements today, just operating over waypoint clusters instead of target names.

5. **STEP 4 — Check each target's viewpoints in isolation.** `check_viewpoints.py` measures every generated waypoint against the collision model and flags anything inside an exclusion or caution zone, before the mission is assembled. Catching a bad viewpoint here is a one-pattern fix; the same defect caught later by the gate costs a full repair iteration across the whole mission.

6. **STEP 5 — Assemble.** `build_mission.py` follows the visit order fixed in Step 3 and produces `mission.json`, aborting if any target was left out.

7. **The validation gate.** `validate_and_persist` re-validates the assembled mission against the GCS's own obstacle database (independent of the pipeline's collision model) and persists it only when valid. If it isn't, the model enters **conflict resolution**: a bounded repair loop (`MAX_VALIDATION_ITERATIONS` gate calls) that climbs a fixed ladder of techniques — reorder (free) before transit waypoints, before wider bypass radius, before reassignment (last resort) — logging every change in a mandatory `CHANGES` block, then rebuilds and calls the gate again. Never hand-edits `mission.json` directly; it's generated and any manual edit is overwritten by the next build.

The throughline the model is held to everywhere in this sequence: **a number in the plan is either read from a data file the pipeline produced, or it doesn't belong there.** No script exists that lets the model type a coordinate, a distance, or an angle by hand.

## Current pipeline vs. this design

The shipped scripts under `sandbox/workspace/pipeline/` still implement the OLD order and its 1-target-1-drone assumption:

- `plan_routes.py` runs before waypoints exist and assigns whole targets (`target_names: [str]` per drone) — it cannot express "half of target A to drone 1, the rest to drone 2".
- `generate_waypoints.py` already does per-type, per-target waypoint generation correctly (Step 2 above matches it), but it runs *after* `plan_routes.py` today, and its output (`step4_waypoints.json`, one `target_blocks` entry per target) has no notion of which drone a given waypoint belongs to.

Making this design real means: keep `generate_waypoints.py` (and the pattern mechanism) but run it before assignment, and replace `plan_routes.py`'s target-level bucketing with a waypoint-level clustering step that accepts a model-authored split for any target the request wants to share across drones, defaulting to today's whole-target nearest-drone assignment otherwise. Until that change lands, treat this file's flow section as the spec to implement against, and `instructions.md` (the model's actual system prompt) as still describing the old, shipped order — **do not edit `instructions.md` to match this section until the pipeline scripts are rewritten to match it**, or the model will be instructed to call scripts that don't yet do what the prompt says.

## modelo.yaml integration (Phase 1 drafted here, not yet implemented; Phase 2 not started)

The GCS is moving element-type geometry from free-text `descriptions` (prose — see `docs/sandbox.md` for
why that's fragile: typos, mixed languages, and a parser that fails loudly is still better than one that
fails silently) to a structured `modelo.yaml` per type, alongside an already-generated 3D file (`.glb`)
for the operator's web viewer.

**Reference implementation, not vendored:** `/home/grvc/work/px4/wtsem/insem/` (`insem.py`,
`models/*.insem.yaml`, `README.md`) — an asset-agnostic engine built on 6 collision primitives (`box`,
`sphere`, `cylinder`, `capsule`, `beam`, `swept_box`) and 4 inspection patterns (`sweep`, `orbit`,
`face_grid`, `point`), where the LLM only ever writes a short inspection *request* and the engine computes,
validates and repairs every waypoint. This design borrows that vocabulary and its `insem/0.2` YAML shape
as a **working assumption** — nothing here has been confirmed against an actual GCS-issued file yet. Read
the reference project, don't copy it blind; the real schema may differ.

**Phase 1 — geometry only, no engine port:**

- `prepare_mission_input.ts` fetches the GCS's `modelo.yaml` for a type (when the GCS has one for it),
  converts YAML → JSON, and writes it as that type's `model` field in `element_types.json` — alongside,
  not replacing, `descriptions`, so an unmigrated type keeps working exactly as today.
- STEP 1 above changes from "derive geometry from prose" to "extract geometry from `model` when present,
  else fall back to prose." Nothing downstream of `geometry.json` changes.
- Pattern authoring (STEP 2 below), viewpoint checking, assembly and the validation gate are **unchanged**
  in Phase 1: the model still hand-writes `patterns/*.py` at runtime, even for a type whose `model` already
  names a pattern and its offsets. That redundancy is deliberate — Phase 1 only kills the *prose-parsing*
  failure mode (the silent 76-collisions-vs-0 example in `docs/sandbox.md`, caused by guessing the wrong
  geometry from text), not the *turns spent hand-authoring Python* cost. That's Phase 2.
- The `.glb` is **not read by this subagent in either phase**. Per the reference project's own design
  (`modelo-3d-glb.md`: the GLB is "skin", generated from the YAML, never consumed by the planner), it
  exists only for the client's web viewer. If that assumption is wrong for our GCS, revisit this section
  before Phase 1 ships — do not silently start parsing `.glb` here without updating this contract first.

**Phase 2 — port the deterministic pattern + repair engine (not started; blocked on Phase 1 shipping
against a real `modelo.yaml`):**

- Port the reference project's SDF primitives and 4 patterns as fixed, versioned, stdlib-only scripts
  under `sandbox/workspace/pipeline/`, replacing the model's runtime authorship of `patterns/*.py` for any
  type whose `model` names one of the four patterns.
- Port its per-view repair search (widen standoff, or rotate to an oblique view) so most single-view
  collisions never reach the model at all — this is what shrinks the `CONFLICT RESOLUTION` section of
  `instructions.md` down to what code genuinely can't resolve (reassignment, coverage, balance — already
  `plan_routes.py`'s / STEP 3's job, not new scope).
- Do not start this before Phase 1 has run against at least one real, GCS-issued `modelo.yaml` — the
  `insem/0.2` shape assumed above is unverified, and porting ~700 lines of SDF/pattern math against the
  wrong schema is work done twice.

**Why the YAML parse happens in Node, not in the sandbox:** the pipeline is stdlib-only Python by design —
no `pip install`, the sandbox may be offline (`docs/sandbox.md`). Python's stdlib has no YAML parser, and
the reference engine's own dependencies (`numpy`/`pyyaml`/`matplotlib`) are exactly what that rule exists
to avoid. `prepare_mission_input.ts` already runs in Node with network access, so the YAML → JSON
conversion happens there, once, before anything reaches the sandbox — the sandbox only ever sees JSON,
same as every other file in `/workspace/data`. `yaml` already resolves from `node_modules` today but is a
transitive dependency, not declared in `package.json` — declare it explicitly before this tool imports it.

**Open questions blocking Phase 1 (not yet answered — do not guess at these in code):**

- Which GCS endpoint/field actually delivers `modelo.yaml` for a type — part of the same catalog response
  `prepare_mission_input` already reads, or a separate fetch this tool doesn't make yet?
- Rollout shape: does every element type get a structured model at once, or does this ship as a mixed
  fleet (some types on `model`, some still on `descriptions`) for a while? STEP 1's fallback above assumes
  the latter; confirm before assuming every type will have `model` on day one.

## Directory map

```
sandbox/sandbox.ts            DefaultSandbox seeded from sandbox/workspace/**
sandbox/workspace/pipeline/   deterministic Python: build_collision_objects, plan_routes,
                               generate_waypoints, check_viewpoints, build_mission, spatial_analysis
                               (pipelib.py: shared I/O + local-frame math used by all of the above)
sandbox/workspace/patterns/   ring.py (the only shipped pattern) — the model authors more of these
                               at runtime, into /workspace/patterns/<name>.py; that's intentional,
                               not a gap to fill in ahead of time
tools/prepare_mission_input.ts  resolves the briefing against the GCS, writes /workspace/data/mission_input.json
tools/validate_and_persist.ts   the validation gate — reads the sandbox's mission, validates, persists
```

## Pipeline contract changes must update `instructions.md` too

`instructions.md` names each pipeline script, its CLI invocation, and the exact JSON shape of every file
under `/workspace/data/*.json` it reads or writes (STEP 0 through STEP 5). The model follows those
literally — renaming a script, changing its args, or changing a JSON field name is a prompt change, not
just a code change. Update the matching STEP section in the same PR.

`MAX_VALIDATION_ITERATIONS` (the gate call limit) is a constant duplicated in `instructions.md` §1 and
enforced by whatever loop-counting the calling code does around `validate_and_persist`. Keep both in sync
if you touch it.

## Reaching the assistant

Called from `agents/assistant/agent/tools/request_mission_plan.ts` via `await ctx.agent(planner_sandbox).send(...)`
and `response.result()` inside a `task` workflow tool (eve >= 0.69 replaced `execution: "background"` with `task`). See the parent's `AGENTS.md` for the currently-open upstream eve bug
(`docs/issue2.md`) affecting this exact dispatch path on the pinned eve version.

## Client UI: this subagent is the one wired into `SubagentPanel`

Today `planner_sandbox` is the only subagent with a dedicated UI surface. The mechanism, for when this
needs to be extended to `planner` or another future subagent:

1. eve emits an `agent.started` event carrying the delegated child's `sessionId` (plus `name`, `taskId`
   and `callId`) as soon as `ctx.agent(...)` opens the child session on its first `send` —
   `client/src/Chat.tsx` listens for it and opens a tab. (Before eve 0.69 this was `subagent.called`
   with `childSessionId`; that event no longer exists.)
2. `client/src/SubagentPanel.tsx` does **not** start a new session. It attaches to the already-running
   child session with `useEveAgent({ initialSession: { sessionId, streamIndex: 0 }, resume: true })`.
3. `client/src/ApprovalToolPart.tsx` renders any HITL request (`ask_question`, session-limit prompts,
   tool approvals) inside that panel the same way the main chat does, falling back to MUI X's default
   renderer for plain approve/deny.
4. **Cancellation semantics — read the comment at `client/src/SubagentPanel.tsx`'s `confirmCancel`
   before changing this flow.** Cancelling the child's turn resolves the parent's
   `await response.result()` with `status: "waiting"` and no `data` (eve's documented shape for a
   cancelled `ctx.agent` turn). `request_mission_plan` treats missing `data` as a failure and throws,
   so the task settles as failed and the assistant reads that in its `task.result` — the assistant's
   turn is no longer ended by it, unlike the pre-0.69 background flow. The sandbox itself is
   session-scoped, not turn-scoped, and survives cancellation (verified on eve 0.69 by reading eve's cancel path in `node_modules/eve/dist/src/{harness,execution}/*cancel*`
   — none of it touches the sandbox). "Cerrar" (`onClose`) just stops watching without cancelling anything.
5. "Ver archivos del sandbox" (`handleListFiles`) is a literal chat message asking the model to list
   `/workspace`, not a dedicated inspection API — there isn't one yet. Replace it if eve ships a native
   sandbox file browser.
