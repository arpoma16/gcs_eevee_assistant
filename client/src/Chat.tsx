import { useState } from "react";
import { useEveAgent } from "eve/react";
import { loadThreadData, saveThreadData, titleFromMessage, type ThreadSummary } from "./lib/threads";
import "./Chat.css";

interface ChatProps {
  threadId: string;
  onThreadUpdate: (id: string, patch: Partial<ThreadSummary>) => void;
}

function Chat({ threadId, onThreadUpdate }: ChatProps) {
  const [saved] = useState(() => loadThreadData(threadId));
  const [cancelling, setCancelling] = useState(false);
  const [cancelError, setCancelError] = useState<string | null>(null);

  const agent = useEveAgent({
    initialEvents: saved.events ?? [],
    initialSession: saved.session,
    resume: saved.session !== undefined,
    onSessionChange(session) {
      saveThreadData(threadId, { ...loadThreadData(threadId), session });
    },
    onFinish(snapshot) {
      saveThreadData(threadId, { events: snapshot.events, session: snapshot.session });
      onThreadUpdate(threadId, {});
    },
  });

  const isBusy = agent.status === "submitted" || agent.status === "streaming";
  const isResuming = agent.status === "resuming";

  async function handleCancel() {
    setCancelling(true);
    setCancelError(null);
    try {
      await agent.cancel();
    } catch (error) {
      setCancelError(error instanceof Error ? error.message : "No se pudo cancelar el turno.");
    } finally {
      setCancelling(false);
    }
  }

  const pendingRequests = agent.data.messages
    .flatMap((message) => message.parts)
    .flatMap((part) => {
      if (part.type !== "dynamic-tool" || part.state !== "approval-requested") return [];
      const request = part.toolMetadata?.eve?.inputRequest;
      return request ? [request] : [];
    });

  return (
    <section className="chat">
      <div className="messages">
        {agent.data.messages.length === 0 ? (
          <p className="empty">Empezá la conversación…</p>
        ) : (
          agent.data.messages.map((message) => (
            <article key={message.id} className={`message ${message.role}`}>
              <header>{message.role}</header>
              {message.parts.map((part, index) =>
                part.type === "text" ? <p key={index}>{part.text}</p> : null,
              )}
            </article>
          ))
        )}
      </div>

      {pendingRequests.map((request) => (
        <fieldset key={request.requestId} className="approval">
          <legend>
            {request.kind === "tool-approval"
              ? "Approval required"
              : request.kind === "question"
                ? "Question"
                : "Session limit"}
          </legend>
          <p>{request.prompt}</p>
          {request.options?.map((option) => (
            <button
              key={option.id}
              type="button"
              onClick={() =>
                void agent.respond([{ requestId: request.requestId, optionId: option.id }])
              }
            >
              {option.label}
            </button>
          ))}
        </fieldset>
      ))}

      {isBusy ? (
        <div className="status">
          <span>{agent.status === "streaming" ? "Respondiendo…" : "Enviando…"}</span>
          <button type="button" onClick={() => void handleCancel()} disabled={cancelling}>
            {cancelling ? "Cancelando…" : "Cancelar"}
          </button>
        </div>
      ) : null}

      {cancelError ? <p className="error">{cancelError}</p> : null}
      {agent.error ? <p className="error">{agent.error.message}</p> : null}

      <form
        onSubmit={(event) => {
          event.preventDefault();
          const form = new FormData(event.currentTarget);
          const message = String(form.get("message") ?? "").trim();
          if (message.length === 0 || isResuming) return;

          if (agent.data.messages.length === 0) {
            onThreadUpdate(threadId, { title: titleFromMessage(message) });
          }
          void agent.send(message, isBusy ? { turnPolicy: "steer" } : undefined);
          event.currentTarget.reset();
        }}
      >
        <input name="message" disabled={isResuming} placeholder="Message the agent…" autoFocus />
        <button type="submit" disabled={isResuming}>
          Send
        </button>
      </form>
    </section>
  );
}

export default Chat;
