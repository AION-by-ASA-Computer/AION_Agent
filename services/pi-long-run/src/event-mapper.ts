import type { AgentSessionEvent } from "@earendil-works/pi-coding-agent";
import { StreamSanitizer } from "./stream-sanitize.js";

export type AionStreamChunk =
  | { type: "token"; content: string }
  | { type: "reasoning"; reasoning: string }
  | {
      type: "tool_event";
      event: {
        type: "tool_start" | "tool_end";
        id?: string;
        name?: string;
        input?: unknown;
        result?: string;
        error?: boolean;
      };
    }
  | { type: "context_compacting_start" }
  | { type: "context_compacting_end" }
  | { type: "error"; content: string }
  | { type: "done" };

/** Extract plain text from Pi AgentToolResult or legacy string payloads. */
export function toolResultToText(result: unknown): string {
  if (result == null) return "";
  if (typeof result === "string") return result;
  if (typeof result === "object") {
    const blocks = (result as { content?: unknown }).content;
    if (Array.isArray(blocks)) {
      const parts: string[] = [];
      for (const block of blocks) {
        if (
          block &&
          typeof block === "object" &&
          (block as { type?: string }).type === "text" &&
          typeof (block as { text?: unknown }).text === "string"
        ) {
          parts.push((block as { text: string }).text);
        }
      }
      if (parts.length) return parts.join("");
    }
  }
  try {
    return JSON.stringify(result);
  } catch {
    return String(result);
  }
}

/** Detect structured AION tool failures returned as plain text JSON. */
export function toolResultLooksLikeError(text: string): boolean {
  const trimmed = String(text || "").trim();
  if (!trimmed.startsWith("{")) return false;
  try {
    const data = JSON.parse(trimmed) as { ok?: boolean; error?: string };
    if (data.ok === false) return true;
    if (
      data.error === "missing_arguments" ||
      data.error === "tool_args_truncated" ||
      data.error === "circuit_breaker"
    ) {
      return true;
    }
  } catch {
    return false;
  }
  return false;
}

export function mapPiEventToAion(event: AgentSessionEvent): AionStreamChunk[] {
  const out: AionStreamChunk[] = [];

  if (event.type === "message_end") {
    const msg = event.message as {
      role?: string;
      stopReason?: string;
      errorMessage?: string;
    };
    if (
      msg.role === "assistant" &&
      msg.stopReason === "error" &&
      msg.errorMessage
    ) {
      out.push({ type: "error", content: msg.errorMessage });
    }
    return out;
  }

  if (event.type === "message_update") {
    const inner = event.assistantMessageEvent;
    if (inner.type === "text_delta") {
      out.push({ type: "token", content: inner.delta });
    } else if (inner.type === "thinking_delta") {
      out.push({ type: "reasoning", reasoning: inner.delta });
    }
    return out;
  }

  if (event.type === "tool_execution_start") {
    out.push({
      type: "tool_event",
      event: {
        type: "tool_start",
        id: event.toolCallId,
        name: event.toolName,
        input: event.args,
      },
    });
    return out;
  }

  if (event.type === "tool_execution_end") {
    const resultText = toolResultToText(event.result);
    if (event.isError || toolResultLooksLikeError(resultText)) {
      out.push({
        type: "tool_event",
        event: {
          type: "tool_error",
          id: event.toolCallId,
          name: event.toolName,
          error: resultText,
        },
      });
      return out;
    }
    out.push({
      type: "tool_event",
      event: {
        type: "tool_end",
        id: event.toolCallId,
        name: event.toolName,
        output: resultText,
      },
    });
    return out;
  }

  if (event.type === "compaction_start") {
    out.push({ type: "context_compacting_start" });
    return out;
  }

  if (event.type === "compaction_end") {
    out.push({ type: "context_compacting_end" });
    return out;
  }

  if (event.type === "auto_retry_start") {
    out.push({
      type: "error",
      content: `LLM retry ${event.attempt}/${event.maxAttempts}: ${event.errorMessage}`,
    });
  }

  return out;
}

export type AionStreamMapper = {
  map: (event: AgentSessionEvent) => AionStreamChunk[];
  flush: () => AionStreamChunk[];
};

/** Per-prompt mapper that strips leaked Qwen tool/thinking markup from token chunks. */
export function createAionStreamMapper(): AionStreamMapper {
  const sanitizer = new StreamSanitizer();
  return {
    map(event: AgentSessionEvent) {
      const chunks = mapPiEventToAion(event);
      const out: AionStreamChunk[] = [];
      for (const chunk of chunks) {
        if (chunk.type === "token") {
          const clean = sanitizer.filter(chunk.content);
          if (clean) out.push({ type: "token", content: clean });
          continue;
        }
        out.push(chunk);
      }
      return out;
    },
    flush() {
      const rest = sanitizer.flush();
      return rest ? [{ type: "token", content: rest }] : [];
    },
  };
}
