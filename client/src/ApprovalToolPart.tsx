import { Box, Button, Stack, Typography } from "@mui/material";
import { getDefaultMessagePartRenderer, type ChatDynamicToolMessagePart, type ChatPartRendererProps } from "@mui/x-chat/headless";
import type { EveMessageInputRequest } from "eve/client";
import type { UseEveAgentHelpers } from "eve/react";

interface ApprovalToolPartProps extends ChatPartRendererProps<ChatDynamicToolMessagePart> {
  getInputRequest: (toolCallId: string) => EveMessageInputRequest | undefined;
  respond: UseEveAgentHelpers<unknown>["respond"];
}

/**
 * eve's HITL requests (`ask_question`, session-limit prompts) carry arbitrary
 * `options` — not just approve/deny — so a request with more than the two
 * built-in choices renders its own buttons and answers via `agent.respond`
 * directly, bypassing MUI X's binary `addToolApprovalResponse`. Everything
 * else (plain tool approvals, every other tool state) falls back to the
 * built-in renderer.
 */
function ApprovalToolPart(props: ApprovalToolPartProps) {
  const { part, getInputRequest, respond, ...rest } = props;
  const { toolInvocation } = part;
  const request = getInputRequest(toolInvocation.toolCallId);

  if (toolInvocation.state !== "approval-requested" || !request || (request.options?.length ?? 0) <= 2) {
    const fallback = getDefaultMessagePartRenderer(part);
    return fallback ? fallback({ part, ...rest }) : null;
  }

  return (
    <Box sx={{ border: 1, borderColor: "divider", borderRadius: 1, p: 1.5, my: 0.5 }}>
      <Typography variant="body2" sx={{ mb: 1 }}>
        {request.prompt}
      </Typography>
      <Stack direction="row" spacing={1} sx={{ flexWrap: "wrap" }}>
        {request.options?.map((option) => (
          <Button
            key={option.id}
            size="small"
            variant={option.style === "primary" ? "contained" : "outlined"}
            color={option.style === "danger" ? "error" : "primary"}
            onClick={() => void respond([{ requestId: request.requestId, optionId: option.id }])}
          >
            {option.label}
          </Button>
        ))}
      </Stack>
    </Box>
  );
}

export default ApprovalToolPart;
