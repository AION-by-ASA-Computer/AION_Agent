"use client";

import { useEffect, useState } from "react";
import { apiBase } from "@/lib/config";
import { setStoredAuth } from "@/lib/auth/storage";
import { initLocaleFromStorage } from "@/lib/i18n/i18n-store";
import { syncLanguagePreferenceToServer } from "@/lib/i18n/sync-language";

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
      const returnTo = hashParams.get("return_to") || "/";

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
            window.location.href = returnTo;
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
