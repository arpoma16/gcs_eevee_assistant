import { useCallback, useEffect, useMemo, useRef } from "react";
import type { EveDynamicToolPart, EveMessage, EveMessageInputRequest, EveMessagePart } from "eve/client";
import type { UseEveAgentHelpers } from "eve/react";
import type {
  ChatAdapter,
  ChatMessage,
  ChatMessageChunk,
  ChatMessagePart,
  ChatToolInvocationState,
} from "@mui/x-chat/headless";

/**
 * `EveDynamicToolPart["state"]` and `ChatToolInvocationState` use the same
 * vocabulary (AI SDK `dynamic-tool` convention on eve's side) except eve has
 * no `input-streaming` -> `input-available` gap for approval, so this is an
 * identity map — kept explicit so a future divergence fails to typecheck
 * instead of silently mis-rendering tool cards.
 */
const TOOL_STATE: Record<EveDynamicToolPart["state"], ChatToolInvocationState> = {
  "input-streaming": "input-streaming",
  "input-available": "input-available",
  "approval-requested": "approval-requested",
  "approval-responded": "approval-responded",
  "output-available": "output-available",
  "output-error": "output-error",
  "output-denied": "output-denied",
};

/** Maps one eve message part to the MUI X Chat part shape, or `null` for parts with no chat equivalent (e.g. `authorization`, `step-start`). */
function toChatPart(part: EveMessagePart): ChatMessagePart | null {
  if (part.type === "text") {
    return { type: "text", text: part.text, state: part.state === "streaming" ? "streaming" : "done" };
  }
  if (part.type === "reasoning") {
    return { type: "reasoning", text: part.text, state: part.state === "streaming" ? "streaming" : "done" };
  }
  if (part.type === "dynamic-tool") {
    return {
      type: "dynamic-tool",
      toolInvocation: {
        toolCallId: part.toolCallId,
        toolName: part.toolName,
        state: TOOL_STATE[part.state],
        input: "input" in part ? part.input : undefined,
        output: "output" in part ? part.output : undefined,
        errorText: "errorText" in part ? part.errorText : undefined,
        approvalId: "approval" in part ? part.approval?.id : undefined,
        approval:
          "approval" in part && part.approval && part.approval.approved !== undefined
            ? { approved: part.approval.approved, reason: part.approval.reason }
            : undefined,
      },
    };
  }
  return null;
}

/** Maps one eve message to the MUI X Chat message shape. */
function toChatMessage(message: EveMessage): ChatMessage {
  const parts = message.parts
    .map((part) => toChatPart(part))
    .filter((part): part is ChatMessagePart => part !== null);
  const status = message.metadata?.status;
  return {
    id: message.id,
    role: message.role,
    parts,
    status:
      status === "streaming"
        ? "streaming"
        : status === "failed"
          ? "error"
          : status === "submitted"
            ? "sending"
            : "sent",
  };
}

/**
 * Bridges `useEveAgent` to a MUI X Chat `ChatAdapter`. eve does not expose a
 * raw stream to re-wrap — `agent.data.messages` is already the normalized,
 * per-render snapshot — so `sendMessage` triggers `agent.send` and a
 * `ReadableStream` is fed by diffing successive snapshots against a queued
 * controller instead of translating wire bytes. See AGENTS.md's `"use
 * workflow"` note for the unrelated cross-realm gotcha; this file doesn't
 * cross a workflow boundary, so it doesn't apply here.
 */
