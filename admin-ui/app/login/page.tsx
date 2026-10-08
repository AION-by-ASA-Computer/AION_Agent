"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ShieldCheck, Loader2, AlertCircle } from "lucide-react";

import { apiBase } from "@/lib/api";
import { setStoredAuth } from "@/lib/auth/storage";
import { fetchAuthStatus, resetAuthStatusCache } from "@/lib/auth/status";
import { TwoFactorStep, type MfaChallenge, type MfaLoginResult } from "@/components/auth/TwoFactorStep";

const LOGIN_ERRORS: Record<string, string> = {
  temp_password_expired: "La password temporanea è scaduta. Chiedi a un amministratore di rigenerarla.",
  sso_required: "Questo account accede tramite SSO: usa il pulsante SSO.",
  password_login_disabled: "L'accesso con password non è disponibile per questo account.",
  not_admin: "Questo account non ha il ruolo 'admin'.",
  sso_not_linked: "Questo account SSO non è collegato a nessun utente AION.",
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
  // Finche' lo stato non arriva mostriamo il form (comportamento precedente).
  const [passwordVisible, setPasswordVisible] = useState(true);
  const [emergency, setEmergency] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void fetchAuthStatus(true).then((s) => {
      if (cancelled) return;
      setSsoProvider(s.sso_enabled ? s.sso_provider : null);
      setPasswordVisible(!s.sso_enabled || s.password_login_visible);
      setShowDefaultHint(!s.sso_enabled);
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

  const showPasswordForm = passwordVisible || emergency;

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
    <div className="min-h-screen w-full flex items-center justify-center bg-[#0a0a0a] px-4 py-12 text-white">
      <div className="w-full max-w-sm flex flex-col items-center gap-6">
        <div className="flex flex-col items-center gap-3">
          <div className="w-14 h-14 rounded-2xl bg-emerald-500/15 border border-emerald-500/30 flex items-center justify-center">
            <ShieldCheck className="text-emerald-400" size={28} aria-hidden />
          </div>
          <h1 className="text-2xl font-bold tracking-tight">AION Admin</h1>
          <p className="text-sm text-gray-400 text-center">Accesso riservato agli amministratori</p>
        </div>

        {mfa ? (
          <TwoFactorStep
            challenge={mfa}
            onSuccess={completeLogin}
            onCancel={() => setMfa(null)}
          />
        ) : (
        <div className="flex w-full flex-col gap-4">
        {ssoProvider && (
          <button
            type="button"
            onClick={startSso}
            className="flex w-full items-center justify-center gap-2 rounded-xl bg-emerald-500/20 px-4 py-2.5 text-sm font-medium text-emerald-300 hover:bg-emerald-500/30 border border-emerald-500/30 transition"
          >
            Accedi con {SSO_LABELS[ssoProvider] ?? ssoProvider}
          </button>
        )}
        {ssoProvider && showPasswordForm && (
          <div className="flex items-center gap-3 text-xs text-gray-500">
            <span className="h-px flex-1 bg-[#262626]" />
            oppure con password
            <span className="h-px flex-1 bg-[#262626]" />
          </div>
        )}
        {!showPasswordForm && err && (
          <div
            className="flex items-start gap-2 rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300"
            role="alert"
          >
            <AlertCircle size={16} className="mt-0.5 shrink-0" aria-hidden />
            <span>{err}</span>
          </div>
        )}
        {showPasswordForm && (
        <form onSubmit={submit} className="flex w-full flex-col gap-3">
          <input
            className="w-full rounded-xl border border-[#262626] bg-[#141414] px-4 py-2.5 text-sm text-white placeholder:text-gray-500 outline-none focus:border-emerald-500/50 focus:ring-2 focus:ring-emerald-500/20 transition"
            placeholder="Username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            autoFocus
          />
          <input
            type="password"
            className="w-full rounded-xl border border-[#262626] bg-[#141414] px-4 py-2.5 text-sm text-white placeholder:text-gray-500 outline-none focus:border-emerald-500/50 focus:ring-2 focus:ring-emerald-500/20 transition"
            placeholder="Password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
          />
          {err && (
            <div
              className="flex items-start gap-2 rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300"
              role="alert"
            >
              <AlertCircle size={16} className="mt-0.5 shrink-0" aria-hidden />
              <span>{err}</span>
            </div>
          )}
          <button
            type="submit"
            disabled={loading}
            className="mt-1 flex items-center justify-center gap-2 rounded-xl bg-emerald-500/20 px-4 py-2.5 text-sm font-medium text-emerald-300 hover:bg-emerald-500/30 border border-emerald-500/30 disabled:opacity-60 transition"
          >
            {loading ? <Loader2 className="animate-spin" size={16} aria-hidden /> : null}
            Entra
          </button>
        </form>
        )}
        {!showPasswordForm && (
          <button
            type="button"
            onClick={() => setEmergency(true)}
            className="text-xs text-gray-500 underline-offset-2 hover:text-gray-300 hover:underline"
          >
            Accesso di emergenza con password
          </button>
        )}
        </div>
        )}

        {showDefaultHint && !mfa && (
          <p className="text-xs text-gray-500 max-w-sm text-center">
            Setup iniziale? Le credenziali di default sono
            {" "}
            <code className="px-1.5 py-0.5 rounded bg-white/5 border border-white/10 text-gray-300">admin</code>
            {" / "}
            <code className="px-1.5 py-0.5 rounded bg-white/5 border border-white/10 text-gray-300">admin</code>
            . Cambia la password al primo accesso.
          </p>
        )}
      </div>
    </div>
  );
}
