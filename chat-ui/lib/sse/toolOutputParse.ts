/** Detect structured AION tool failures in tool_end output (JSON ok:false). */

export function toolOutputLooksLikeError(output: string): boolean {
  const trimmed = String(output || "").trim();
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
