---
description: Use when the user asks to create, plan, generate or modify a drone inspection mission for registered elements — gathering targets and drones, choosing the inspection strategy, and dispatching the request to the planner.
---

# Mission Defaults

These are mission PARAMETERS, not private notes. The planner has **no other source** for any of them — whatever you do not forward in Step 4 is a value it will invent.

<!-- prettier-ignore -->
| Parameter | Default | Overridable by the user |
|---|---|---|
| `cruise_speed` (m/s) | 5 | **yes** — "do it at 3 m/s" → send `3` |
| `camera_fov` (deg) | 60 | rarely, but honour it if the user states it |

- **`cruise_speed`**: if the user names a speed anywhere in the request, that value REPLACES the default. Assume every drone accepts whatever speed is set — do not filter devices by it.
- **`camera_fov`**: horizontal field of view of the inspection camera. The planner uses it to work out how far from a target a waypoint must sit for the frame to cover what the chosen strategy requires — so the stand-off follows from the FOV, the inspection type and the object's size. No device reports its own FOV yet, so the 60° default applies unless the user says otherwise.

# Create Mission Workflow

Your role is to GATHER and FILTER data, then DELEGATE planning to the sub-agent via `request_mission_plan`. You do NOT plan waypoints or build routes — the planner sub-agent handles that.

**EXECUTION RULE:** Execute steps 1 through 4 AUTOMATICALLY and SEQUENTIALLY as a continuous chain without asking for user confirmation between steps. **EXCEPTIONS:** (1) If Step 1 yields ambiguous results, you MUST pause the workflow and ask the user to clarify before proceeding to Step 2. (2) If Step 2 finds no online drones, you MUST pause and ask the user per the "No online drones" rule below before proceeding to Step 3.

1. **Get targets** → call `multiuav-gcs__get_registered_objects` immediately.
   - Match by name, type, location, group.
   - **If geographic qualifier used:** apply the Spatial Reasoning rules from your base instructions. The filtered subset becomes `targets`.
   - **EARLY EXIT:** If ambiguous after filtering (e.g., multiple targets match and intent is unclear), PAUSE and ask the user to clarify WHICH objects. Do not ask for coordinates.
2. **Get drones** → call `multiuav-gcs__get_devices`, then `multiuav-gcs__get_fleet_telemetry` for real-time positions of online drones.
   - **HARD RULE: NEVER include OFFLINE drones in the selected devices without explicit user confirmation.** Run the Filter Priority + Proximity HARD RULE below restricted to ONLINE drones first.
   - **If that filtering leaves at least one ONLINE candidate** → proceed normally with those. Do NOT ask the user anything about offline drones — they are simply excluded, silently.
   - **Only if that filtering leaves ZERO online candidates** → do NOT stop silently either. Re-run the same Filter Priority + Proximity HARD RULE against the OFFLINE fleet to pick candidates, then PAUSE and ask the user by name whether to generate the mission plan using those offline drones. Proceed to Step 3 only after the user explicitly agrees; if they decline, stop and inform them a plan cannot be commanded or loaded until a drone comes online.
   - **Filter Priority:** (1) User explicit criteria, (2) Proximity to targets, (3) Workload estimation (1 drone per cluster/N objects, capped at available drones). Do NOT assign more drones than target objects.
   - **Proximity HARD RULE:** for every candidate drone, compute its distance to the NEAREST target using `distance_km ≈ 111 × sqrt((lat1-lat2)² + (cos(lat_avg_rad) × (lon1-lon2))²)` (lat/lon in degrees, `lat_avg_rad` = average of the two latitudes in radians). NEVER include a drone whose distance to every target exceeds 10km, regardless of its online status. Do not eyeball coordinates — compute the value.
