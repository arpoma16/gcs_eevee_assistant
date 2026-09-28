import { useState } from "react";
import { Box, Button, Stack, Tab, Tabs, Typography } from "@mui/material";
import { useEveAgent } from "eve/react";
import { ChatBox } from "@mui/x-chat";
import { useChatStatus, useChatActions } from "@mui/x-chat/headless";
import { useEveAgentChatAdapter } from "./lib/useEveAgentChatAdapter";
import ApprovalToolPart from "./ApprovalToolPart";
import {
  loadThreadData,
  saveThreadData,
  titleFromMessage,
  type DelegatedSubagentRecord,
  type ThreadSummary,
} from "./lib/threads";
import SubagentPanel from "./SubagentPanel";
import CopyButton from "./CopyButton";

interface ChatProps {
  threadId: string;
  onThreadUpdate: (id: string, patch: Partial<ThreadSummary>) => void;
}

function Chat({ threadId, onThreadUpdate }: ChatProps) {
  const [saved] = useState(() => loadThreadData(threadId));
  // Every delegation this thread has made, oldest first — a retry always
  // opens a brand-new session (eve never reuses one without an explicit
  // `agentId`), so this list only grows. Persisted so a past attempt is
  // still reachable after a reload without paying for a fresh delegation.
  const [subagents, setSubagents] = useState<readonly DelegatedSubagentRecord[]>(() => saved.subagents ?? []);
  const [openSessionId, setOpenSessionId] = useState<string | null>(() => saved.subagents?.at(-1)?.sessionId ?? null);

  const agent = useEveAgent({
    // Vacío (o ausente) apunta a las rutas same-origin /eve/v1/* que sirve
    // `eve dev --agent <name>`: un agente por proceso, sin prefijo.
    // Con "assistant" apunta a /eve/assistant/v1/*, que es como `vercel dev
    // --local` monta cada miembro del workspace. No combinar con `host`.
    agent: import.meta.env.VITE_EVE_AGENT || undefined,
    initialEvents: saved.events ?? [],
    initialSession: saved.session,
    resume: saved.session !== undefined,
    onSessionChange(session) {
      saveThreadData(threadId, { ...loadThreadData(threadId), session });
    },
    onFinish(snapshot) {
      // Merge, don't replace: a plain `{events, session}` write here clobbers
      // whatever `subagents` the `subagent.called` handler below already
      // persisted mid-turn, since `saveThreadData` overwrites the whole
      // record. A turn finishing is exactly when a delegation has just
      // settled, so this was silently dropping the panel's history on every
      // reload.
      saveThreadData(threadId, { ...loadThreadData(threadId), events: snapshot.events, session: snapshot.session });
      onThreadUpdate(threadId, {});
    },
    // `subagent.called` carries the delegated child's sessionId as soon as eve
    // starts it — well before the parent's background tool call ever settles.
    // See docs/debugging.md ("Seguir el stream del subagente por API") for the
    // same id via `eve traces` when debugging outside the browser.
    //
    // This stays on `onEvent` (not routed through the MUI X chat adapter):
    // the event isn't part of any message's content, so there's no chunk in
    // MUI X's vocabulary it naturally maps to.
    onEvent(event) {
      if (event.type === "subagent.called") {
        const record: DelegatedSubagentRecord = {
          sessionId: event.data.childSessionId,
          name: event.data.name,
          startedAt: Date.now(),
        };
        setSubagents((prev) => {
          if (prev.some((s) => s.sessionId === record.sessionId)) return prev;
          const next = [...prev, record];
          saveThreadData(threadId, { ...loadThreadData(threadId), subagents: next });
          return next;
        });
        setOpenSessionId(record.sessionId);
      }
    },
  });

  const { adapter, messages, getInputRequest } = useEveAgentChatAdapter(agent, {
    onFirstSend: (text) => onThreadUpdate(threadId, { title: titleFromMessage(text) }),
  });

  return (
    <Stack direction="row" sx={{ flex: 1, minHeight: 0 }}>
      <Stack sx={{ flex: 1, minWidth: 0 }}>
        {agent.session ? (
          <Stack direction="row" spacing={1} sx={{ alignItems: "center", px: 2, py: 1, borderBottom: 1, borderColor: "divider" }}>
            <Typography variant="caption" color="text.secondary">
              assistant session: {agent.session.sessionId}
            </Typography>
            <CopyButton text={agent.session.sessionId} />
          </Stack>
        ) : null}

        <ChatBox
          adapter={adapter}
          messages={messages}
          onMessagesChange={() => {
            /* controlled: useEveAgent stays the source of truth, this is a required no-op */
          }}
          onError={(error) => console.error("[chat]", error.source, error.message)}
          partRenderers={{
            "dynamic-tool": (props) => <ApprovalToolPart {...props} getInputRequest={getInputRequest} respond={agent.respond} />,
          }}
          features={{ conversationHeader: false, helperText: false }}
          sx={{ flex: 1, minHeight: 0, position: "relative" }}
        >
          <CancelTurnButton />
        </ChatBox>
      </Stack>

      {subagents.length > 0 ? (
        <Stack sx={{ width: 420, borderLeft: 1, borderColor: "divider", minHeight: 0 }}>
          <Tabs
            value={openSessionId ?? false}
            onChange={(_, value) => setOpenSessionId(value)}
            variant="scrollable"
            scrollButtons="auto"
          >
            {subagents.map((s) => (
              <Tab key={s.sessionId} value={s.sessionId} label={`${s.name} · ${new Date(s.startedAt).toLocaleTimeString()}`} title={s.sessionId} />
            ))}
          </Tabs>

          {openSessionId ? (
            <SubagentPanel
              key={openSessionId}
              sessionId={openSessionId}
              subagentName={subagents.find((s) => s.sessionId === openSessionId)?.name ?? "subagent"}
              onClose={() => setOpenSessionId(null)}
            />
          ) : (
            <Box sx={{ p: 2 }}>
              <Typography color="text.secondary">Elegí una delegación arriba para verla.</Typography>
            </Box>
          )}
        </Stack>
      ) : null}
    </Stack>
  );
}

/** `ChatBox` renders no stop button of its own (see MUI X Chat docs, Building an adapter §3) — this one lives as a `ChatBox` child so it can reach `useChatStatus`/`useChatActions`. */
function CancelTurnButton() {
  const { isStreaming } = useChatStatus();
  const { stopStreaming } = useChatActions();
  if (!isStreaming) return null;
  return (
    <Button size="small" onClick={() => stopStreaming()} sx={{ position: "absolute", top: 8, right: 8, zIndex: 1 }}>
      Cancelar
    </Button>
  );
}

export default Chat;
