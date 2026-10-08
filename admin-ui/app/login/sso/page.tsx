"use client";

import { useEffect, useState } from "react";
import { Loader2, AlertCircle } from "lucide-react";

import { apiBase } from "@/lib/api";
import { adminPath } from "@/lib/paths";
import { setStoredAuth } from "@/lib/auth/storage";
import { resetAuthStatusCache } from "@/lib/auth/status";

// Il codice e' monouso: in dev (StrictMode) l'effect gira due volte e la
// seconda esecuzione non deve trattarlo come mancante.
let started = false;

/** Navigazione completa: il gate e la cache di stato ripartono da zero. */
function go(path: string) {
  window.location.replace(adminPath(path));
}

/** Riceve il codice di handoff da /auth/sso/callback (purpose=admin_login). */
export default function AdminSsoExchangePage() {
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (started) return;
    started = true;
    const hash = new URLSearchParams(window.location.hash.substring(1));
    const code = hash.get("code");
    const rawReturn = hash.get("return_to") || "/";
    // Solo percorsi interni all'admin-ui.
    const returnTo = rawReturn.startsWith("/") && !rawReturn.startsWith("//") ? rawReturn : "/";
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

  return (
    <div className="flex min-h-screen items-center justify-center bg-[#0a0a0a] px-4 text-gray-200">
      {error ? (
        <div className="flex max-w-sm flex-col items-center gap-4 rounded-xl border border-red-500/30 bg-red-500/10 p-6 text-center">
          <AlertCircle className="text-red-400" aria-hidden />
          <p className="text-sm text-red-300">{error}</p>
          <button
            type="button"
            onClick={() => go("/login")}
            className="rounded-xl bg-emerald-500/20 px-4 py-2 text-sm text-emerald-300 hover:bg-emerald-500/30"
          >
            Torna al login
          </button>
        </div>
      ) : (
        <div className="flex items-center gap-3 text-sm text-gray-400">
          <Loader2 className="animate-spin" size={18} aria-hidden />
          Completamento accesso SSO…
        </div>
      )}
    </div>
  );
}
