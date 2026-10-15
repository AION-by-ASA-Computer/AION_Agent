/**
 * Validates a client-supplied `return_to` as an internal, same-origin path.
 *
 * Rejects absolute URLs, protocol-relative URLs (`//host`), and the
 * backslash variants (`/\host`, `\\host`) that some browsers normalize to
 * `//host` when resolving a URL with a "special" scheme (http/https),
 * which would otherwise let an attacker redirect to an external origin.
 */
export function sanitizeReturnTo(raw: string | null | undefined, fallback = "/"): string {
  if (!raw) return fallback;
  if (raw.includes("\\")) return fallback;
  if (!raw.startsWith("/") || raw.startsWith("//")) return fallback;
  return raw;
}
