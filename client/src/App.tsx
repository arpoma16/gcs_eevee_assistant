import { useState } from "react";
import Chat from "./Chat";
import { createThread, loadThreads, saveThreads, type ThreadSummary } from "./lib/threads";
import "./App.css";

function App() {
  const [threads, setThreads] = useState<ThreadSummary[]>(() => {
    const existing = loadThreads();
    if (existing.length > 0) return existing;
    const first = createThread();
    saveThreads([first]);
    return [first];
  });
  const [activeId, setActiveId] = useState(() => threads[0].id);

  function handleNewChat() {
    const thread = createThread();
    setThreads((prev) => {
      const next = [thread, ...prev];
      saveThreads(next);
      return next;
    });
    setActiveId(thread.id);
  }

  function handleThreadUpdate(id: string, patch: Partial<ThreadSummary>) {
    setThreads((prev) => {
      const next = prev.map((thread) =>
        thread.id === id ? { ...thread, ...patch, updatedAt: Date.now() } : thread,
      );
      saveThreads(next);
      return next;
    });
  }

  const sorted = [...threads].sort((a, b) => b.updatedAt - a.updatedAt);

  return (
    <div className="app">
      <aside className="sidebar">
        <button type="button" className="new-chat" onClick={handleNewChat}>
          + Nuevo chat
        </button>
        <nav className="threads">
          {sorted.map((thread) => (
            <button
              key={thread.id}
              type="button"
              className={`thread ${thread.id === activeId ? "active" : ""}`}
              onClick={() => setActiveId(thread.id)}
            >
              {thread.title}
            </button>
          ))}
        </nav>
      </aside>

      <main className="main">
        <h1>eve • gcs_eevee_assistant</h1>
        <Chat key={activeId} threadId={activeId} onThreadUpdate={handleThreadUpdate} />
      </main>
    </div>
  );
}

export default App;
