"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ShieldCheck, Loader2 } from "lucide-react";

import { apiBase } from "@/lib/api";
import { setStoredAuth } from "@/lib/auth/storage";
import { fetchAuthStatus, resetAuthStatusCache } from "@/lib/auth/status";
import { TwoFactorStep, type MfaChallenge, type MfaLoginResult } from "@/components/auth/TwoFactorStep";
import { cn } from "@/lib/cn";
import { chatUrl } from "@/lib/paths";
import {
  AuthAlert,
  AuthDivider,
  AuthHeading,
  AuthShell,
  SsoProviderIcon,
  authInputCls,
  authOutlineBtnCls,
  authPrimaryBtnCls,
} from "@/components/auth/AuthShell";

const codeCls = "rounded-md border border-border/60 bg-muted px-1.5 py-0.5 font-mono text-[0.95em] text-foreground";

const LOGIN_ERRORS: Record<string, string> = {
  temp_password_expired: "La password temporanea è scaduta. Usa «Password dimenticata?» o chiedi a un amministratore di inviarti un nuovo link.",
  sso_required: "Questo account accede tramite SSO: usa il pulsante SSO.",
  password_login_disabled: "L'accesso con password non è disponibile per questo account.",
  not_admin: "Questo account non ha il ruolo 'admin'.",
  sso_not_linked: "Questo account SSO non è collegato a nessun utente AION.",
  sso_domain_not_allowed: "Questo account non è abilitato all'accesso. Stai usando l'account sbagliato: accedi con quello aziendale.",
  sso_failed: "Accesso SSO non riuscito. Riprova.",
  sso_token_invalid: "Accesso SSO non riuscito (token non valido). Riprova.",
  sso_start_failed: "Impossibile avviare l'accesso SSO.",
};

const SSO_LABELS: Record<string, string> = {
  microsoft: "Microsoft",
  google: "Google",
};

export default function AdminLoginPage() {
  const router = useRouter();
  const params = useSearchParams();
  const next = params.get("next") || "/";

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [showDefaultHint, setShowDefaultHint] = useState(false);
  const [mfa, setMfa] = useState<MfaChallenge | null>(null);
  const [ssoProvider, setSsoProvider] = useState<string | null>(null);
  // In SSO il form compare solo se qualche admin ha ancora una password
  // (migrazione in corso o recupero con ``python -m src.auth.recover``).
  // null finche' /auth/status non risponde: niente form "lampeggiante".
  const [showPasswordForm, setShowPasswordForm] = useState<boolean | null>(null);
  const [resetAvailable, setResetAvailable] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void fetchAuthStatus(true).then((s) => {
      if (cancelled) return;
      setSsoProvider(s.sso_enabled ? s.sso_provider : null);
      setShowPasswordForm(!s.sso_enabled || s.admin_password_login);
      setShowDefaultHint(!s.sso_enabled);
      setResetAvailable(s.password_reset_available);
    });
    const code = params.get("error");
    if (code) setErr(LOGIN_ERRORS[code] ?? `Accesso negato (${code})`);
    return () => {
      cancelled = true;
    };
  }, [params]);

  function startSso() {
    if (!ssoProvider) return;
    const q = new URLSearchParams({ provider: ssoProvider, client: "admin", return_to: next });
    window.location.href = `${apiBase()}/auth/sso/start?${q.toString()}`;
  }

  function completeLogin(j: MfaLoginResult) {
    if (!j.access_token) {
      setErr("Token mancante nella risposta.");
      return;
    }
    const roles = Array.isArray(j.roles) ? j.roles : [];
    if (!roles.includes("admin")) {
      setErr("Questo utente non ha il ruolo 'admin'. Chiedi all'amministratore di assegnartelo.");
      setMfa(null);
      return;
    }
    setStoredAuth(j.access_token, j.user_id ?? null);
    resetAuthStatusCache();
    if (j.must_change_password) {
      router.replace("/change-password");
    } else {
      router.replace(next);
    }
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    setLoading(true);
    try {
      const r = await fetch(`${apiBase()}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        // client:"admin" -> il backend NON applica il blocco "solo SSO" ai ruoli admin
        // (accesso di emergenza). Per i non-admin viene comunque trattato come "chat".
        body: JSON.stringify({ username, password, client: "admin" }),
      });
      const raw = await r.text();
      let j: {
        detail?: string | { code?: string } | unknown[];
        access_token?: string;
        user_id?: string;
        roles?: string[];
        must_change_password?: boolean;
        mfa_required?: boolean;
        mfa_stage?: "enroll" | "verify";
        mfa_token?: string;
      };
      try {
        j = raw ? JSON.parse(raw) : {};
      } catch {
        setErr(
          r.status === 404
            ? "Endpoint non trovato. Verifica NEXT_PUBLIC_AION_API_URL e che il backend FastAPI sia in esecuzione."
            : "Risposta non valida dal server.",
        );
        return;
      }
      if (!r.ok) {
        const d = j.detail;
        const code =
          d && !Array.isArray(d) && typeof d === "object" ? (d as { code?: string }).code : undefined;
        const msg =
          typeof d === "string"
            ? d
            : code
            ? LOGIN_ERRORS[code] ?? `Accesso negato (${code})`
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
      completeLogin(j);
    } catch (e: unknown) {
      setErr((e as Error)?.message || "Errore di rete");
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthShell
      footer={
        showDefaultHint && !mfa ? (
          <p className="max-w-sm text-center text-xs leading-relaxed text-muted-foreground">
            Setup iniziale? Le credenziali di default sono
            {" "}
            <code className={codeCls}>admin</code>
            {" / "}
            <code className={codeCls}>admin</code>
            . Cambia la password al primo accesso.
          </p>
        ) : null
      }
    >
      {mfa ? (
        <>
          <AuthHeading title="AION Admin" srOnly />
          <TwoFactorStep challenge={mfa} onSuccess={completeLogin} onCancel={() => setMfa(null)} />
        </>
      ) : (
        <>
          <AuthHeading
            icon={<ShieldCheck className="h-5 w-5" aria-hidden />}
            title="AION Admin"
            description="Accesso riservato agli amministratori"
          />
          {showPasswordForm === null ? (
            <div className="flex justify-center py-4">
              <Loader2 className="animate-spin text-primary" size={22} aria-hidden />
            </div>
          ) : (
            <div className="flex flex-col gap-5">
              {ssoProvider && (
                <button type="button" onClick={startSso} className={authOutlineBtnCls}>
                  <SsoProviderIcon provider={ssoProvider} />
                  Accedi con {SSO_LABELS[ssoProvider] ?? ssoProvider}
                </button>
              )}
              {ssoProvider && showPasswordForm && <AuthDivider label="oppure con password" />}
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
                    autoFocus
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
                  {resetAvailable && (
                    <a
                      href={chatUrl("/forgot-password")}
                      className="focus-ring -mt-1 self-end rounded text-xs font-medium text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
                    >
                      Password dimenticata?
                    </a>
                  )}
                  {err && <AuthAlert>{err}</AuthAlert>}
                  <button type="submit" disabled={loading} className={cn(authPrimaryBtnCls, "mt-1")}>
                    {loading ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
                    Entra
                  </button>
                </form>
              )}
            </div>
          )}
        </>
      )}
    </AuthShell>
  );
}
