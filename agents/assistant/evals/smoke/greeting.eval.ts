import { defineEval } from "eve/evals";
import { satisfies } from "eve/evals/expect";

export default defineEval({
  description: "A bare greeting gets a non-empty reply without calling any tool.",
  async test(t) {
    const turn = await t.send("Hello!");
    t.succeeded();
    t.notCalledTool("request_mission_plan");
    t.check(
      turn.message,
      satisfies(
        (message: string | undefined) => Boolean(message && message.trim().length > 0),
        "non-empty reply",
      ),
    );
  },
});
