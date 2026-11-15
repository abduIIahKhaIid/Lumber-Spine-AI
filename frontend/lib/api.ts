/** Backend origin. Set NEXT_PUBLIC_API_ORIGIN at build time when the API is elsewhere. */
export const apiOrigin = (process.env.NEXT_PUBLIC_API_ORIGIN || "http://localhost:8000").replace(
  /\/$/,
  "",
);

export function apiUrl(path: string): string {
  return `${apiOrigin}${path.startsWith("/") ? path : `/${path}`}`;
}

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function errorMessage(response: Response): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail) && body.detail[0]?.msg) return body.detail[0].msg;
  } catch {
    /* not JSON */
  }
  if (response.status === 429) return "Too many requests. Wait a moment and try again.";
  return `Request failed (${response.status}).`;
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(apiUrl(path), init);
  } catch {
    throw new ApiError("The analysis server is not reachable. Start the backend and try again.", 0);
  }
  if (!response.ok) throw new ApiError(await errorMessage(response), response.status);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export function jsonBody(body: unknown, headers: Record<string, string> = {}): RequestInit {
  return {
    method: "POST",
    headers: { "Content-Type": "application/json", ...headers },
    body: JSON.stringify(body),
  };
}

/** Parse a POST server-sent-event stream into JSON events. */
export async function* sseEvents<T>(
  path: string,
  body: unknown,
  signal: AbortSignal,
): AsyncGenerator<T> {
  let response: Response;
  try {
    response = await fetch(apiUrl(path), {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify(body ?? {}),
      signal,
    });
  } catch (error) {
    if ((error as Error).name === "AbortError") return;
    throw new ApiError("The assistant server is not reachable.", 0);
  }
  if (!response.ok || !response.body)
    throw new ApiError(await errorMessage(response), response.status);
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      let end: number;
      while ((end = buffer.indexOf("\n\n")) >= 0) {
        const block = buffer.slice(0, end);
        buffer = buffer.slice(end + 2);
        const data = block
          .split("\n")
          .filter((line) => line.startsWith("data:"))
          .map((line) => line.slice(5).trimStart())
          .join("\n");
        if (data) yield JSON.parse(data) as T;
      }
      if (done) break;
    }
  } catch (error) {
    if ((error as Error).name !== "AbortError") throw error;
  } finally {
    reader.releaseLock();
  }
}
