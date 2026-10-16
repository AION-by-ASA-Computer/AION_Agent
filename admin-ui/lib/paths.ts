/** Client-safe admin UI path prefix (empty in local dev, `/admin` in Docker prod). */
function adminBasePath(): string {
  const raw = (process.env.NEXT_PUBLIC_BASE_PATH ?? "").trim().replace(/\/$/, "");
  return raw === "/" ? "" : raw;
}

/** Prefix an app route for hard navigations (`window.location`, SSE URLs). */
export function adminPath(path: string): string {
  const p = path.startsWith("/") ? path : `/${path}`;
  const bp = adminBasePath();
  return bp ? `${bp}${p}` : p;
}

/**
 * Absolute URL of a chat-ui route. `NEXT_PUBLIC_AION_CHAT_URL` wins; otherwise on `next dev`
 * (admin on :3870) chat-ui is assumed on :8003 of the same host, and behind Caddy it is the site root.
 */
export function chatUrl(path: string): string {
  const p = path.startsWith("/") ? path : `/${path}`;
  const env = (process.env.NEXT_PUBLIC_AION_CHAT_URL ?? "").trim().replace(/\/$/, "");
  if (env) return `${env}${p}`;
  if (typeof window !== "undefined") {
    const { protocol, hostname, port, origin } = window.location;
    return port === "3870" ? `${protocol}//${hostname}:8003${p}` : `${origin}${p}`;
  }
  return p;
}
