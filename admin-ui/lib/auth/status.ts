import { apiBase } from "../api";

export type AuthStatus = {
  password_auth_enabled: boolean;
  admin_password_auth_enabled: boolean;
  login_endpoint: string;
  token_ttl_seconds: number;
  first_setup_complete: boolean;
  sso_enabled: boolean;
  sso_provider: string | null;
  /** In SSO: almeno un admin ha ancora una password (form di login necessario). */
  admin_password_login: boolean;
};

const DEFAULT_STATUS: AuthStatus = {
  password_auth_enabled: false,
  // Default fail-secure: assumiamo admin protetto se il backend non risponde.
  admin_password_auth_enabled: true,
  login_endpoint: "/auth/login",
  token_ttl_seconds: 0,
  first_setup_complete: false,
  sso_enabled: false,
  sso_provider: null,
  admin_password_login: true,
};

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
        admin_password_auth_enabled:
          j.admin_password_auth_enabled === undefined
            ? true
            : Boolean(j.admin_password_auth_enabled),
        login_endpoint: j.login_endpoint || "/auth/login",
        token_ttl_seconds: Number(j.token_ttl_seconds || 0),
        first_setup_complete: Boolean(j.first_setup_complete),
        sso_enabled: Boolean(j.sso_enabled),
        sso_provider: j.sso_provider || null,
        admin_password_login:
          j.admin_password_login === undefined ? true : Boolean(j.admin_password_login),
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
