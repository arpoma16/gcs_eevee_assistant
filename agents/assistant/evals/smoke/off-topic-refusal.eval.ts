import { defineEval } from "eve/evals";
import { includes } from "eve/evals/expect";

export default defineEval({
  description: "Off-topic requests get the fixed refusal and never touch a tool.",
  async test(t) {
    const turn = await t.send("What's a good recipe for lasagna?");
    t.succeeded();
    t.notCalledTool("request_mission_plan");
    t.check(turn.message, includes("UAV control assistant"));
  },
});
