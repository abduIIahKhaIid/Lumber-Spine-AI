"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, jsonBody, sseEvents } from "@/lib/api";
import type { ChatMessage, StreamEvent, Thread, ThreadSummary } from "./types";

const PENDING = "pending-assistant";

function pendingMessage(): ChatMessage {
  return { id: PENDING, role: "assistant", content: "", status: "streaming", steps: [] };
}

/** Thread list + active conversation + streaming, mirroring Chainlit's interaction model. */
export function useChat(initialThreadId: string | null) {
  const [threads, setThreads] = useState<ThreadSummary[]>([]);
  const [thread, setThread] = useState<Thread | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [providerLabel, setProviderLabel] = useState("");
  const [error, setError] = useState("");
  const [loadingThread, setLoadingThread] = useState(false);
  const controller = useRef<AbortController | null>(null);
  const activeId = useRef<string | null | undefined>(undefined);

  useEffect(() => {
    activeId.current = thread?.id ?? null;
  }, [thread]);

  const refreshThreads = useCallback(async (query = "") => {
    try {
      setThreads(await api<ThreadSummary[]>(`/api/chat/threads?q=${encodeURIComponent(query)}`));
    } catch (err) {
      setError((err as Error).message);
    }
  }, []);

  const openThread = useCallback(async (id: string | null) => {
    controller.current?.abort();
    setError("");
    if (!id) {
      setThread(null);
      setMessages([]);
      return;
    }
    setLoadingThread(true);
    try {
      const loaded = await api<Thread>(`/api/chat/threads/${id}`);
      setThread(loaded);
      setMessages(loaded.messages);
    } catch (err) {
      setError((err as Error).message);
      setThread(null);
      setMessages([]);
    } finally {
      setLoadingThread(false);
    }
  }, []);

  useEffect(() => {
    void refreshThreads();
  }, [refreshThreads]);

  useEffect(() => {
    // The URL also changes when a new conversation is created mid-stream; do not reload then.
    if (activeId.current !== undefined && initialThreadId === activeId.current) return;
    activeId.current = initialThreadId;
    void openThread(initialThreadId);
  }, [initialThreadId, openThread]);

  const apply = useCallback((event: StreamEvent) => {
    switch (event.type) {
      case "user_message":
        setMessages((current) => {
          if (event.replaces) {
            const index = current.findIndex((m) => m.id === event.replaces);
            return [...current.slice(0, Math.max(index, 0)), event.message];
          }
          return [...current, event.message];
        });
        break;
      case "truncated":
        setMessages((current) => {
          const index = current.findIndex((m) => m.id === event.after);
          return index >= 0 ? current.slice(0, index + 1) : current;
        });
        break;
      case "title":
        setThread((current) => (current ? { ...current, title: event.title } : current));
        break;
      case "thinking":
        setMessages((current) => [...current.filter((m) => m.id !== PENDING), pendingMessage()]);
        break;
      case "step":
        setMessages((current) =>
          current.map((m) => (m.id === PENDING ? { ...m, steps: [...m.steps, event.step] } : m)),
        );
        break;
      case "provider":
        setProviderLabel(`${event.provider_name} · ${event.model}`);
        setMessages((current) =>
          current.map((m) =>
            m.id === PENDING ? { ...m, provider: event.provider, model: event.model } : m,
          ),
        );
        break;
      case "delta":
        setMessages((current) =>
          current.map((m) => (m.id === PENDING ? { ...m, content: m.content + event.text } : m)),
        );
        break;
      case "reset":
        setMessages((current) =>
          current.map((m) => (m.id === PENDING ? { ...m, content: "" } : m)),
        );
        break;
      case "assistant_message":
        setMessages((current) => current.map((m) => (m.id === PENDING ? event.message : m)));
        break;
      case "error":
        if (event.assistant_message) {
          const message = event.assistant_message;
          setMessages((current) => current.map((m) => (m.id === PENDING ? message : m)));
        } else {
          setError(event.message);
          setMessages((current) => current.filter((m) => m.id !== PENDING));
        }
        break;
    }
  }, []);

  const stream = useCallback(
    async (path: string, body: unknown) => {
      controller.current?.abort();
      const abort = new AbortController();
      controller.current = abort;
      setStreaming(true);
      setError("");
      setProviderLabel("");
      try {
        for await (const event of sseEvents<StreamEvent>(path, body, abort.signal)) {
          apply(event);
        }
      } catch (err) {
        setError((err as Error).message);
        setMessages((current) => current.filter((m) => m.id !== PENDING));
      } finally {
        if (abort.signal.aborted) {
          // Stopped by the user: keep what was written, marked as stopped.
          setMessages((current) =>
            current
              .filter((m) => !(m.id === PENDING && !m.content))
              .map((m) =>
                m.id === PENDING ? { ...m, id: `stopped-${Date.now()}`, status: "stopped" } : m,
              ),
          );
        }
        if (controller.current === abort) controller.current = null;
        setStreaming(false);
        void refreshThreads();
      }
    },
    [apply, refreshThreads],
  );

  const ensureThread = useCallback(
    async (language: "english" | "urdu"): Promise<Thread> => {
      if (thread) return thread;
      const created = await api<Thread>("/api/chat/threads", jsonBody({ language }));
      const full = { ...created, messages: [] };
      activeId.current = created.id;
      setThread(full);
      window.history.replaceState(null, "", `/assistant?thread=${created.id}`);
      return full;
    },
    [thread],
  );

  const send = useCallback(
    async (content: string, image: string | null, language: "english" | "urdu") => {
      try {
        const active = await ensureThread(language);
        await stream(`/api/chat/threads/${active.id}/messages`, { content, image });
      } catch (err) {
        setError((err as Error).message);
      }
    },
    [ensureThread, stream],
  );

  const edit = useCallback(
    async (messageId: string, content: string) => {
      if (!thread) return;
      await stream(`/api/chat/threads/${thread.id}/messages/${messageId}/edit`, { content });
    },
    [stream, thread],
  );

  const regenerate = useCallback(async () => {
    if (!thread) return;
    await stream(`/api/chat/threads/${thread.id}/regenerate`, {});
  }, [stream, thread]);

  const stop = useCallback(() => controller.current?.abort(), []);

  const rename = useCallback(
    async (id: string, title: string) => {
      await api(`/api/chat/threads/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title }),
      });
      if (thread?.id === id) setThread({ ...thread, title });
      void refreshThreads();
    },
    [refreshThreads, thread],
  );

  const setLanguage = useCallback(
    async (language: "english" | "urdu") => {
      if (!thread) return;
      setThread({ ...thread, language });
      await api(`/api/chat/threads/${thread.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ language }),
      });
    },
    [thread],
  );

  const remove = useCallback(
    async (id: string) => {
      await api(`/api/chat/threads/${id}`, { method: "DELETE" });
      if (thread?.id === id) {
        setThread(null);
        setMessages([]);
        window.history.replaceState(null, "", "/assistant");
      }
      void refreshThreads();
    },
    [refreshThreads, thread],
  );

  return {
    threads,
    thread,
    messages,
    streaming,
    providerLabel,
    error,
    loadingThread,
    setError,
    refreshThreads,
    openThread,
    send,
    edit,
    regenerate,
    stop,
    rename,
    remove,
    setLanguage,
  };
}
