import { apiBase } from "../config";

export type AuthStatus = {
  password_auth_enabled: boolean;
  login_endpoint: string;
  token_ttl_seconds: number;
};

const DEFAULT_STATUS: AuthStatus = {
  password_auth_enabled: false,
  login_endpoint: "/auth/login",
  token_ttl_seconds: 0,
};

/** Una sola richiesta per pagina: cache module-level. */
let cachedStatus: Promise<AuthStatus> | null = null;

export function fetchAuthStatus(force = false): Promise<AuthStatus> {
  if (!force && cachedStatus) return cachedStatus;
  cachedStatus = (async () => {
    try {
      const r = await fetch(`${apiBase()}/auth/status`, { cache: "no-store" });
      if (!r.ok) return DEFAULT_STATUS;
      const j = (await r.json()) as Partial<AuthStatus>;
      return {
        password_auth_enabled: Boolean(j.password_auth_enabled),
        login_endpoint: j.login_endpoint || "/auth/login",
        token_ttl_seconds: Number(j.token_ttl_seconds || 0),
      };
    } catch {
      return DEFAULT_STATUS;
    }
  })();
  return cachedStatus;
}

export function resetAuthStatusCache() {
  cachedStatus = null;
}
