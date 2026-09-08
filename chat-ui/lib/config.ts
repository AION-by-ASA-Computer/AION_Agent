/** Browser-visible API base (FastAPI URL). Must be absolute in dev — relative URLs would hit the Next.js origin and 404. */
export function apiBase(): string {
  const b = process.env.NEXT_PUBLIC_AION_API_URL?.trim().replace(/\/$/, "");
  if (b) return b;
  return "http://localhost:8001";
}

/** Same-origin absolute API base (required for OAuth redirect_uri when apiBase() is `/api`). */
export function absoluteApiBase(): string {
  const base = apiBase();
  if (/^https?:\/\//i.test(base)) return base;
  if (typeof window !== "undefined") {
    const path = base.startsWith("/") ? base : `/${base}`;
    return `${window.location.origin}${path}`;
  }
  return base;
}

export function oauthCallbackRedirectUri(): string {
  return `${absoluteApiBase().replace(/\/$/, "")}/v1/integrations/oauth/callback`;
}

export function adminUiBase(): string {
  return (process.env.NEXT_PUBLIC_AION_ADMIN_UI_URL || "http://localhost:3870").replace(/\/$/, "");
}
