"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowUp, Loader2, Paperclip, Square, X } from "lucide-react";
import { apiUrl } from "@/lib/api";

type Attachment = { name: string; data: string };

function readAsBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",", 2)[1] ?? "");
    reader.onerror = () => reject(new Error("The file could not be read."));
    reader.readAsDataURL(file);
  });
}

async function toAttachment(file: File): Promise<Attachment> {
  if (file.name.toLowerCase().endsWith(".dcm")) {
    const form = new FormData();
    form.append("file", file);
    const response = await fetch(apiUrl("/api/convert-dicom"), { method: "POST", body: form });
    if (!response.ok) throw new Error("That DICOM file could not be converted.");
    const body = (await response.json()) as { jpegBase64: string };
    return { name: file.name, data: body.jpegBase64 };
  }
  if (!/^image\/(png|jpe?g|webp)$/.test(file.type))
    throw new Error("Attach a PNG, JPEG or DICOM image.");
  if (file.size > 10 * 1024 * 1024) throw new Error("Images must be smaller than 10 MB.");
  return { name: file.name, data: await readAsBase64(file) };
}

export default function Composer({
  streaming,
  onSend,
  onStop,
  placeholder,
  initial,
}: {
  streaming: boolean;
  onSend: (text: string, image: string | null) => void;
  onStop: () => void;
  placeholder: string;
  initial?: string;
}) {
  const [text, setText] = useState(initial ?? "");
  const [attachment, setAttachment] = useState<Attachment | null>(null);
  const [preparing, setPreparing] = useState(false);
  const [error, setError] = useState("");
  const area = useRef<HTMLTextAreaElement>(null);
  const picker = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (initial !== undefined) {
      setText(initial);
      area.current?.focus();
    }
  }, [initial]);

  useEffect(() => {
    const element = area.current;
    if (!element) return;
    element.style.height = "auto";
    element.style.height = `${Math.min(element.scrollHeight, 220)}px`;
  }, [text]);

  function submit() {
    if (streaming || preparing || (!text.trim() && !attachment)) return;
    onSend(text.trim(), attachment?.data ?? null);
    setText("");
    setAttachment(null);
  }

  return (
    <div className="mx-auto w-full max-w-3xl px-4 pb-4">
      <div className="rounded-2xl border border-rule bg-paper p-2 shadow-[0_1px_2px_rgba(20,33,46,0.06)] focus-within:border-[#9aa8b6]">
        {attachment && (
          <div className="mb-2 flex items-center gap-2 rounded-xl bg-bone p-2">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={`data:image/jpeg;base64,${attachment.data}`}
              alt=""
              className="h-12 w-12 rounded-lg object-cover"
            />
            <span className="min-w-0 flex-1 truncate text-sm">{attachment.name}</span>
            <button
              type="button"
              aria-label="Remove attachment"
              className="rounded p-1 hover:bg-paper"
              onClick={() => setAttachment(null)}
            >
              <X size={16} />
            </button>
          </div>
        )}
        <label htmlFor="composer" className="sr-only">
          Message
        </label>
        <textarea
          id="composer"
          ref={area}
          rows={1}
          dir="auto"
          value={text}
          placeholder={placeholder}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              submit();
            }
          }}
          className="block max-h-[220px] w-full resize-none bg-transparent px-2 py-2 leading-relaxed outline-none focus:outline-none focus-visible:outline-none"
        />
        <div className="flex items-center gap-1">
          <button
            type="button"
            className="rounded-lg p-2 text-graphite hover:bg-bone hover:text-ink"
            aria-label="Attach an image"
            title="Attach a PNG, JPEG or DICOM image"
            onClick={() => picker.current?.click()}
            disabled={preparing}
          >
            {preparing ? <Loader2 size={18} className="animate-spin" /> : <Paperclip size={18} />}
          </button>
          <input
            ref={picker}
            type="file"
            className="sr-only"
            accept="image/png,image/jpeg,image/webp,.dcm"
            onChange={async (e) => {
              const file = e.target.files?.[0];
              e.target.value = "";
              if (!file) return;
              setError("");
              setPreparing(true);
              try {
                setAttachment(await toAttachment(file));
              } catch (err) {
                setError((err as Error).message);
              } finally {
                setPreparing(false);
              }
            }}
          />
          <span className="ml-1 hidden text-xs text-graphite sm:inline">
            Enter to send, Shift+Enter for a new line
          </span>
          {streaming ? (
            <button
              type="button"
              onClick={onStop}
              className="ml-auto flex h-9 w-9 items-center justify-center rounded-full bg-ink text-white"
              aria-label="Stop generating"
              title="Stop"
            >
              <Square size={14} fill="currentColor" />
            </button>
          ) : (
            <button
              type="button"
              onClick={submit}
              disabled={preparing || (!text.trim() && !attachment)}
              className="ml-auto flex h-9 w-9 items-center justify-center rounded-full bg-cobalt text-white disabled:bg-rule"
              aria-label="Send message"
            >
              <ArrowUp size={18} />
            </button>
          )}
        </div>
      </div>
      {error && (
        <p role="alert" className="mt-2 text-sm text-sev-severe-ink">
          {error}
        </p>
      )}
      <p className="mt-2 text-center text-xs text-graphite">
        Educational assistant. It can be wrong and does not replace a clinician.
      </p>
    </div>
  );
}
