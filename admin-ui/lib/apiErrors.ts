/** Human-readable message from FastAPI ``detail`` (string, validation array, or object). */
export function formatApiErrorDetail(detail: unknown): string {
  if (detail == null) return "";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((entry) => {
        if (entry && typeof entry === "object" && "msg" in entry) {
          const loc = "loc" in entry && Array.isArray(entry.loc) ? entry.loc.join(".") : "";
          const msg = String((entry as { msg: string }).msg);
          return loc ? `${loc}: ${msg}` : msg;
        }
        return JSON.stringify(entry);
      })
      .join("; ");
  }
  if (typeof detail === "object" && detail !== null && "message" in detail) {
    return String((detail as { message: unknown }).message);
  }
  return JSON.stringify(detail);
}

/** Parse error body from a failed ``fetch`` response (JSON ``detail`` or plain text). */
export async function readApiErrorMessage(res: Response, fallback?: string): Promise<string> {
  const text = await res.text();
  if (!text.trim()) return fallback ?? `HTTP ${res.status}`;
  try {
    const body = JSON.parse(text) as { detail?: unknown };
    if (body?.detail != null) return formatApiErrorDetail(body.detail);
  } catch {
    /* not JSON */
  }
  return text;
}
