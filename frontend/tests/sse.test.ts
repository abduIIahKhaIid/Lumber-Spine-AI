import { test } from "node:test";
import assert from "node:assert/strict";
import { sseEvents } from "../lib/api.ts";

test("SSE parser joins events split across chunks, including multi-byte text", async () => {
  const encoder = new TextEncoder();
  const bytes = encoder.encode(
    'data: {"type":"delta","text":"سلام"}\n\n: heartbeat\n\ndata: {"type":"done"}\n\n',
  );
  const chunks = [bytes.slice(0, 17), bytes.slice(17, 30), bytes.slice(30)];
  globalThis.fetch = (async () =>
    new Response(
      new ReadableStream({
        start(controller) {
          chunks.forEach((chunk) => controller.enqueue(chunk));
          controller.close();
        },
      }),
      { status: 200 },
    )) as typeof fetch;
  const events = [];
  for await (const event of sseEvents("/x", {}, new AbortController().signal)) events.push(event);
  assert.deepEqual(events, [{ type: "delta", text: "سلام" }, { type: "done" }]);
});
