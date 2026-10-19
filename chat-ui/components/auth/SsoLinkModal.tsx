"use client";

import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { apiBase } from "@/lib/config";
import { getStoredToken, setStoredAuth } from "@/lib/auth/storage";
import { resetAuthStatusCache } from "@/lib/auth/status";
import { useT } from "@/lib/i18n/use-t";
import { cn } from "@/lib/cn";
import {
  AuthAlert,
  AuthShell,
  SsoProviderIcon,
  authPrimaryBtnCls,
  authQuietBtnCls,
} from "@/components/auth/AuthShell";

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
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="sso-link-title"
      className="fixed inset-0 z-50 overflow-y-auto bg-background"
    >
      <AuthShell>
        <div className="mb-6 flex flex-col items-center gap-3 text-center">
          <div className="flex size-12 items-center justify-center rounded-full border border-border/70 bg-background/60">
            <SsoProviderIcon provider={provider} className="h-6 w-6" />
          </div>
          <div className="space-y-1.5">
            <h2 id="sso-link-title" className="text-lg font-semibold tracking-tight text-balance">
              {t("sso_link.title")}
            </h2>
            <p className="text-sm leading-relaxed text-pretty text-muted-foreground">
              {t("sso_link.desc", { provider: providerName })}
            </p>
          </div>
        </div>

        <div className="flex flex-col gap-3">
          {error && <AuthAlert>{error}</AuthAlert>}
          <button onClick={handleLink} disabled={loading} className={authPrimaryBtnCls}>
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
            className={cn(authQuietBtnCls, "self-center")}
          >
            {t("sso_link.logout")}
          </button>
        </div>
      </AuthShell>
    </div>
  );
}