export function useEveAgentChatAdapter(
  agent: UseEveAgentHelpers<{ readonly messages: readonly EveMessage[] }>,
  options: {
    readonly onFirstSend?: (text: string) => void;
    /** Gate for `stop()`/abort — return `false` to skip cancelling (e.g. a confirm dialog the user declined). */
    readonly confirmCancel?: () => boolean;
  } = {},
) {
  const controllerRef = useRef<ReadableStreamDefaultController<ChatMessageChunk> | null>(null);
  const seenRef = useRef<Map<string, EveMessage>>(new Map());
  const streamingIdRef = useRef<string | null>(null);

  // `ChatToolInvocation` has no free-form field to carry eve's `inputRequest`
  // (prompt + arbitrary options, not just approve/deny), so it's tracked here
  // instead, keyed by toolCallId, for the approval partRenderer to read.
  const inputRequestsRef = useRef<Map<string, EveMessageInputRequest>>(new Map());
  useEffect(() => {
    for (const message of agent.data.messages) {
      for (const part of message.parts) {
        if (part.type === "dynamic-tool" && "approval" in part && part.approval) {
          const request = part.toolMetadata?.eve?.inputRequest;
          if (request) inputRequestsRef.current.set(part.toolCallId, request);
        }
      }
    }
  }, [agent.data.messages]);

  useEffect(() => {
    const controller = controllerRef.current;
    if (!controller) return;

    for (const message of agent.data.messages) {
      if (message.role !== "assistant") continue;
      const previous = seenRef.current.get(message.id);
      seenRef.current.set(message.id, message);

      if (!previous) {
        controller.enqueue({ type: "start", messageId: message.id });
        streamingIdRef.current = message.id;
      }

      diffParts(previous?.parts ?? [], message.parts, controller);

      const status = message.metadata?.status;
      if (status === "complete" && streamingIdRef.current === message.id) {
        controller.enqueue({ type: "finish", messageId: message.id });
        streamingIdRef.current = null;
      } else if (status === "failed" && streamingIdRef.current === message.id) {
        controller.enqueue({ type: "abort", messageId: message.id });
        streamingIdRef.current = null;
      }
    }
    // Runs after every render where `agent.data.messages` identity changes —
    // eve's store hands back a fresh array per snapshot, so this effect's own
    // dependency array is exactly that array.
  }, [agent.data.messages]);

  const { onFirstSend, confirmCancel } = options;

  const cancelTurn = useCallback(async () => {
    if (confirmCancel && !confirmCancel()) return;
    // `stop()`/abort errors aren't surfaced by the runtime's own error model
    // (it only wraps method throws during an active adapter call chain tied
    // to a request); log so a failed cancel isn't silent.
    try {
      await agent.cancel();
    } catch (error) {
      console.error("[chat] cancel failed", error);
    }
  }, [agent, confirmCancel]);

  const adapter = useMemo<ChatAdapter>(
    () => ({
      async sendMessage({ message, signal }) {
        const text = message.parts.find((part) => part.type === "text")?.text ?? "";
        if (agent.data.messages.length === 0) onFirstSend?.(text);
        const stream = new ReadableStream<ChatMessageChunk>({
          start(controller) {
            controllerRef.current = controller;
          },
          cancel() {
            controllerRef.current = null;
          },
        });
        signal.addEventListener("abort", () => {
          // MUI X aborts this signal on ordinary stream cleanup too (turn
          // finishing normally, the message stream being torn down), not
          // just when the user hits stop — cancelling `agent` in those cases
          // would fire `confirmCancel`'s dialog with nothing to confirm. Only
          // treat it as a real user cancel while eve's own turn is still
          // in flight.
          if (agent.status === "streaming" || agent.status === "submitted") {
            void cancelTurn();
          }
        });
        // Fire the turn after the stream (and its controller) is wired up, so
        // the effect above always has a controller to enqueue into even if
        // eve's first stream event arrives before this promise resolves.
        void agent.send(text, agent.status === "streaming" || agent.status === "submitted" ? { turnPolicy: "steer" } : undefined);
        return stream;
      },
      stop: cancelTurn,
      async addToolApprovalResponse({ id, approved }) {
        await agent.respond([{ requestId: id, optionId: approved ? "approve" : "deny" }]);
      },
    }),
    [agent, onFirstSend, cancelTurn],
  );

  const messages = useMemo(() => agent.data.messages.map(toChatMessage), [agent.data.messages]);

  return { adapter, messages, getInputRequest: (toolCallId: string) => inputRequestsRef.current.get(toolCallId) };
}

function diffParts(
  previous: readonly EveMessagePart[],
  next: readonly EveMessagePart[],
  controller: ReadableStreamDefaultController<ChatMessageChunk>,
): void {
  next.forEach((part, index) => {
    const before = previous[index];
    if (part.type === "text") {
      const id = `text-${index}`;
      if (!before) {
        controller.enqueue({ type: "text-start", id });
        if (part.text) controller.enqueue({ type: "text-delta", id, delta: part.text });
      } else if (before.type === "text" && before.text !== part.text && part.text.startsWith(before.text)) {
        controller.enqueue({ type: "text-delta", id, delta: part.text.slice(before.text.length) });
      }
      if (part.state === "done" && (!before || before.type !== "text" || before.state !== "done")) {
        controller.enqueue({ type: "text-end", id });
      }
      return;
    }

    if (part.type === "dynamic-tool") {
      const beforeTool = before?.type === "dynamic-tool" ? before : undefined;
      if (!beforeTool) {
        controller.enqueue({ type: "tool-input-start", toolCallId: part.toolCallId, toolName: part.toolName, dynamic: true });
      }
      if (beforeTool?.state === part.state) return;

      if (part.state === "input-available" || part.state === "approval-requested") {
        controller.enqueue({
          type: "tool-input-available",
          toolCallId: part.toolCallId,
          toolName: part.toolName,
          input: part.input,
        });
      }
      if (part.state === "approval-requested") {
        controller.enqueue({
          type: "tool-approval-request",
          toolCallId: part.toolCallId,
          toolName: part.toolName,
          input: part.input,
          approvalId: part.approval.id,
        });
      }
      if (part.state === "output-available") {
        controller.enqueue({ type: "tool-output-available", toolCallId: part.toolCallId, output: part.output, preliminary: part.partial });
      }
      if (part.state === "output-error") {
        controller.enqueue({ type: "tool-output-error", toolCallId: part.toolCallId, errorText: part.errorText });
      }
      if (part.state === "output-denied") {
        controller.enqueue({ type: "tool-output-denied", toolCallId: part.toolCallId, reason: part.approval.reason });
      }
    }
  });
}