3. **Determine inspection strategy** → Analyze user intent based on the "INSPECTION STRATEGIES" section below. Determine the type (`simple`, `circular`, or `detailed`).
4. **Delegate mission creation to planner** → call `request_mission_plan` with filtered data.
   - `targets`: the filtered subset from Step 1 · `selected_devices`: the drones from Step 2 that will actually fly — never the whole fleet · `mission_strategy` + `mission_strategy_description`: the type and rules from Step 3 · `user_request`: the user's intent.
   - **Copy the identifiers, never retype them.** A target's `id` is its `itemId` and its `name` is its `name`, both from `get_registered_objects` — the flattened item, not its group. A device's `id`, `name` and `category` come from `get_devices`. The server rejects the whole mission if any of them does not match the catalog exactly.
   - `targets_length` MUST equal the number of entries in `targets`. The tool rejects the call on any mismatch — count them, do not estimate.
   - **Do NOT gather or send obstacles.** The server resolves every obstacle in the flight area on its own, from the catalog. There is no obstacle parameter.
   - **Do NOT convert coordinates.** Send identifiers only; the server resolves each element's real position and converts the whole briefing itself. Never send latitudes, longitudes or XYZ values.
   - **Do NOT dictate visit order**, neither between targets nor between a target's own waypoints. The planner computes both from real geometry and route cost; an order volunteered here replaces a better solution with a worse guess. An order the USER dictated is part of their request and belongs in `user_request`, in their words.
   - **`mission_strategy_description` MUST end with this block, verbatim and last**, filled with the values from "Mission Defaults" above after applying any user override. It is the ONLY channel these parameters have:

     ```
     MISSION PARAMETERS
     cruise_speed: 5
     camera_fov: 60
     ```

     Emit both keys every time, even when unchanged. A missing key is a value the planner will invent. Inspection altitude is NOT a parameter — each strategy derives it from the element's own geometry.

   - Respond to user: "Mission plan is being generated..." and STOP. Do not poll, do not call the tool again waiting for it.

The workflow ends here: the planner answers asynchronously, and handling its
result is covered by "Planner Results" in your base instructions — you do not
need this skill loaded for that.

# INSPECTION STRATEGIES (Parameters for the Planner)

Select the appropriate type based on the user's request. When calling `request_mission_plan`, instruct the planner to apply the specific structural rules for the chosen type:

## 1. SIMPLE INSPECTION - Quick and efficient

- **When to use:** Keywords: "quick", "fast", "just a look", "brief", "ASAP".
- **Parameters to send to Planner:** - 1 waypoint per element.
  - Optimal frontal view.
  - Distance: one frame covers the element seen head-on → **`frame_extent = max_horizontal_extent`**.
  - Altitude: Vertical midpoint of the element.
  - Yaw: Pointing to the element's center.

## 2. CIRCULAR INSPECTION - Detail/time balance

