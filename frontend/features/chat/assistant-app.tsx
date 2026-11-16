"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import clsx from "clsx";
import { Languages, PanelLeft, X } from "lucide-react";
import { api } from "@/lib/api";
import { SpineMark } from "@/components/app-shell";
import CaseAttachment from "./case-attachment";
import Composer from "./composer";
import MessageList from "./messages";
import ThreadSidebar from "./thread-sidebar";
import type { ProviderStatus } from "./types";
import { useChat } from "./use-chat";

const CASE_STARTERS = [
  { title: "Explain this result", prompt: "Explain this scan result in simple words." },
  {
    title: "What matters most",
    prompt: "Which level in this result should my doctor look at first, and why?",
  },
  {
    title: "Show the worst level",
    prompt: "Show me the box and focus map of the most severe level.",
  },
  {
    title: "Urdu mein samjhao",
    prompt: "Is result ko aasaan Urdu mein samjhao.",
  },
];

const STARTERS = [
  {
    title: "Explain a grade",
    prompt: "What is the difference between moderate and severe spinal canal stenosis on MRI?",
  },
  {
    title: "Foraminal narrowing",
    prompt: "How does neural foraminal narrowing at L4/L5 relate to leg symptoms?",
  },
  {
    title: "Red flags",
    prompt: "Which lumbar spine symptoms need urgent medical attention?",
  },
  {
    title: "Urdu mein samjhao",
    prompt: "Subarticular stenosis kya hota hai? Aasaan Urdu mein samjhao.",
  },
];

