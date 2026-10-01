import type { ClientSessionState, MessageStreamEvent } from "eve/client";

export interface ThreadSummary {
  id: string;
  title: string;
  updatedAt: number;
}

/** One `planner_sandbox`-style delegation captured from an `agent.started` event. */
export interface DelegatedSubagentRecord {
  sessionId: string;
  name: string;
  startedAt: number;
}

export interface SavedThreadChat {
  session?: ClientSessionState;
  events?: readonly MessageStreamEvent[];
  /**
   * Every child session `assistant` has delegated to in this thread, oldest
   * first. A retry always starts a brand-new session (each `ctx.agent(name)`
   * call opens a new session), so this can grow past one entry — kept
   * around so a past attempt stays reachable after the page reloads, instead
   * of paying for a fresh delegation just to look at it again.
   */
  subagents?: readonly DelegatedSubagentRecord[];
}

const THREADS_KEY = "eve-chat-threads";
const threadDataKey = (id: string) => `eve-chat-thread:${id}`;

export function loadThreads(): ThreadSummary[] {
  try {
    const raw = localStorage.getItem(THREADS_KEY);
    return raw ? (JSON.parse(raw) as ThreadSummary[]) : [];
  } catch {
    return [];
  }
}

export function saveThreads(threads: readonly ThreadSummary[]): void {
  try {
    localStorage.setItem(THREADS_KEY, JSON.stringify(threads));
  } catch {
    // Storage unavailable (private mode, quota); the list just won't persist.
  }
}

export function loadThreadData(id: string): SavedThreadChat {
  try {
    const raw = localStorage.getItem(threadDataKey(id));
    return raw ? (JSON.parse(raw) as SavedThreadChat) : {};
  } catch {
    return {};
  }
}

export function saveThreadData(id: string, data: SavedThreadChat): void {
  try {
    localStorage.setItem(threadDataKey(id), JSON.stringify(data));
  } catch {
    // Storage unavailable; the session just won't resume after reload.
  }
}

export function deleteThreadData(id: string): void {
  try {
    localStorage.removeItem(threadDataKey(id));
  } catch {
    // Nothing to clean up if storage is unavailable.
  }
}

export function createThread(): ThreadSummary {
  return {
    id: crypto.randomUUID(),
    title: "Nuevo chat",
    updatedAt: Date.now(),
  };
}

export function titleFromMessage(text: string): string {
  const trimmed = text.trim().replace(/\s+/g, " ");
  return trimmed.length > 40 ? `${trimmed.slice(0, 40)}…` : trimmed;
}
