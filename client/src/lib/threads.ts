import type { ClientSessionState, MessageStreamEvent } from "eve/client";

export interface ThreadSummary {
  id: string;
  title: string;
  updatedAt: number;
}

export interface SavedThreadChat {
  session?: ClientSessionState;
  events?: readonly MessageStreamEvent[];
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
