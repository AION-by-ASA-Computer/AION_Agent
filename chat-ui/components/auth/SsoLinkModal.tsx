"use client";

import { useState } from "react";
import { Loader2 } from "lucide-react";
import { apiBase } from "@/lib/config";
import { getStoredToken } from "@/lib/auth/storage";
import { ChatBrand } from "@/components/brand/ChatBrand";

export function SsoLinkModal({ provider }: { provider: string }) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const providerName = provider === "microsoft" ? "Microsoft" : provider === "google" ? "Google" : provider;

  const handleLink = async () => {
    setLoading(true);
    setError(null);
    try {
      const token = getStoredToken();
      const res = await fetch(`${apiBase()}/auth/sso/link/start`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ return_to: window.location.pathname }),
      });

      if (!res.ok) {
        let msg = "Impossibile avviare il collegamento SSO.";
        try {
          const j = await res.json();
          if (j.detail?.code) msg = `Errore: ${j.detail.code}`;
          else if (typeof j.detail === "string") msg = j.detail;
        } catch {}
        setError(msg);
        setLoading(false);
        return;
      }

      const data = await res.json();
      if (data.authorize_url) {
        window.location.href = data.authorize_url;
      } else {
        setError("Risposta non valida dal server.");
        setLoading(false);
      }
    } catch (e) {
      console.error(e);
      setError("Errore di rete.");
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-background/80 backdrop-blur-sm">
      <div className="w-full max-w-md rounded-aion border border-border bg-card p-6 text-card-foreground shadow-lg">
        <div className="mb-6 flex justify-center">
          <ChatBrand className="h-12" />
        </div>
        <h2 className="mb-2 text-center text-xl font-semibold">Aggiornamento Sicurezza</h2>
        <p className="mb-6 text-center text-sm text-muted-foreground">
          L'amministratore richiede di collegare il tuo account a <strong>{providerName}</strong> per continuare ad accedere.
        </p>

        {error && (
          <div className="mb-4 rounded bg-destructive/10 p-3 text-sm text-destructive">
            {error}
          </div>
        )}

        <button
          onClick={handleLink}
          disabled={loading}
          className="focus-ring flex w-full items-center justify-center gap-2 rounded-aion bg-primary py-2.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
        >
          {loading ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            `Collega account ${providerName}`
          )}
        </button>
      </div>
    </div>
  );
}
