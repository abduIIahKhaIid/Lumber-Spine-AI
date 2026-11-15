export type Step = {
  provider: string;
  model: string;
  status: "ok" | "failed" | "skipped";
  detail: string;
  ms: number;
};

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
};

export type ThreadSummary = {
  id: string;
  title: string;
  created: string;
  updated: string;
  language: "english" | "urdu";
  has_case: boolean;
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
  | { type: "reset" }
  | { type: "assistant_message"; message: ChatMessage }
  | { type: "error"; message: string; assistant_message?: ChatMessage }
  | { type: "truncated"; after: string }
  | { type: "done" };

export type ProviderStatus = {
  configured: Record<string, boolean>;
  chain: { provider: string; model: string; label: string }[];
  cooldowns: Record<string, number>;
};
