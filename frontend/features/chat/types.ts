export type Step = {
  provider: string;
  model: string;
  status: "ok" | "failed" | "skipped";
  detail: string;
  ms: number;
};

export type ToolCall = {
  id: string;
  name: "analyze_scan" | "show_images" | string;
  label: string;
  status: "running" | "done" | "error";
  progress: number;
  message: string;
  seconds?: number;
  model_seconds?: number | null;
  queue_seconds?: number | null;
  /** Small JPEG of the attached scan, sent only while the analysis runs. */
  preview?: string;
};

export type ImageElement = { type: "image"; key: string; caption: string; data: string };

export type ScanAttachment = { id?: string; name: string; kind: "single" | "multi" };

export type ChatMessage = {
  id: string;
  thread_id?: string;
  seq?: number;
  role: "user" | "assistant";
  content: string;
  image?: string | null;
  provider?: string | null;
  model?: string | null;
  status: "complete" | "error" | "stopped" | "streaming";
  steps: Step[];
  created?: string;
  edited?: boolean;
  reasoning?: string;
  reasoning_seconds?: number;
  tools?: ToolCall[];
  elements?: ImageElement[];
  attachment?: ScanAttachment;
  /** Stable React key: a streamed answer keeps its key when the saved message replaces it. */
  client_key?: string;
};

export type ThreadSummary = {
  id: string;
  title: string;
  created: string;
  updated: string;
  language: "english" | "urdu";
  has_case: boolean;
  /** An answer is being written on the server (it continues if the page is closed). */
  running?: boolean;
};

export type Thread = ThreadSummary & {
  case_context: import("./case-attachment").CaseContext | null;
  messages: ChatMessage[];
};

export type StreamEvent =
  | { type: "user_message"; message: ChatMessage; replaces?: string }
  | { type: "title"; title: string }
  | { type: "thinking" }
  | { type: "step"; step: Step }
  | { type: "provider"; provider: string; provider_name: string; model: string }
  | { type: "delta"; text: string }
  | { type: "reasoning"; text: string }
  | { type: "reasoning_done"; seconds: number }
  | { type: "tool"; tool: ToolCall }
  | { type: "elements"; elements: ImageElement[] }
  | { type: "case"; case: import("./case-attachment").CaseContext }
  | { type: "reset" }
  | { type: "assistant_message"; message: ChatMessage }
  | { type: "error"; message: string; assistant_message?: ChatMessage }
  | { type: "truncated"; after: string }
  | { type: "stopped" }
  | { type: "done" };

export type ProviderStatus = {
  configured: Record<string, boolean>;
  chain: { provider: string; model: string; label: string }[];
  cooldowns: Record<string, number>;
};
