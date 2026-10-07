"use client";

import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { apiBase } from "@/lib/config";
import { getStoredToken, setStoredAuth } from "@/lib/auth/storage";
import { resetAuthStatusCache } from "@/lib/auth/status";
import { useT } from "@/lib/i18n/use-t";
import { ChatBrand } from "@/components/brand/ChatBrand";

export function SsoLinkModal({ provider }: { provider: string }) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const t = useT();

  useEffect(() => {
    // Esito di un collegamento fallito: il callback ritorna su /?sso_link_error=<code>.
    const params = new URLSearchParams(window.location.search);
    const code = params.get("sso_link_error");
    if (code) {
      const key = `login.sso_error.${code}`;
      const msg = t(key);
      setError(msg && msg !== key ? msg : t("login.sso_error.link_failed"));
      params.delete("sso_link_error");
      const qs = params.toString();
      window.history.replaceState(null, "", window.location.pathname + (qs ? `?${qs}` : ""));
    }
  }, [t]);

  const handleLogout = () => {
    setStoredAuth(null, null);
    resetAuthStatusCache();
    window.location.href = "/login";
  };

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
        let msg = t("sso_link.start_failed");
        try {
          const j = await res.json();
          if (j.detail?.code) {
            const key = `login.sso_error.${j.detail.code}`;
            const m = t(key);
            msg = m && m !== key ? m : msg;
          }
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
        setError(t("sso_link.bad_response"));
        setLoading(false);
      }
    } catch (e) {
      console.error(e);
      setError(t("sso_link.network"));
      setLoading(false);
    }
  };

  return (
    <div role="dialog" aria-modal="true" className="fixed inset-0 z-50 flex items-center justify-center bg-background/80 backdrop-blur-sm">
      <div className="w-full max-w-md rounded-aion border border-border bg-card p-6 text-card-foreground shadow-lg">
        <div className="mb-6 flex justify-center">
          <ChatBrand className="h-12" />
        </div>
        <h2 className="mb-2 text-center text-xl font-semibold">{t("sso_link.title")}</h2>
        <p className="mb-6 text-center text-sm text-muted-foreground">
          {t("sso_link.desc", { provider: providerName })}
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
            t("sso_link.button", { provider: providerName })
          )}
        </button>
        <button
          type="button"
          onClick={handleLogout}
          disabled={loading}
          className="focus-ring mt-3 w-full rounded-aion py-2 text-sm text-muted-foreground hover:text-foreground"
        >
          {t("sso_link.logout")}
        </button>
      </div>
    </div>
  );
}
