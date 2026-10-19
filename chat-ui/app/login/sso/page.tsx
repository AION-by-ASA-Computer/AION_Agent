"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { apiBase } from "@/lib/config";
import { setStoredAuth } from "@/lib/auth/storage";
import { DesktopHandoffError, completeDesktopHandoff, getPendingDesktop } from "@/lib/auth/desktop";
import { DesktopHandoffStatus, type DesktopHandoffState } from "@/components/auth/DesktopHandoffStatus";
import { sanitizeReturnTo } from "@/lib/auth/safeRedirect";
import { initLocaleFromStorage } from "@/lib/i18n/i18n-store";
import { syncLanguagePreferenceToServer } from "@/lib/i18n/sync-language";

export default function SsoExchangePage() {
  const [error, setError] = useState<string | null>(null);
  const [handoff, setHandoff] = useState<DesktopHandoffState | null>(null);
  const handoffToken = useRef<string | null>(null);

  const runHandoff = useCallback(async (token: string) => {
    handoffToken.current = token;
    setHandoff({ phase: "working" });
    try {
      const target = await completeDesktopHandoff(token);
      setHandoff({ phase: "done" });
      window.location.assign(target);
    } catch (e) {
      setHandoff({ phase: "error", code: e instanceof DesktopHandoffError ? e.code : "generic" });
    }
  }, []);

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
        if (data.access_token && getPendingDesktop()) {
          // Login per l'app desktop: nessun token nel browser; sso_link_required lo gestisce l'app.
          await runHandoff(data.access_token);
          return;
        }
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
  }, [runHandoff]);

  if (handoff) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center bg-background px-4 text-foreground">
        <DesktopHandoffStatus
          state={handoff}
          onRetry={() => {
            if (handoff.phase === "error" && handoff.code === "unauthorized") {
              window.location.href = "/login";
            } else if (handoffToken.current) {
              void runHandoff(handoffToken.current);
            }
          }}
        />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background px-4 text-foreground">
        <div className="max-w-md rounded-aion border border-destructive bg-destructive/10 p-6 text-center">
          <h2 className="mb-4 text-lg font-semibold text-destructive">Errore SSO</h2>
          <p className="mb-6 text-sm text-foreground">{error}</p>
          <button
            onClick={() => window.location.href = "/login"}
            className="focus-ring rounded-aion bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
          >
            Torna al login
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-background px-4 text-foreground">
      <div className="flex flex-col items-center gap-4">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-muted border-t-primary" />
        <p className="text-sm text-muted-foreground animate-pulse">Completamento accesso SSO in corso...</p>
      </div>
    </div>
  );
}
