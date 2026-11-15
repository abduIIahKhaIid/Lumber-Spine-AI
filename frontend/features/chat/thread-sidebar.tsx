"use client";

import { useEffect, useState } from "react";
import clsx from "clsx";
import { Check, MessageSquarePlus, Pencil, Search, Trash2, X } from "lucide-react";
import type { ThreadSummary } from "./types";

function groupLabel(iso: string): string {
  const date = new Date(iso);
  const today = new Date();
  const start = new Date(today.getFullYear(), today.getMonth(), today.getDate()).getTime();
  const day = 86_400_000;
  const time = date.getTime();
  if (time >= start) return "Today";
  if (time >= start - day) return "Yesterday";
  if (time >= start - 7 * day) return "Previous 7 days";
  if (time >= start - 30 * day) return "Previous 30 days";
  return date.toLocaleDateString(undefined, { month: "long", year: "numeric" });
}

export default function ThreadSidebar({
  threads,
  activeId,
  onOpen,
  onNew,
  onSearch,
  onRename,
  onDelete,
  className,
}: {
  threads: ThreadSummary[];
  activeId?: string;
  onOpen: (id: string) => void;
  onNew: () => void;
  onSearch: (query: string) => void;
  onRename: (id: string, title: string) => void;
  onDelete: (id: string) => void;
  className?: string;
}) {
  const [query, setQuery] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");

  useEffect(() => {
    const timer = setTimeout(() => onSearch(query.trim()), 250);
    return () => clearTimeout(timer);
  }, [query, onSearch]);

  const groups: [string, ThreadSummary[]][] = [];
  for (const thread of threads) {
    const label = groupLabel(thread.updated);
    const group = groups.find(([name]) => name === label);
    if (group) group[1].push(thread);
    else groups.push([label, [thread]]);
  }

  return (
    <aside className={clsx("flex min-h-0 flex-col border-r border-rule bg-[#e6eaef]", className)}>
      <div className="space-y-2 p-3">
        <button type="button" onClick={onNew} className="btn btn-primary w-full justify-start">
          <MessageSquarePlus size={18} /> New chat
        </button>
        <label className="relative block">
          <span className="sr-only">Search conversations</span>
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-graphite" />
          <input
            className="field pl-9"
            placeholder="Search conversations"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>
      </div>
      <nav className="min-h-0 flex-1 overflow-y-auto px-2 pb-4" aria-label="Conversation history">
        {threads.length === 0 && (
          <p className="px-3 py-6 text-sm text-graphite">
            {query ? "No conversation matches that search." : "Your conversations appear here."}
          </p>
        )}
        {groups.map(([label, items]) => (
          <div key={label} className="mt-3">
            <h3 className="px-3 pb-1 text-xs font-semibold text-graphite">{label}</h3>
            <ul>
              {items.map((thread) => (
                <li key={thread.id} className="group relative">
                  {editing === thread.id ? (
                    <form
                      className="flex items-center gap-1 px-1 py-1"
                      onSubmit={(e) => {
                        e.preventDefault();
                        if (draft.trim()) onRename(thread.id, draft.trim());
                        setEditing(null);
                      }}
                    >
                      <input
                        autoFocus
                        className="field py-1.5"
                        value={draft}
                        maxLength={120}
                        onChange={(e) => setDraft(e.target.value)}
                        onKeyDown={(e) => e.key === "Escape" && setEditing(null)}
                      />
                      <button className="rounded p-1.5 hover:bg-paper" aria-label="Save title">
                        <Check size={16} />
                      </button>
                      <button
                        type="button"
                        className="rounded p-1.5 hover:bg-paper"
                        aria-label="Cancel"
                        onClick={() => setEditing(null)}
                      >
                        <X size={16} />
                      </button>
                    </form>
                  ) : (
                    <>
                      <button
                        type="button"
                        onClick={() => onOpen(thread.id)}
                        aria-current={thread.id === activeId ? "page" : undefined}
                        className={clsx(
                          "w-full truncate rounded-lg py-2 pl-3 pr-16 text-left text-sm",
                          thread.id === activeId
                            ? "bg-paper font-semibold text-ink shadow-sm"
                            : "text-ink/80 hover:bg-paper/70",
                        )}
                      >
                        {thread.has_case && (
                          <span className="mr-1.5 inline-block h-2 w-2 rounded-full bg-cobalt align-middle" />
                        )}
                        {thread.title}
                      </button>
                      <span className="absolute right-1 top-1/2 hidden -translate-y-1/2 gap-0.5 group-focus-within:flex group-hover:flex">
                        <button
                          type="button"
                          className="rounded p-1.5 text-graphite hover:bg-bone hover:text-ink"
                          aria-label={`Rename ${thread.title}`}
                          onClick={() => {
                            setDraft(thread.title);
                            setEditing(thread.id);
                          }}
                        >
                          <Pencil size={14} />
                        </button>
                        <button
                          type="button"
                          className="rounded p-1.5 text-graphite hover:bg-bone hover:text-sev-severe-ink"
                          aria-label={`Delete ${thread.title}`}
                          onClick={() => {
                            if (window.confirm(`Delete "${thread.title}"?`)) onDelete(thread.id);
                          }}
                        >
                          <Trash2 size={14} />
                        </button>
                      </span>
                    </>
                  )}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </nav>
    </aside>
  );
}
