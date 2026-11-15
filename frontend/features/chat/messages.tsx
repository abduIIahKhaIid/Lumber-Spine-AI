"use client";

import { useState } from "react";
import clsx from "clsx";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  AlertCircle,
  Check,
  ChevronDown,
  CircleSlash,
  Copy,
  Loader2,
  Pencil,
  RefreshCw,
  SkipForward,
} from "lucide-react";
import { SpineMark } from "@/components/app-shell";
import type { ChatMessage, Step } from "./types";

const PROVIDER = { groq: "Groq", gemini: "Gemini", ollama: "Ollama" } as Record<string, string>;

function StepIcon({ step }: { step: Step }) {
  if (step.status === "ok") return <Check size={14} className="text-sev-normal-ink" />;
  if (step.status === "skipped") return <SkipForward size={14} className="text-graphite" />;
  return <CircleSlash size={14} className="text-sev-severe-ink" />;
}

/** Chainlit-style step disclosure: which providers were tried and why one was skipped. */
function Steps({ message }: { message: ChatMessage }) {
  const [open, setOpen] = useState(false);
  const streaming = message.status === "streaming";
  const failures = message.steps.filter((s) => s.status !== "ok").length;
  const current = message.provider ? `${PROVIDER[message.provider] ?? message.provider}` : "";
  if (!streaming && message.steps.length === 0) return null;
  const summary = streaming
    ? current
      ? `Using ${current}`
      : "Thinking"
    : `Used ${current || "assistant"}${failures ? `, after ${failures} fallback${failures > 1 ? "s" : ""}` : ""}`;
  return (
    <div className="mb-2">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        className="inline-flex items-center gap-1.5 rounded-md py-0.5 text-sm text-graphite hover:text-ink"
      >
        {streaming ? <Loader2 size={14} className="animate-spin" /> : null}
        <span>{summary}</span>
        <ChevronDown size={14} className={clsx("transition-transform", open && "rotate-180")} />
      </button>
      {open && (
        <ol className="mt-1.5 space-y-1 border-l-2 border-rule pl-3 text-sm">
          {message.steps.map((step, index) => (
            <li key={index} className="flex items-center gap-2">
              <StepIcon step={step} />
              <span className="font-medium">{PROVIDER[step.provider] ?? step.provider}</span>
              <span className="text-graphite">{step.model}</span>
              <span className="text-graphite">
                {step.detail}
                {step.ms ? `, ${(step.ms / 1000).toFixed(1)} s` : ""}
              </span>
            </li>
          ))}
          {streaming && message.provider && (
            <li className="flex items-center gap-2">
              <Loader2 size={14} className="animate-spin text-cobalt" />
              <span className="font-medium">{current}</span>
              <span className="text-graphite">{message.model}</span>
            </li>
          )}
        </ol>
      )}
    </div>
  );
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      aria-label="Copy answer"
      title="Copy"
      className="rounded-md p-1.5 text-graphite hover:bg-paper hover:text-ink"
      onClick={async () => {
        await navigator.clipboard.writeText(text);
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      }}
    >
      {copied ? <Check size={16} /> : <Copy size={16} />}
    </button>
  );
}

