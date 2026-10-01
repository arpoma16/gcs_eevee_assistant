/**
 * Where the sandbox keeps the gate's own copy of the validator (`lib/` + `tools/validate.py`).
 *
 * `sandbox/sandbox.ts` writes it during `prepare`, root-owned and read-only, from the same seed that
 * becomes `/workspace`; eve prepares a new environment generation whenever that seed changes, so the
 * copy always matches the shipped `lib/`. `validate_and_persist` runs it instead of
 * `/workspace/tools/validate.py`, which the model can edit. It guards against accidental edits, not a
 * deliberate one: the sandbox has passwordless sudo.
 */
export const GATE_DIR = "/opt/planner_gate";

/** The gate's validator invocation: its own copy, reading the model's data. */
export const GATE_COMMAND = `PYTHONDONTWRITEBYTECODE=1 python3 ${GATE_DIR}/tools/validate.py --data /workspace/data`;
