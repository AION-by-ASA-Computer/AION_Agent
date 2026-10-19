"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { apiBase } from "@/lib/config";
import { setStoredAuth } from "@/lib/auth/storage";
import { fetchAuthStatus } from "@/lib/auth/status";
import { cn } from "@/lib/cn";
import {
  AuthAlert,
  AuthDivider,
  AuthHeading,
  AuthShell,
  SsoProviderIcon,
  authInputCls,
  authOutlineBtnCls,
  authPrimaryBtnCls,
  authQuietBtnCls,
} from "@/components/auth/AuthShell";
import { TwoFactorStep, type MfaChallenge } from "@/components/auth/TwoFactorStep";
import { initLocaleFromStorage } from "@/lib/i18n/i18n-store";
import { syncLanguagePreferenceToServer } from "@/lib/i18n/sync-language";
import { useT } from "@/lib/i18n/use-t";

export default function LoginPage() {
  const t = useT();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [authRequired, setAuthRequired] = useState<boolean | null>(null);
  const [ssoEnabled, setSsoEnabled] = useState<boolean>(false);
  const [ssoProvider, setSsoProvider] = useState<"microsoft" | "google" | null>(null);
  const [passwordVisible, setPasswordVisible] = useState<boolean>(true);
  const [mfa, setMfa] = useState<MfaChallenge | null>(null);

  const ssoErrorMessage = useCallback(
    (code: string) => {
      const key = `login.sso_error.${code}`;
      const msg = t(key);
      return msg && msg !== key ? msg : t("login.sso_error.generic");
    },
    [t]
  );

  useEffect(() => {
    let cancelled = false;
    void fetchAuthStatus().then((s) => {
      if (!cancelled) {
        setAuthRequired(s.password_auth_enabled);
        setSsoEnabled(s.sso_enabled || false);
        setSsoProvider(s.sso_provider || null);
        setPasswordVisible(s.password_login_visible ?? true);
      }
    });

    const params = new URLSearchParams(window.location.search);
    const ssoError = params.get("error");
    if (ssoError) {
      setErr(ssoErrorMessage(ssoError));
    }

    return () => {
      cancelled = true;
    };
  }, [ssoErrorMessage]);

  function handleSSOLogin() {
    window.location.href = `${apiBase()}/auth/sso/start?provider=${ssoProvider}&return_to=/`;
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    const r = await fetch(`${apiBase()}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password, client: "chat" }),
    });
    const raw = await r.text();
    let j: {
      detail?: string | { code?: string } | unknown[];
      access_token?: string;
      user_id?: string;
      mfa_required?: boolean;
      mfa_stage?: "enroll" | "verify";
      mfa_token?: string;
    };
    try {
      j = raw ? (JSON.parse(raw) as typeof j) : {};
    } catch {
      setErr(
        r.status === 404
          ? `Endpoint non trovato. Imposta NEXT_PUBLIC_AION_API_URL (es. http://localhost:8001) e avvia l'API FastAPI.`
          : "Risposta non valida dal server."
      );
      return;
    }
    if (!r.ok) {
      const d = j.detail;
      const code = d && !Array.isArray(d) && typeof d === "object" ? (d as { code?: string }).code : undefined;
      const msg =
        code
          ? ssoErrorMessage(code)
          : typeof d === "string"
          ? d
          : Array.isArray(d) && d[0] && typeof (d[0] as { msg?: string }).msg === "string"
            ? (d[0] as { msg: string }).msg
            : "Login failed";
      setErr(msg);
      return;
    }
    if (j.mfa_required && j.mfa_token && j.mfa_stage) {
      setPassword("");
      setMfa({ stage: j.mfa_stage, token: j.mfa_token });
      return;
    }
    await completeLogin(j);
  }

  async function completeLogin(j: { access_token?: string; user_id?: string }) {
    if (j.access_token && j.user_id) {
      setStoredAuth(j.access_token, j.user_id);
      initLocaleFromStorage();
      await syncLanguagePreferenceToServer(j.access_token);
      window.location.href = "/";
    }
  }

  const showSso = ssoEnabled && !!ssoProvider && !mfa;
  const showPasswordForm = passwordVisible && !mfa;

  return (
    <AuthShell
      footer={
        /* Il bypass "chat senza login" e' permesso solo se AION_CHAT_PASSWORD_AUTH e' disattivato lato server. */
        authRequired === false ? (
          <Link href="/" className={authQuietBtnCls}>
            {t("login.no_auth")}
          </Link>
        ) : null
      }
    >
      <AuthHeading title="AION Chat — login" srOnly />
      {mfa ? (
        <TwoFactorStep challenge={mfa} onSuccess={completeLogin} onCancel={() => setMfa(null)} />
      ) : (
        <div className="flex flex-col gap-5">
          {showSso && (
            <button onClick={handleSSOLogin} className={authOutlineBtnCls} type="button">
              <SsoProviderIcon provider={ssoProvider} />
              {ssoProvider === "microsoft" ? t("login.sso_microsoft") : t("login.sso_google")}
            </button>
          )}
          {showSso && showPasswordForm && <AuthDivider label={t("login.or")} />}
          {!showPasswordForm && err && <AuthAlert>{err}</AuthAlert>}
          {showPasswordForm && (
            <form onSubmit={submit} className="flex flex-col gap-3">
              <input
                className={authInputCls}
                placeholder="Username"
                aria-label="Username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="username"
              />
              <input
                type="password"
                className={authInputCls}
                placeholder="Password"
                aria-label="Password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
              />
              {err && <AuthAlert>{err}</AuthAlert>}
              <button type="submit" className={cn(authPrimaryBtnCls, "mt-1")}>
                {t("login.btn")}
              </button>
            </form>
          )}
        </div>
      )}
    </AuthShell>
  );
}