function UserMessage({
  message,
  disabled,
  onEdit,
}: {
  message: ChatMessage;
  disabled: boolean;
  onEdit: (id: string, content: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(message.content);
  if (editing) {
    return (
      <form
        className="ml-auto w-full max-w-[85%] rounded-2xl border border-cobalt bg-paper p-3"
        onSubmit={(e) => {
          e.preventDefault();
          if (!draft.trim()) return;
          setEditing(false);
          onEdit(message.id, draft.trim());
        }}
      >
        <label className="sr-only" htmlFor={`edit-${message.id}`}>
          Edit message
        </label>
        <textarea
          id={`edit-${message.id}`}
          autoFocus
          rows={Math.min(8, Math.max(2, draft.split("\n").length))}
          className="w-full resize-none bg-transparent outline-none"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Escape") setEditing(false);
          }}
        />
        <p className="mt-1 text-xs text-graphite">
          Sending replaces this message and removes the replies after it.
        </p>
        <div className="mt-2 flex justify-end gap-2">
          <button type="button" className="btn btn-quiet py-1.5" onClick={() => setEditing(false)}>
            Cancel
          </button>
          <button className="btn btn-primary py-1.5" disabled={!draft.trim()}>
            Send
          </button>
        </div>
      </form>
    );
  }
  return (
    <div className="group ml-auto flex max-w-[85%] items-start gap-1">
      <button
        type="button"
        disabled={disabled}
        onClick={() => {
          setDraft(message.content);
          setEditing(true);
        }}
        aria-label="Edit message"
        title="Edit"
        className="mt-2 rounded-md p-1.5 text-graphite opacity-0 hover:bg-paper hover:text-ink focus:opacity-100 group-hover:opacity-100 disabled:hidden"
      >
        <Pencil size={15} />
      </button>
      <div className="rounded-2xl rounded-br-md bg-[#dde4ec] px-4 py-2.5">
        {message.image && (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={`data:image/jpeg;base64,${message.image}`}
            alt="Attached"
            className="mb-2 max-h-56 rounded-lg"
          />
        )}
        <p className="whitespace-pre-wrap leading-relaxed" dir="auto">
          {message.content}
        </p>
        {message.edited && <p className="mt-1 text-right text-xs text-graphite">edited</p>}
      </div>
    </div>
  );
}

function AssistantMessage({
  message,
  isLast,
  disabled,
  onRegenerate,
}: {
  message: ChatMessage;
  isLast: boolean;
  disabled: boolean;
  onRegenerate: () => void;
}) {
  const streaming = message.status === "streaming";
  return (
    <div className="flex gap-3">
      <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-ink">
        <SpineMark className="h-4 w-4 text-white" />
      </span>
      <div className="min-w-0 flex-1">
        <Steps message={message} />
        {message.status === "error" ? (
          <p className="flex items-start gap-2 rounded-xl bg-sev-severe/10 p-3 text-sev-severe-ink">
            <AlertCircle size={18} className="mt-0.5 shrink-0" />
            {message.content}
          </p>
        ) : (
          <div className="prose-chat" dir="auto">
            {message.content ? (
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
            ) : streaming ? (
              <span className="inline-flex gap-1 py-2" aria-label="Writing">
                <span className="h-2 w-2 animate-pulse rounded-full bg-graphite" />
                <span className="h-2 w-2 animate-pulse rounded-full bg-graphite [animation-delay:150ms]" />
                <span className="h-2 w-2 animate-pulse rounded-full bg-graphite [animation-delay:300ms]" />
              </span>
            ) : null}
          </div>
        )}
        {!streaming && (
          <div className="mt-1 flex items-center gap-1">
            {message.content && message.status !== "error" && <CopyButton text={message.content} />}
            {isLast && (
              <button
                type="button"
                disabled={disabled}
                onClick={onRegenerate}
                aria-label="Regenerate answer"
                title="Regenerate"
                className="rounded-md p-1.5 text-graphite hover:bg-paper hover:text-ink disabled:opacity-40"
              >
                <RefreshCw size={16} />
              </button>
            )}
            {message.status === "stopped" && <span className="text-xs text-graphite">Stopped</span>}
          </div>
        )}
      </div>
    </div>
  );
}

export default function MessageList({
  messages,
  streaming,
  onEdit,
  onRegenerate,
}: {
  messages: ChatMessage[];
  streaming: boolean;
  onEdit: (id: string, content: string) => void;
  onRegenerate: () => void;
}) {
  const lastAssistant = [...messages].reverse().find((m) => m.role === "assistant")?.id;
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 px-4 py-6">
      {messages.map((message) =>
        message.role === "user" ? (
          <UserMessage
            key={message.id}
            message={message}
            disabled={streaming || message.id.startsWith("stopped")}
            onEdit={onEdit}
          />
        ) : (
          <AssistantMessage
            key={message.id}
            message={message}
            isLast={message.id === lastAssistant}
            disabled={streaming}
            onRegenerate={onRegenerate}
          />
        ),
      )}
    </div>
  );
}
