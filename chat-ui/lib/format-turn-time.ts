/**
 * Formatting utilities for message timestamps and turn durations.
 */

/**
 * Formats an ISO date string, timestamp number, or Date object into local HH:mm format.
 * Example: "2026-09-10T10:18:24.000Z" -> "10:18" (or local equivalent).
 */
export function formatMessageTime(dateOrIso?: string | number | Date | null): string {
  if (!dateOrIso) return "";
  try {
    const d = typeof dateOrIso === "string" || typeof dateOrIso === "number"
      ? new Date(dateOrIso)
      : dateOrIso;
    if (isNaN(d.getTime())) return "";
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } catch {
    return "";
  }
}

/**
 * Formats turn duration in milliseconds into a concise, human-readable string.
 * Examples:
 *  - 450ms -> "0.5s"
 *  - 3200ms -> "3.2s"
 *  - 14800ms -> "15s"
 *  - 74000ms -> "1m 14s"
 */
export function formatTurnDuration(durationMs?: number | null): string {
  if (durationMs == null || isNaN(durationMs) || durationMs <= 0) return "";
  const totalSeconds = durationMs / 1000;
  if (totalSeconds < 1) {
    return `${totalSeconds.toFixed(1)}s`;
  }
  if (totalSeconds < 10) {
    return `${totalSeconds.toFixed(1)}s`;
  }
  if (totalSeconds < 60) {
    return `${Math.round(totalSeconds)}s`;
  }
  const mins = Math.floor(totalSeconds / 60);
  const remSecs = Math.round(totalSeconds % 60);
  return `${mins}m ${remSecs}s`;
}
