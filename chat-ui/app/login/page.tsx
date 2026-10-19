"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { apiBase } from "@/lib/config";
import { getStoredToken, setStoredAuth } from "@/lib/auth/storage";
import {
  DesktopHandoffError,
  completeDesktopHandoff,
  getPendingDesktop,
  readDesktopParams,
  type DesktopRequest,
} from "@/lib/auth/desktop";
import { fetchCurrentUser } from "@/lib/api/user-preferences";
import { DesktopHandoffStatus, type DesktopHandoffState } from "@/components/auth/DesktopHandoffStatus";
import { fetchAuthStatus } from "@/lib/auth/status";
import { ChatBrand } from "@/components/brand/ChatBrand";
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
  const [desktop, setDesktop] = useState<DesktopRequest | null>(null);
  const [handoff, setHandoff] = useState<DesktopHandoffState | null>(null);
  const [existing, setExisting] = useState<{ token: string; label: string } | null>(null);
  const handoffToken = useRef<string | null>(null);

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

    const req = readDesktopParams();
    if (req) {
      setDesktop(req);
      const stored = getStoredToken();
      if (stored) {
        void fetchCurrentUser(stored).then((u) => {
          if (cancelled || !u) return;
          const label = u.display_name || u.identifier || "";
          if (label) setExisting({ token: stored, label });
        });
      }
    }

    return () => {
      cancelled = true;
    };
  }, [ssoErrorMessage]);

  async function runHandoff(token: string) {
    handoffToken.current = token;
    setHandoff({ phase: "working" });
    try {
      const target = await completeDesktopHandoff(token);
      setHandoff({ phase: "done" });
      window.location.assign(target);
    } catch (e) {
      setHandoff({ phase: "error", code: e instanceof DesktopHandoffError ? e.code : "generic" });
    }
  }

  function retryHandoff() {
    if (handoff?.phase === "error" && handoff.code === "unauthorized") {
      handoffToken.current = null;
      setHandoff(null);
      return;
    }
    if (handoffToken.current) void runHandoff(handoffToken.current);
  }

  function useAnotherAccount() {
    setExisting(null);
  }

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
    // Login per l'app desktop: il token non viene salvato nel browser, serve solo per l'handoff.
    if (j.access_token && getPendingDesktop()) {
      await runHandoff(j.access_token);
      return;
    }
    if (j.access_token && j.user_id) {
      setStoredAuth(j.access_token, j.user_id);
      initLocaleFromStorage();
      await syncLanguagePreferenceToServer(j.access_token);
      window.location.href = "/";
    }
  }

  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-6 bg-background px-4 text-foreground">
      <ChatBrand className="mb-2 h-20" />
      <h1 className="text-xl font-semibold tracking-tight text-foreground sr-only">AION Chat — login</h1>
      {desktop && (
        <p className="w-full max-w-sm rounded-aion border border-input bg-muted px-3 py-2 text-center text-sm text-foreground">
          {t("login.desktop.banner")}
        </p>
      )}
      {handoff && <DesktopHandoffStatus state={handoff} onRetry={retryHandoff} />}
      {desktop && !handoff && existing && (
        <div className="flex w-full max-w-sm flex-col gap-3">
          <button
            type="button"
            onClick={() => void runHandoff(existing.token)}
            className="focus-ring rounded-aion bg-primary py-2.5 text-sm font-medium text-primary-foreground hover:bg-primary/90"
          >
            {t("login.desktop.continue_as", { user: existing.label })}
          </button>
          <button
            type="button"
            onClick={useAnotherAccount}
            className="focus-ring text-xs text-primary underline-offset-2 hover:underline"
          >
            {t("login.desktop.other_account")}
          </button>
        </div>
      )}
      {!handoff && !(desktop && existing) && ssoEnabled && ssoProvider && !mfa && (
        <div className="flex w-full max-w-sm flex-col gap-4 mb-2">
          <button
            onClick={handleSSOLogin}
            className="focus-ring flex w-full items-center justify-center gap-3 rounded-aion border border-input bg-background px-4 py-4 text-base font-semibold text-foreground hover:bg-muted transition-colors"
            type="button"
          >
            {ssoProvider === "microsoft" ? (
              <svg className="h-6 w-6 shrink-0" viewBox="0 0 21 21" fill="none">
                <path d="M0 0H10V10H0V0Z" fill="#f25022"/>
                <path d="M11 0H21V10H11V0Z" fill="#7fba00"/>
                <path d="M0 11H10V21H0V11Z" fill="#00a4ef"/>
                <path d="M11 11H21V21H11V11Z" fill="#ffb900"/>
              </svg>
            ) : (
              <svg className="h-6 w-6 shrink-0" viewBox="0 0 48 48">
                <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/>
                <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/>
                <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/>
                <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/>
              </svg>
            )}
            {ssoProvider === "microsoft" ? t("login.sso_microsoft") : t("login.sso_google")}
          </button>
          {passwordVisible && (
            <div className="relative">
              <div className="absolute inset-0 flex items-center">
                <span className="w-full border-t border-input" />
              </div>
              <div className="relative flex justify-center text-xs uppercase">
                <span className="bg-background px-2 text-muted-foreground">{t("login.or")}</span>
              </div>
            </div>
          )}
        </div>
      )}
      {!handoff && !(desktop && existing) && mfa && (
        <TwoFactorStep
          challenge={mfa}
          onSuccess={completeLogin}
          onCancel={() => setMfa(null)}
        />
      )}
      {!handoff && !(desktop && existing) && passwordVisible && !mfa && (
        <form onSubmit={submit} className="flex w-full max-w-sm flex-col gap-3">
          <input
            className="focus-ring rounded-aion border border-input bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground"
            placeholder="Username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
          />
          <input
            type="password"
            className="focus-ring rounded-aion border border-input bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground"
            placeholder="Password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
          />
          {err && (
            <p className="text-sm text-destructive" role="alert">
              {err}
            </p>
          )}
          <button
            type="submit"
            className="focus-ring rounded-aion bg-primary py-2.5 text-sm font-medium text-primary-foreground hover:bg-primary/90"
          >
            {t("login.btn")}
          </button>
        </form>
      )}
      {/* Il bypass "chat senza login" e' permesso solo se AION_CHAT_PASSWORD_AUTH e' disattivato lato server. */}
      {authRequired === false && !desktop && (
        <Link href="/" className="focus-ring text-xs text-primary underline-offset-2 hover:underline">
          {t("login.no_auth")}
        </Link>
      )}
    </div>
  );
}
