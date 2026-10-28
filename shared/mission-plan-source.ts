/**
 * `MissionPlan.source` written by the planner_sandbox gate, so the parent can find the plan in the GCS
 * without trusting the planner's final answer.
 *
 * The gate (`validate_and_persist`, in the child session) knows its parent through
 * `ctx.session.parent.{sessionId, callId}`; `request_mission_plan` (the parent's workflow tool) knows the
 * same pair as `ctx.session.id` + `ctx.callId`. That pair identifies one planning request, so the plan id
 * reaches the main chat straight from the database even when the model never writes its `eve__reply`.
 */
const PREFIX = "planner_sandbox";

export type PlannerRequest = { sessionId: string; callId: string };

export function plannerPlanSource(request: PlannerRequest, valid: boolean): string {
  return `${PREFIX}:${valid ? "valid" : "invalid"}:${request.sessionId}:${request.callId}`;
}

/** The validity the gate recorded, when `source` belongs to `request`; otherwise undefined. */
export function matchPlannerPlanSource(source: unknown, request: PlannerRequest): { valid: boolean } | undefined {
  if (typeof source !== "string") return undefined;
  const [prefix, status, sessionId, callId] = source.split(":");
  if (prefix !== PREFIX || sessionId !== request.sessionId || callId !== request.callId) return undefined;
  return { valid: status === "valid" };
}
