"use client";

import { useEffect, useState } from "react";
import { Loader2, AlertCircle } from "lucide-react";
import { AuthShell, authPrimaryBtnCls } from "@/components/auth/AuthShell";

import { apiBase } from "@/lib/api";
import { adminPath } from "@/lib/paths";
import { setStoredAuth } from "@/lib/auth/storage";
import { resetAuthStatusCache } from "@/lib/auth/status";
import { sanitizeReturnTo } from "@/lib/auth/safeRedirect";

// Il codice e' monouso: in dev (StrictMode) l'effect gira due volte e la
// seconda esecuzione non deve trattarlo come mancante.
let started = false;

/** Navigazione completa: il gate e la cache di stato ripartono da zero. */
function go(path: string) {
  let safe = "/";
  try {
    const dest = new URL(path, window.location.origin);
    if (dest.origin === window.location.origin) {
      safe = dest.pathname + dest.search + dest.hash;
    }
  } catch {
    safe = "/";
  }
  window.location.replace(adminPath(safe));
}

/** Riceve il codice di handoff da /auth/sso/callback (purpose=admin_login). */
export default function AdminSsoExchangePage() {
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (started) return;
    started = true;
    const hash = new URLSearchParams(window.location.hash.substring(1));
    const code = hash.get("code");
    // Solo percorsi interni all'admin-ui.
    const returnTo = sanitizeReturnTo(hash.get("return_to"));
    window.history.replaceState(null, "", window.location.pathname + window.location.search);

    if (!code) {
      setError("Codice di accesso SSO mancante.");
      return;
    }

    void (async () => {
      try {
        const res = await fetch(`${apiBase()}/auth/sso/exchange`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ code }),
        });
        if (!res.ok) {
          let errCode = "sso_failed";
          try {
            const j = await res.json();
            errCode = j.detail?.code || errCode;
          } catch {}
          go(`/login?error=${encodeURIComponent(errCode)}`);
          return;
        }
        const data = await res.json();
        const roles: string[] = Array.isArray(data.roles) ? data.roles : [];
        if (!data.access_token || !roles.includes("admin")) {
          go("/login?error=not_admin");
          return;
        }
        setStoredAuth(data.access_token, data.user_id ?? null);
        resetAuthStatusCache();
        go(returnTo);
      } catch {
        started = false;
        setError("Errore di rete durante l'accesso SSO.");
      }
    })();
  }, []);

  if (error) {
    return (
      <AuthShell>
        <div className="flex flex-col items-center gap-4 text-center">
          <div className="flex size-10 items-center justify-center rounded-xl bg-destructive/10 text-destructive">
            <AlertCircle className="h-5 w-5" aria-hidden />
          </div>
          <p className="text-sm text-foreground" role="alert">{error}</p>
          <button type="button" onClick={() => go("/login")} className={authPrimaryBtnCls}>
            Torna al login
          </button>
        </div>
      </AuthShell>
    );
  }

  return (
    <div className="flex min-h-[100dvh] items-center justify-center gap-3 bg-background px-4 text-sm text-muted-foreground">
      <Loader2 className="animate-spin text-primary" size={18} aria-hidden />
      <span role="status">Completamento accesso SSO…</span>
    </div>
  );
}
