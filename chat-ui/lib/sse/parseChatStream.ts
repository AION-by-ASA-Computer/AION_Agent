import type { ChatChunk } from "./types";

/** Normalize CRLF / lone CR to LF for SSE framing. */
function normalizeSseText(s: string): string {
  return s.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
}

/**
 * Parses sse-starlette stream: blocks separated by blank line, lines like `event:` / `data:`.
 */
function parseSseBlock(block: string): { event: string; data: string } | null {
  let event = "message";
  const dataLines: string[] = [];
  for (const raw of normalizeSseText(block).split("\n")) {
    const line = raw.replace(/\s+$/, "");
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
  }
  if (!dataLines.length) return null;
  return { event, data: dataLines.join("\n") };
}

export async function* iterateSseJson(body: ReadableStream<Uint8Array> | null): AsyncGenerator<Record<string, unknown>> {
  if (!body) return;
  const reader = body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += normalizeSseText(dec.decode(value, { stream: true }));
      let idx: number;
      while ((idx = buf.indexOf("\n\n")) >= 0) {
        const block = buf.slice(0, idx).trim();
        buf = buf.slice(idx + 2);
        if (!block) continue;
        const parsed = parseSseBlock(block);
        if (!parsed) continue;
        try {
          const obj = JSON.parse(parsed.data) as Record<string, unknown>;
          if (obj && typeof obj === "object") yield obj;
        } catch {
          /* skip */
        }
      }
    }
    const tail = buf.trim();
    if (tail) {
      const parsed = parseSseBlock(tail);
      if (parsed) {
        try {
          const obj = JSON.parse(parsed.data) as Record<string, unknown>;
          if (obj && typeof obj === "object") yield obj;
        } catch {
          /* skip */
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}

/**
 * Maps SSE JSON payloads to ChatChunk. Backend error frames often use `{ "error": "..." }` without `type`.
 */
export async function* iterateChatChunks(body: ReadableStream<Uint8Array> | null): AsyncGenerator<ChatChunk> {
  for await (const obj of iterateSseJson(body)) {
    if ("type" in obj && typeof (obj as { type?: unknown }).type === "string") {
      yield obj as ChatChunk;
      continue;
    }
    const err = obj.error;
    if (typeof err === "string") {
      yield { type: "error", content: err };
      continue;
    }
    if (typeof obj.detail === "string") {
      yield { type: "error", content: obj.detail };
    }
  }
}
