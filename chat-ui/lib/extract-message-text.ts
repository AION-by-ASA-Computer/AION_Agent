import type { TurnSegment } from "@/lib/sse/types";

/** Plain text suitable for clipboard from an assistant message. */
export function extractAssistantCopyText(msg: {
  content: string;
  segments?: TurnSegment[];
  reasoning?: string;
}): string {
  const parts: string[] = [];
  if (msg.segments?.length) {
    for (const seg of msg.segments) {
      if (seg.kind === "text" && seg.content.trim()) parts.push(seg.content.trim());
      else if (seg.kind === "reasoning" && seg.content.trim()) parts.push(seg.content.trim());
    }
  } else {
    if (msg.reasoning?.trim()) parts.push(msg.reasoning.trim());
    if (msg.content.trim()) parts.push(msg.content.trim());
  }
  const joined = parts.join("\n\n").trim();
  return joined || msg.content.trim();
}
