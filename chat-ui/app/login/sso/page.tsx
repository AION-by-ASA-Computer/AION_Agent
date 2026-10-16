"use client";

import { useEffect, useState } from "react";
import { AlertCircle, Loader2 } from "lucide-react";
import { apiBase } from "@/lib/config";
import { setStoredAuth } from "@/lib/auth/storage";
import { sanitizeReturnTo } from "@/lib/auth/safeRedirect";
import { initLocaleFromStorage } from "@/lib/i18n/i18n-store";
import { syncLanguagePreferenceToServer } from "@/lib/i18n/sync-language";
import { AuthAlert, AuthHeading, AuthShell, authPrimaryBtnCls } from "@/components/auth/AuthShell";

export default function SsoExchangePage() {
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function exchangeCode() {
      if (!window.location.hash) {
        setError("Nessun codice trovato (manca l'hash).");
        return;
      }

      const hashParams = new URLSearchParams(window.location.hash.substring(1));
      const code = hashParams.get("code");
      const returnTo = sanitizeReturnTo(hashParams.get("return_to"));

      if (!code) {
        setError("Codice di handoff mancante.");
        return;
      }

      // Pulisce l'URL
      window.history.replaceState(null, "", window.location.pathname + window.location.search);

      try {
        const res = await fetch(`${apiBase()}/auth/sso/exchange`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ code }),
        });

        if (!res.ok) {
          let errCode = "exchange_failed";
          try {
            const j = await res.json();
            errCode = j.detail?.code || errCode;
          } catch {}
          window.location.href = `/login?error=${encodeURIComponent(errCode)}`;
          return;
        }

        const data = await res.json();
        if (data.access_token && data.user_id) {
          setStoredAuth(data.access_token, data.user_id);
          initLocaleFromStorage();
          await syncLanguagePreferenceToServer(data.access_token);
          
          if (data.sso_link_required) {
            // L'utente deve fare il link, la dashboard mostrerà il modale
            window.location.href = "/";
          } else {
            let safeReturnTo = "/";
            try {
              const dest = new URL(returnTo, window.location.origin);
              if (dest.origin === window.location.origin) {
                safeReturnTo = dest.pathname + dest.search + dest.hash;
              }
            } catch {
              safeReturnTo = "/";
            }
            window.location.href = safeReturnTo;
          }
        } else {
          setError("Risposta non valida dal server.");
        }
      } catch (err) {
        console.error(err);
        setError("Errore di rete durante lo scambio del codice SSO.");
      }
    }

    void exchangeCode();
  }, []);

  if (error) {
    return (
      <AuthShell>
        <AuthHeading
          icon={<AlertCircle className="h-5 w-5" aria-hidden />}
          title="Errore SSO"
        />
        <div className="flex flex-col gap-4">
          <AuthAlert>{error}</AuthAlert>
          <button
            onClick={() => window.location.href = "/login"}
            className={authPrimaryBtnCls}
          >
            Torna al login
          </button>
        </div>
      </AuthShell>
    );
  }

  return (
    <div className="flex min-h-[100dvh] flex-col items-center justify-center gap-3 bg-background px-4 text-muted-foreground">
      <Loader2 className="animate-spin text-primary" size={22} aria-hidden />
      <p className="text-sm" role="status">Completamento accesso SSO in corso...</p>
    </div>
  );
}
