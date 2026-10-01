import { Box, Button, Stack, Typography } from "@mui/material";
import { useEveAgent } from "eve/react";
import { ChatBox } from "@mui/x-chat";
import { useEveAgentChatAdapter } from "./lib/useEveAgentChatAdapter";
import ApprovalToolPart from "./ApprovalToolPart";
import CopyButton from "./CopyButton";

interface SubagentPanelProps {
  sessionId: string;
  subagentName: string;
  onClose: () => void;
}

/**
 * Attaches to an already-running child session (created when a workflow tool
 * delegates to a subagent) instead of starting a new one. `initialSession` +
 * `resume: true` is exactly the shape `useEveAgent` needs to follow a session
 * it did not create itself — no separate client is required.
 */
function SubagentPanel({ sessionId, subagentName, onClose }: SubagentPanelProps) {
  const agent = useEveAgent({
    agent: import.meta.env.VITE_EVE_AGENT || undefined,
    initialSession: { sessionId, streamIndex: 0 },
    resume: true,
  });

  const isResuming = agent.status === "resuming";
  const isBusy = agent.status === "submitted" || agent.status === "streaming";

  const { adapter, messages, getInputRequest } = useEveAgentChatAdapter(agent, {
    confirmCancel: () =>
      // request_mission_plan (a `task` workflow tool) waits in
      // `await response.result()` on its `ctx.agent(planner_sandbox).send(...)`
      // for the whole delegation. Cancelling this child's turn resolves that
      // await with `status: "waiting"` and no `data` (eve's documented shape
      // for a cancelled turn), so the tool throws and the task settles as
      // failed. The assistant reads that failure in its `task.result` and its
      // turn keeps going — since eve 0.69 the cancel no longer ends it.
      // "Cerrar" (onClose) is the safe way to just stop watching without
      // cancelling anything.
      //
      // The sandbox is safe either way: it's owned by the SESSION, not the
      // turn, and eve's turn-cancellation path never tears it down (confirmed
      // on eve 0.69 by reading node_modules/eve/dist/src/{harness,execution}/*cancel*
      // — the only sandbox reference stages attachments into it). Files stay
      // put and this same panel keeps working afterward.
      window.confirm(
        "Esto corta la generación acá y el pedido de plan del assistant queda como fallido (el assistant recibe " +
          "el error y sigue su turno). El sandbox NO se destruye — los archivos siguen ahí y podés seguir usando este panel " +
          '(incluido "Ver archivos del sandbox") después de cancelar.\n\n' +
          'Si solo querés dejar de mirar sin cortar nada, usá "Cerrar" en vez de esto.',
      ),
  });

  function handleListFiles() {
    if (isBusy || isResuming) return;
    void agent.send(
      "Listá los archivos en /workspace (y subcarpetas relevantes como /workspace/data y /workspace/pipeline) y mostrame el contenido de los que ya existan.",
    );
  }

  return (
    <Stack sx={{ flex: 1, minHeight: 0 }}>
      <Stack direction="row" spacing={1} sx={{ alignItems: "center", justifyContent: "space-between", px: 2, py: 1, borderBottom: 1, borderColor: "divider" }}>
        <Typography variant="body2" title={sessionId}>
          subagent: <strong>{subagentName}</strong> ({sessionId.slice(0, 12)}…)
        </Typography>
        <Stack direction="row" spacing={1}>
          <CopyButton text={sessionId} label="Copiar id" />
          <Button size="small" onClick={onClose} title="Deja de mirar esta sesión; no la cancela">
            Cerrar
          </Button>
        </Stack>
      </Stack>

      <Box sx={{ px: 2, py: 1, borderBottom: 1, borderColor: "divider" }}>
        <Button size="small" variant="outlined" onClick={handleListFiles} disabled={isBusy || isResuming}>
          Ver archivos del sandbox
        </Button>
      </Box>

      {isResuming ? (
        <Box sx={{ p: 2 }}>
          <Typography color="text.secondary">Adjuntando a la sesión…</Typography>
        </Box>
      ) : (
        <ChatBox
          adapter={adapter}
          messages={messages}
          onMessagesChange={() => {
            /* controlled: useEveAgent stays the source of truth, this is a required no-op */
          }}
          onError={(error) => console.error("[subagent-panel]", error.source, error.message)}
          partRenderers={{
            "dynamic-tool": (props) => <ApprovalToolPart {...props} getInputRequest={getInputRequest} respond={agent.respond} />,
          }}
          features={{ conversationHeader: false, helperText: false, suggestions: false }}
          sx={{ flex: 1, minHeight: 0 }}
        />
      )}
    </Stack>
  );
}

export default SubagentPanel;