- **When to use:** Default inspection. General views, structural elements, "normal" inspection.
- **Parameters to send to Planner:**
  - 4 points around each element.
  - Mandatory frontal point (aligned with element's orientation at 0°).
  - Additional points at 90°, 180°, and 270° from frontal position.
  - Distance: one frame covers the full face it is looking at → **`frame_extent = face_width`**.
  - Altitude: Vertical midpoint of the element or inportant structural sections(example: hub_height).
  - Cluster-based: Complete all waypoints of one element before moving to the next.

## 3. DETAILED INSPECTION - Maximum precision

- **When to use:** Complete analysis, predictive maintenance, critical elements.
- **Parameters to send to Planner:**
  - Distance: one frame covers ONE SECTION, not the whole element — that is what separates DETAILED from the other two → **`frame_extent = relevant_dimension / 3`**, where `relevant_dimension` is whichever dimension the pattern below sweeps across (`structure_height` for A1/A2, `element_height`/`element_width` for B).
  - Section count: **the planner computes how many sections that stand-off actually buys** — it may come out under 3 when the object's safety radius forces it farther away. Each pattern below only states its own floor.
  - Cut density: the planner splits the swept dimension into sections and confirms how many the resulting distance actually buys. On a large object the safety radius may force it farther out and yield fewer cuts than asked — that is a physical limit, not an error to argue with.

  ### A. For Volumetric Elements (Towers, Turbines, etc.):

  First classify the element by its aspect ratio: **height / max_diameter**.

  #### A1. Slender structures (aspect ratio > 4, e.g. masts, poles, chimneys, pylons, thin towers)
  - **Pattern: Top-down face sweep** — more efficient than rings for tall, narrow structures.
  - **For prismatic (non-circular) elements:** identify each distinct face (e.g. 4 faces for square cross-section).
    - For each face: one waypoint per section across `structure_height` (floor: 1).
    - Camera always perpendicular to the face, constant stand-off distance.
    - **Ordering — boustrophedon, not repeated top-to-bottom:** sweep face 1 top-to-bottom, then face 2 bottom-to-top continuing from where face 1 ended (no re-climb), then face 3 top-to-bottom, then face 4 bottom-to-top — proceeding clockwise around the structure. Alternating direction each face avoids climbing back to the top between faces, which would otherwise cost a full extra ascent per face at `VERTICAL_ENERGY_MULTIPLIER`.
  - **For cylindrical elements:** treat as 4 virtual faces at 0°, 90°, 180°, 270° relative to the element's heading.
    - For each virtual face: same rule — one waypoint per section across `structure_height` (floor: 1).
    - Camera always pointing toward the cylinder axis (radially inward), constant stand-off distance.
    - **Ordering — boustrophedon, not repeated top-to-bottom:** sweep 0° top-to-bottom, then 90° bottom-to-top continuing from where 0° ended (no re-climb), then 180° top-to-bottom, then 270° bottom-to-top. Alternating direction each face avoids climbing back to the top between faces, which would otherwise cost a full extra ascent per face at `VERTICAL_ENERGY_MULTIPLIER`.
  - **Altitude range:** from [top_z - camera_offset] down to [base_z + camera_offset]. Never place a waypoint where the camera would see only sky or ground.

  #### A2. Bulky structures (aspect ratio ≤ 4, e.g. turbine nacelles, storage tanks, substations)
  - **Pattern: Horizontal rings** — efficient full coverage for wide structures.
  - Divide the element vertically into N inspection rings, one per section across `structure_height` (**floor: 3** — guarantees top/mid/base coverage even when the safety radius forces a wider frame). Each ring altitude must center on a meaningful structural section.
  - Ring altitude placement rule: distribute rings uniformly across [base_z + camera_offset, top_z - camera_offset].
  - For each ring: 4 points spaced at 0°, 90°, 180°, 270° relative to the element's heading (0° = heading direction).
  - Waypoint ordering: Complete all 4 points of a ring clockwise (frontal → +90° → +180° → +270°) before moving to the next ring.

  ### B. For Planar Elements (Facades, Walls, Building faces):
  - **Sweep Pattern (Barrido):** Execute a grid-based scan covering the entire surface area.
  - **Grid logic:**
    - Divide the element into N vertical sections (rows) and M horizontal sections (columns) across `element_height` and `element_width` respectively (floor: 1 each).
    - Waypoints must cover the full area, ensuring sufficient overlap for complete imagery.
  - **Waypoint ordering (Zig-zag / S-pattern):**
    - Start at one corner (e.g., bottom-left).
    - Sweep horizontally across the row to the opposite side.
    - Move vertically to the next row (up or down).
    - Sweep horizontally in the opposite direction.
    - Repeat until the entire surface is covered.
  - **Orientation:** Camera must always be perpendicular to the surface (facing the element directly).
  - **Distance:** Maintain a constant safety distance from the surface.

## 4. CUSTOM / HYBRID - User-defined rules

- **When to use:** The user explicitly describes HOW to fly, sets specific constraints, or requests a specific pattern (e.g., "only scan the south face", "fly in a zig-zag", "stay above 50m", "focus only on the top connections").
- **Parameters to send to Planner:**
  - Identify the closest base strategy (Simple, Circular, or Detailed) to use as a foundation.
  - OVERRIDE the base parameters with the user's specific explicit instructions.
  - Pass the exact logical constraints (e.g., "Limit waypoints to the South face", "Maintain exactly 30m distance") to the planner.
  - Do NOT calculate the custom waypoints yourself; just pass the logic clearly.
