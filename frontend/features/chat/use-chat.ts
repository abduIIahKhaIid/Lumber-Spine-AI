"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, jsonBody, sseEvents } from "@/lib/api";
import type { ChatMessage, ScanAttachment, StreamEvent, Thread, ThreadSummary } from "./types";

const PENDING = "pending-assistant";

function pendingMessage(): ChatMessage {
  return {
    id: PENDING,
    client_key: `answer-${Date.now()}`,
    role: "assistant",
    content: "",
    status: "streaming",
    steps: [],
  };
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
  const follow = useRef<(path: string, body: unknown) => Promise<void>>(async () => {});
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
      activeId.current = loaded.id;
      setThread(loaded);
      setMessages(loaded.messages);
      // The answer is still being written on the server: follow it from the start.
      if (loaded.running) void follow.current(`/api/chat/threads/${id}/stream`, null);
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

  // Answers in other conversations keep running on the server: refresh their status.
  const othersRunning = threads.some((t) => t.running && t.id !== activeId.current);
  useEffect(() => {
    if (!othersRunning) return;
    const timer = setInterval(() => void refreshThreads(), 3000);
    return () => clearInterval(timer);
  }, [othersRunning, refreshThreads]);

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
          if (current.some((m) => m.id === event.message.id)) return current; // replayed
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
          current.map((m) =>
            m.id === PENDING
              ? { ...m, content: "", reasoning: "", reasoning_seconds: undefined }
              : m,
          ),
        );
        break;
      case "reasoning":
        setMessages((current) =>
          current.map((m) =>
            m.id === PENDING ? { ...m, reasoning: (m.reasoning ?? "") + event.text } : m,
          ),
        );
        break;
      case "reasoning_done":
        setMessages((current) =>
          current.map((m) => (m.id === PENDING ? { ...m, reasoning_seconds: event.seconds } : m)),
        );
        break;
      case "tool":
        setMessages((current) =>
          current.map((m) => {
            if (m.id !== PENDING) return m;
            const tools = m.tools ?? [];
            const known = tools.some((t) => t.id === event.tool.id);
            return {
              ...m,
              tools: known
                ? tools.map((t) => (t.id === event.tool.id ? event.tool : t))
                : [...tools, event.tool],
            };
          }),
        );
        break;
      case "elements":
        setMessages((current) =>
          current.map((m) => (m.id === PENDING ? { ...m, elements: event.elements } : m)),
        );
        break;
      case "case":
        setThread((current) =>
          current ? { ...current, case_context: event.case, has_case: true } : current,
        );
        break;
      case "assistant_message":
        setMessages((current) =>
          current.map((m) =>
            m.id === PENDING ? { ...event.message, client_key: m.client_key } : m,
          ),
        );
        break;
      case "error":
        if (event.assistant_message) {
          const message = event.assistant_message;
          setMessages((current) =>
            current.map((m) => (m.id === PENDING ? { ...message, client_key: m.client_key } : m)),
          );
        } else {
          setError(event.message);
          setMessages((current) => current.filter((m) => m.id !== PENDING));
        }
        break;
    }
  }, []);

  const reload = useCallback(async (id: string) => {
    try {
      const loaded = await api<Thread>(`/api/chat/threads/${id}`);
      if (activeId.current !== id) return;
      setThread(loaded);
      setMessages(loaded.messages);
    } catch {
      /* keep what is shown */
    }
  }, []);

  /** Streams a run. Aborting only detaches this page: the server keeps writing the answer. */
  const stream = useCallback(
    async (path: string, body: unknown) => {
      controller.current?.abort();
      const abort = new AbortController();
      controller.current = abort;
      const threadId = activeId.current;
      let stopped = false;
      setStreaming(true);
      setError("");
      setProviderLabel("");
      try {
        for await (const event of sseEvents<StreamEvent>(path, body, abort.signal)) {
          if (event.type === "stopped") stopped = true;
          else apply(event);
        }
      } catch (err) {
        setError((err as Error).message);
        setMessages((current) => current.filter((m) => m.id !== PENDING));
      } finally {
        if (controller.current === abort) {
          controller.current = null;
          setStreaming(false);
          if (stopped && threadId) await reload(threadId);
        }
        void refreshThreads();
      }
    },
    [apply, refreshThreads, reload],
  );
  follow.current = stream;

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
    async (
      content: string,
      image: string | null,
      language: "english" | "urdu",
      scan: File[] | null = null,
    ) => {
      try {
        const active = await ensureThread(language);
        let attachment: ScanAttachment | null = null;
        if (scan?.length) {
          setStreaming(true);
          const form = new FormData();
          for (const file of scan) form.append("files", file);
          attachment = await api<ScanAttachment>(`/api/chat/threads/${active.id}/attachments`, {
            method: "POST",
            body: form,
          });
        }
        await stream(`/api/chat/threads/${active.id}/messages`, { content, image, attachment });
      } catch (err) {
        setError((err as Error).message);
        setStreaming(false);
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

  /** Ends the answer on the server; the partial answer is kept as "stopped". */
  const stop = useCallback(async () => {
    const id = activeId.current;
    if (!id) return;
    try {
      await api(`/api/chat/threads/${id}/stop`, { method: "POST" });
    } catch (err) {
      setError((err as Error).message);
    }
    controller.current?.abort();
    controller.current = null;
    setStreaming(false);
    await reload(id);
    void refreshThreads();
  }, [refreshThreads, reload]);

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
