/**
 * Validates a client-supplied `return_to` as an internal, same-origin path.
 *
 * Resolves it against the current origin with the URL parser (so the
 * backslash/protocol-relative normalization quirks of "special" schemes are
 * handled by the parser itself, not by guessing every bypass string) and
 * only accepts it when the resulting origin still matches ours.
 */
export function sanitizeReturnTo(raw: string | null | undefined, fallback = "/"): string {
  if (!raw) return fallback;
  try {
    const url = new URL(raw, window.location.origin);
    if (url.origin !== window.location.origin) return fallback;
    return url.pathname + url.search + url.hash;
  } catch {
    return fallback;
  }
}
