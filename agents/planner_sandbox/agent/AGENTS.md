# planner_sandbox subagent

## Objective

Plan a multi-UAV inspection mission for **any element type and any operator request**, without the model
inventing a single coordinate. The model **writes the script** that generates the inspection — which parts,
surfaces, zones and features, in what combination and split — but every number in it comes out of a fixed
library (`lib/`) that loads the element's characterised model and computes the geometry. The model decides
*what* to inspect and *how to combine it*; the library decides *where the drone is*.

The design follows `/home/grvc/work/px4/wtsem/insem/` (`insem.py`, `models/*.insem.yaml`): an
asset-agnostic engine built on 6 collision primitives (`box`, `sphere`, `cylinder`, `capsule`, `beam`,
`swept_box`) and 4 inspection patterns (`sweep`, `orbit`, `face_grid`, `point`). Difference with insem: there
the LLM only writes a declarative request; here it writes a Python script against the same primitives, so a
request insem's request schema can't express (two drones on one target, a custom sequence, a mixed pattern)
is still expressible.

`instructions.md` **is** the system prompt, not documentation about it. This file documents the code around
it.

**Status:** `lib/`, `tools/`, `examples/`, both TS tools and `instructions.md` implement this design. The
old ring/`plan_routes` pipeline (`sandbox/workspace/pipeline/`, `patterns/`) has been removed.

## Element model: one `.insem.yaml` per type, always

- `prepare_mission_input.ts` resolves one model per **target** type into `data/models/<slug>.insem.yaml`
  (obstacle-only types get none). With a `definitionYaml` in the catalog it downloads it verbatim
  (`GET /markers/types/{id}/definition`; example: `test/workspace/data/models/wind_turbine.insem.yaml`).
  Without one — or when the download fails — `agent/lib/insem_model.ts` synthesises a minimal model from the
  catalog's `attributes.geometry`: `circle` → one `cylinder` with an `orbit` surface (zones base/middle/top);
  `rectangle` → one `box` with `face_grid` surfaces front (+y, towards azimFront) / back / right / left / top.
  `element_types.json` says which in `model_source: "gcs" | "generated"`. One code path for every type — no
  `ring.py` special case. A generated model has no `state`, so an instance's `attributes` are reported as
  ignored.
- **`parameters` are fixed per type** (hub height, part sizes). **Per-instance variation is `state` only**,
  taken from the target's `attributes` (e.g. `nacelle_heading_deg`, `rotor_azimuth_deg`). A script must adapt
  to each instance's state; it never overrides parameters.
- **Orientation convention:** `azimFront` is the instance's fixed installation pose (compass degrees,
  0 = North, clockwise); `lib/world.py` rotates the model's base frame by it. Articulated heading (a
  nacelle's) is `state`, resolved by the model's own kinematics. The catalog's `geometry.yaw` is redundant
  with `azimFront` and is being removed.

## Collision: two levels

| checked | against | why |
| --- | --- | --- |
| targets of the segment's **logical leg** | full model (SDF of its primitives), `min_clearance_m` | inspecting means getting close to the part; between two blade views you still can't cross the tower |
| every other element (obstacles and other targets) | catalog's simple geometry (circle/rectangle + height), `transit_clearance_m` | an element you're not inspecting only needs a prudent distance |

A **logical leg** runs between two consecutive non-`transit` waypoints; its context is the targets of those two
ends. Every segment inside it — including the ones between inserted `transit` points — uses that context.
`build_mission.py` (A* via `lib/transit.py`) and `validate.py` apply exactly this rule, so a detour the builder
finds is valid for the validator by construction.

Obstacles never go through the INSEM model: no `attributes`/state, only `position` + `azimFront` (which orients
a `rectangle`) over the catalog's `geometry`. `tools/describe.py` therefore covers target types only.

## Workspace layout (target)

```
/workspace
  requirements.txt        pyyaml, numpy
  lib/                    FIXED — provided by the system, imported by the model's scripts
    model.py              load .insem.yaml (fixed parameters + instance state), kinematics, primitive SDFs
    patterns.py           sweep / orbit / face_grid / point → views in the model frame
    world.py              data/*.json → instanced targets (position + azimFront), drones, simple obstacles
    views.py              view → world waypoint: yaw, gimbal, clearance; basic repair (standoff / oblique);
                          rejections carry nominal / best-attempt / `blocking` reasons + a hint per code
    regulation.py         altitude ceiling: 120 m, or up to 15 m above an element taller than 105 m within
                          50 m of it (EU 2019/947 UAS.OPEN.010(2), requires the element owner's request)
    mission.py            writes the mission v3 format — the only place that knows it; depends_on helpers
    transit.py            A* detours on a local 3D grid (port of insem's find_via) under the logical-leg rule
  tools/                  FIXED — run from the CLI
    describe.py           model summary (parts, surfaces, zones, features, state); the model reads THIS, not raw YAML
    assign.py             basic assignment: whole block → nearest drone, balanced, NN + 2-opt ordering
    build_mission.py      views + assignment → data/mission.json (v3); inserts `transit` detours where a
                          straight segment isn't flyable, and explains why when there is none
    validate.py           the validator (same code the gate runs)
  examples/
    inspect_example.py    complete, commented example script (turbine: blades + tower)
  scripts/                WRITTEN BY THE MODEL
    inspection.py         → data/views.json
    assignment.py         optional, only when assign.py's default doesn't fit the request
  request.md              WRITTEN BY THE MODEL: operator's request + its interpretation; re-read when context is lost
  data/                   prepare_mission_input output + pipeline outputs
```

