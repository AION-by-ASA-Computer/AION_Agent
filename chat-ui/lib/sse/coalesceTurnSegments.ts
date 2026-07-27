import type { TurnSegment } from "./types";

/** True when assistant text was split across a reasoning block (Qwen/Pi interleaving). */
function shouldMergeTextAcrossReasoning(
  before: string,
  reasoning: string,
  after: string,
): boolean {
  if (!before || !after) return false;
  const r = reasoning.trim();
  if (!r) return true;
  if (/[\p{L}]$/u.test(before) && /^[\p{Ll}]/u.test(after)) return true;
  if (
    r.length <= 16 &&
    before.length <= 32 &&
    !/\s$/.test(before) &&
    !/^\s/.test(after) &&
    !/[.!?]$/.test(before.trim())
  ) {
    return true;
  }
  return false;
}

/**
 * Merge assistant text fragments split by reasoning/tool boundaries for display and persist.
 * Drops micro-reasoning blocks that only glue a split word (e.g. C + . + iao).
 */
export function coalesceTurnSegments(segments: TurnSegment[]): TurnSegment[] {
  if (segments.length < 2) return segments;

  const out: TurnSegment[] = [];
  let i = 0;

  while (i < segments.length) {
    const seg = segments[i];
    if (seg.kind !== "text") {
      out.push(seg);
      i += 1;
      continue;
    }

    let text = seg.content;
    i += 1;

    while (i < segments.length) {
      const mid = segments[i];
      if (mid.kind === "text") {
        text += mid.content;
        i += 1;
        continue;
      }
      if (
        mid.kind === "reasoning" &&
        i + 1 < segments.length &&
        segments[i + 1].kind === "text" &&
        shouldMergeTextAcrossReasoning(text, mid.content, segments[i + 1].content)
      ) {
        text += segments[i + 1].content;
        i += 2;
        continue;
      }
      break;
    }

    out.push({ ...seg, content: text });
  }

  return out;
}