export default function AssistantApp() {
  const params = useSearchParams();
  const router = useRouter();
  const chat = useChat(params.get("thread"));
  const [sidebar, setSidebar] = useState(false);
  const [language, setLanguageState] = useState<"english" | "urdu">("english");
  const [draft, setDraft] = useState<string | undefined>(undefined);
  const [status, setStatus] = useState<ProviderStatus | null>(null);
  const scroller = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api<ProviderStatus>("/api/chat/providers")
      .then(setStatus)
      .catch(() => setStatus(null));
  }, []);

  useEffect(() => {
    if (chat.thread) setLanguageState(chat.thread.language);
  }, [chat.thread]);

  useEffect(() => {
    const element = scroller.current;
    if (!element) return;
    const nearBottom = element.scrollHeight - element.scrollTop - element.clientHeight < 240;
    if (nearBottom || chat.streaming) element.scrollTop = element.scrollHeight;
  }, [chat.messages, chat.streaming]);

  const open = useCallback(
    (id: string | null) => {
      setSidebar(false);
      router.replace(id ? `/assistant?thread=${id}` : "/assistant");
    },
    [router],
  );

  const changeLanguage = (value: "english" | "urdu") => {
    setLanguageState(value);
    void chat.setLanguage(value);
  };

  const empty = chat.messages.length === 0 && !chat.loadingThread;
  const chain = status?.chain ?? [];

  return (
    <div className="flex h-full min-h-0">
      <ThreadSidebar
        className={clsx(
          "w-72 shrink-0",
          sidebar ? "fixed inset-y-16 left-0 z-40 flex shadow-xl" : "hidden lg:flex",
        )}
        threads={chat.threads}
        activeId={chat.thread?.id}
        onOpen={open}
        onNew={() => open(null)}
        onSearch={chat.refreshThreads}
        onRename={chat.rename}
        onDelete={chat.remove}
      />
      <section className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center gap-2 border-b border-rule px-3 sm:px-4">
          <button
            type="button"
            className="rounded-lg p-2 hover:bg-paper lg:hidden"
            aria-label={sidebar ? "Hide conversations" : "Show conversations"}
            onClick={() => setSidebar(!sidebar)}
          >
            {sidebar ? <X size={18} /> : <PanelLeft size={18} />}
          </button>
          <h1 className="min-w-0 truncate font-semibold">{chat.thread?.title ?? "New chat"}</h1>
          <div className="ml-auto flex items-center gap-2">
            <span className="hidden text-xs text-graphite md:inline" title="Fallback order">
              {chat.streaming && chat.providerLabel
                ? chat.providerLabel
                : chain.length
                  ? `${chain.length} model${chain.length > 1 ? "s" : ""} in fallback order`
                  : status
                    ? "No AI provider configured"
                    : ""}
            </span>
            <label className="flex items-center gap-1.5 rounded-lg border border-rule bg-paper px-2 py-1 text-sm">
              <Languages size={15} className="text-graphite" />
              <span className="sr-only">Answer language</span>
              <select
                value={language}
                onChange={(e) => changeLanguage(e.target.value as "english" | "urdu")}
                className="bg-transparent outline-none"
              >
                <option value="english">English</option>
                <option value="urdu">اردو</option>
              </select>
            </label>
          </div>
        </header>
        <div ref={scroller} className="min-h-0 flex-1 overflow-y-auto">
          {empty && chat.thread?.case_context ? (
            <div className="mx-auto w-full max-w-3xl px-4 py-6">
              <CaseAttachment context={chat.thread.case_context} />
              <p className="mt-8 text-center text-graphite">
                The result is attached. Ask anything about it, or start with one of these.
              </p>
              <div className="mt-4 grid gap-3 sm:grid-cols-2">
                {CASE_STARTERS.map((starter) => (
                  <button
                    key={starter.title}
                    type="button"
                    onClick={() => chat.send(starter.prompt, null, language)}
                    className="rounded-xl border border-rule bg-paper p-4 text-left hover:border-cobalt"
                  >
                    <span className="font-semibold">{starter.title}</span>
                    <span className="mt-1 block text-sm text-graphite" dir="auto">
                      {starter.prompt}
                    </span>
                  </button>
                ))}
              </div>
            </div>
          ) : empty ? (
            <div className="mx-auto flex h-full max-w-3xl flex-col items-center justify-center px-4 py-10 text-center">
              <SpineMark className="h-12 w-10 text-ink" />
              <h2 className="mt-4 text-2xl font-bold tracking-tight">
                Ask about lumbar MRI findings
              </h2>
              <p className="mt-2 max-w-md text-graphite">
                Questions about grades, levels and symptoms. Attach a DICOM file or a series ZIP
                with the paperclip and the SpineScope models will analyse it here.
              </p>
              <div className="mt-8 grid w-full gap-3 sm:grid-cols-2">
                {STARTERS.map((starter) => (
                  <button
                    key={starter.title}
                    type="button"
                    onClick={() => chat.send(starter.prompt, null, language)}
                    className="rounded-xl border border-rule bg-paper p-4 text-left hover:border-cobalt"
                  >
                    <span className="font-semibold">{starter.title}</span>
                    <span className="mt-1 block text-sm text-graphite" dir="auto">
                      {starter.prompt}
                    </span>
                  </button>
                ))}
              </div>
              {status && chain.length === 0 && (
                <p className="mt-6 rounded-lg bg-sev-moderate/10 p-3 text-sm text-sev-moderate-ink">
                  Add GROQ_API_KEY, GEMINI_API_KEY or OLLAMA_BASE_URL to backend/.env and restart
                  the backend to enable answers.
                </p>
              )}
            </div>
          ) : (
            <MessageList
              messages={chat.messages}
              streaming={chat.streaming}
              attachment={chat.thread?.case_context}
              onEdit={chat.edit}
              onRegenerate={chat.regenerate}
            />
          )}
        </div>
        {chat.error && (
          <p
            role="alert"
            className="mx-auto mb-2 w-full max-w-3xl rounded-lg bg-sev-severe/10 px-4 py-2 text-sm text-sev-severe-ink"
          >
            {chat.error}
          </p>
        )}
        <Composer
          streaming={chat.streaming}
          onSend={(text, image, scan) => {
            setDraft(undefined);
            void chat.send(text, image, language, scan);
          }}
          onStop={chat.stop}
          initial={draft}
          placeholder={
            language === "urdu" ? "اپنا سوال لکھیں" : "Ask about a level, a grade or a symptom"
          }
        />
      </section>
    </div>
  );
}
