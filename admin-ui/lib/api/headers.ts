import { getStoredToken, setStoredAuth } from "@/lib/auth/storage";
import { adminPath } from "@/lib/paths";

/**
 * Headers da iniettare in tutte le fetch admin-ui.
 * Aggiunge `Authorization: Bearer <token>` se presente in localStorage.
 */
function authHeaders(extra?: HeadersInit): HeadersInit {
  const t = getStoredToken();
  const base: Record<string, string> = {};
  if (t) base.Authorization = `Bearer ${t}`;
  if (!extra) return base;
  if (extra instanceof Headers) {
    const out: Record<string, string> = { ...base };
    extra.forEach((v, k) => {
      out[k] = v;
    });
    return out;
  }
  if (Array.isArray(extra)) {
    const out: Record<string, string> = { ...base };
    for (const [k, v] of extra) out[k] = v;
    return out;
  }
  return { ...base, ...(extra as Record<string, string>) };
}

/**
 * Wrapper di ``fetch`` che inietta automaticamente l'header Bearer e
 * gestisce 401 (token scaduto) facendo redirect a /login.
 *
 * Da usare per TUTTE le chiamate alle API protette di /admin/*.
 */
export async function apiFetch(input: RequestInfo, init: RequestInit = {}): Promise<Response> {
  const merged: RequestInit = {
    ...init,
    headers: authHeaders(init.headers),
  };
  const res = await fetch(input, merged);
  if (res.status === 401) {
    setStoredAuth(null, null);
    if (typeof window !== "undefined") {
      const next = window.location.pathname + window.location.search;
      window.location.replace(
        `${adminPath("/login")}?next=${encodeURIComponent(next)}`,
      );
    }
  }
  return res;
}
