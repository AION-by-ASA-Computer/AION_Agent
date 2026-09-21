import type { TurnSegment } from "@/lib/sse/types";

type TranslateFn = (key: string, vars?: Record<string, string | number>) => string;
type OutcomeDetails = Record<string, unknown> | undefined;

function detailStr(details: OutcomeDetails, key: string, fallback = "—"): string {
  const raw = details?.[key];
  if (raw === null || raw === undefined || raw === "") return fallback;
  return String(raw);
}

/** Prefer i18n template when outcomeCode is known; fallback to server message. */
export function resolveTurnOutcomeMessage(
  t: TranslateFn,
  content: string,
  outcomeCode?: string,
  outcomeDetails?: OutcomeDetails,
): string {
  if (!outcomeCode) return content;
  const key = `chat.turn_outcome.${outcomeCode}`;
  const translated = t(key, {
    effort: detailStr(outcomeDetails, "reasoning_effort"),
    max_chars: detailStr(outcomeDetails, "max_reasoning_chars"),
    max_events: detailStr(outcomeDetails, "max_reasoning_events"),
    reasoning_len: detailStr(outcomeDetails, "reasoning_len"),
    tool_calls: detailStr(outcomeDetails, "tool_calls", "0"),
    stop_reason: detailStr(outcomeDetails, "stop_reason", ""),
  });
  return translated === key ? content : translated;
}

/** Last warning status segment (turn_outcome or stream error), with i18n when possible. */
export function outcomeTextFromSegments(segments: TurnSegment[], t: TranslateFn): string {
  for (let i = segments.length - 1; i >= 0; i--) {
    const seg = segments[i];
    if (seg.kind === "status" && seg.tone === "warning" && seg.content.trim()) {
      return resolveTurnOutcomeMessage(
        t,
        seg.content,
        seg.outcomeCode,
        seg.outcomeDetails,
      );
    }
  }
  return "";
}