## Flow

0. `prepare_mission_input` → `origin.json`, `devices.json`, `targets.json`, `obstacles.json`,
   `element_types.json` (catalog `geometry` = the simple collision shape), `models/*.insem.yaml`.
1. Write `request.md`.
2. `python3 tools/describe.py` per type.
3. Write `scripts/inspection.py` (start from `examples/`), run it → `data/views.json`.
4. `python3 tools/assign.py`, or write `scripts/assignment.py` → `data/assignment.json`.
5. `python3 tools/build_mission.py` → `data/mission.json`.
6. `python3 tools/validate.py`. On failure fix **the script** (never `mission.json`, it's generated) and
   re-run from the step that owns the defect.
7. `validate_and_persist`.

### Contracts

`data/views.json` — one entry per inspection waypoint. `block` is the **assignment unit**: normally one per
target; the script splits a target into several blocks when the request shares it across drones.

```json
[{ "target": "A3", "block": "A3/blade_A", "tag": "blade_A/leading_edge/tip",
   "pos": [0, 0, 0], "yaw": 60, "gimbal": -5 }]
```

`data/assignment.json` — same shape whether `tools/assign.py` or the model's own script produced it, so
`build_mission.py` never knows which. `assign.py` balances blocks by estimated route length (a 90-view tower
block doesn't weigh the same as a 15-view blade block), orders each route NN + 2-opt, and with `--keep`
respects a model-written assignment and only reorders it. Makespan is the critical path over `depends_on`,
not the longest single route:

```json
{ "routes": [
  { "uav": "uav_1", "task_id": "T1", "depends_on": [], "blocks": ["A3/blade_A", "A2"] },
  { "uav": "uav_2", "task_id": "T2", "depends_on": ["T1"], "blocks": ["A3/tower"] } ] }
```

### Mission format (v3)

Exactly `test/mission format.yaml` — `version: "3"`, `route[]` with `id`, `name`, `uav`, `uav_type`,
`task_id`, `depends_on`, `action: ROUTE`, full `attributes` (`mode_landing`, `mode_yaw`, `mode_gimbal`,
`mode_trace`, `idle_vel`, `max_vel`) and `wp[]` with `pos`, `yaw`, `gimbal`, `speed`, `action` — plus three
fields per waypoint:

```yaml
type: inspection                  # takeoff | transit | inspection | landing
target: A3                        # null outside inspection
tag: blade_A/leading_edge/tip     # free string, for traceability in validator reports
```

Inside the sandbox `pos` is ENU metres; the gate converts to geodetic on persist.

## The gate (`validate_and_persist`)

Runs **its own copy** of `lib/` + `tools/validate.py` at `/opt/planner_gate` (`agent/lib/gate.ts`), never
`/workspace/tools/validate.py`, which the model can edit. `sandbox/sandbox.ts` writes that copy during
`prepare`, root-owned and read-only, from the same seed that becomes `/workspace`; eve prepares a new
environment generation whenever the seed changes, so the copy always matches the shipped `lib/`. It guards
against accidental edits, not a deliberate one — the sandbox has passwordless sudo. Exit 0/1 is valid/invalid;
any other exit code, or a missing `data/validation.json`, throws. No longer calls the GCS `/missions/validate`
(it only knows simple extruded shapes). On `valid` (or `is_final_attempt`): `xyz-to-geodetic` (uses the
mission's `global_origin`) → `/missions/plans`. Returns `totalCollisions` (clearance findings) and
`totalFindings` (all).

`validate.py` checks: v3 structure; every briefing target covered; `depends_on` references existing
`task_id`s with no cycles; altitude floor and the `lib/regulation.py` ceiling (same rule as view
generation, applied to transit too); geofence (`origin.json` boundaries); the three collision
levels above, segments sampled every ~0.5 m. Report lines name `route / wp index / tag / obstacle /
penetration`.

`MAX_VALIDATION_ITERATIONS` lives in `instructions.md` §1 and in whatever counts gate calls — keep in sync.

## Pending (agreed, deliberately deferred)

- **UAV–UAV deconfliction.** The validator does not yet check separation between routes flying at the same
  time (no `depends_on` between them).
- **`xyz-to-geodetic` round trip with v3.** Unverified that the GCS converter / `/missions/plans` preserve
  `task_id`, `depends_on`, `uav_type`, `gimbal`, `type`, `target`, `tag`. Only the forward direction
  (`geodetic-to-xyz`, see `test/workspace/data/targets.json`) is known to work. Needed as the output format to
  test end to end; fix on the GCS side when it breaks.
- **Catalog vs model consistency (GCS side, owner: operator).** The catalog/target descriptions and the
  `.insem.yaml` disagree on size (test: hub 80 m / rotor 56 m vs 90 m / 120 m), and the model's frame must
  match `azimFront`. Fixed in the data, not worked around in code.
- **Remove `geometry.yaw` from the GCS catalog** in favour of `azimFront`.
- **Camera parameters.** `lib/views.Camera` still uses insem's defaults (72° HFOV, 5280×3956 px). They
  should come from the device (or its category) in the briefing, not from the operator's message; until
  `prepare_mission_input` writes them, the inspection script sets them by hand.

## Pipeline contract changes must update `instructions.md` too

`instructions.md` names each tool, its CLI invocation, and the exact JSON shape of every file it reads or
writes. The model follows those literally — renaming a tool, changing its args, or changing a JSON field is a
prompt change, not just a code change. Update it in the same PR.

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
