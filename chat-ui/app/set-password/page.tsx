"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { CheckCircle2, KeyRound, Link2Off, Loader2, ShieldCheck } from "lucide-react";

import { adminUiBase, apiBase } from "@/lib/config";
import { cn } from "@/lib/cn";
import { isPasswordValid, PASSWORD_MAX_LENGTH, policyViolationsFromDetail } from "@/lib/auth/passwordPolicy";
import { getLocale } from "@/lib/i18n/i18n-store";
import { useT } from "@/lib/i18n/use-t";
import {
  AuthAlert,
  AuthHeading,
  AuthShell,
  authInputCls,
  authOutlineBtnCls,
  authPrimaryBtnCls,
  authQuietBtnCls,
} from "@/components/auth/AuthShell";
import { PasswordChecklist, passwordPolicyErrorMessage } from "@/components/auth/PasswordChecklist";

type Purpose = "invite" | "reset" | "migration";

type TokenInfo = {
  purpose: Purpose;
  identifier: string;
  display_name?: string | null;
  expires_at?: string | null;
};

/** Errori che rendono il link inutilizzabile (schermata di errore al posto del form). */
type FatalCode = "token_invalid" | "token_expired" | "sso_user" | "rate_limited" | "generic";

type State =
  | { kind: "loading" }
  | { kind: "form"; info: TokenInfo }
  | { kind: "success"; identifier: string; isAdmin: boolean }
  | { kind: "error"; code: FatalCode };

async function postJson(path: string, body: unknown): Promise<{ status: number; data: Record<string, unknown> }> {
  const r = await fetch(`${apiBase()}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    cache: "no-store",
  });
  const data = (await r.json().catch(() => ({}))) as Record<string, unknown>;
  return { status: r.status, data };
}

function detailCode(data: Record<string, unknown>): string | undefined {
  const d = data.detail;
  if (d && typeof d === "object" && !Array.isArray(d)) {
    const code = (d as { code?: unknown }).code;
    return typeof code === "string" ? code : undefined;
  }
  return undefined;
}

function fatalCode(code: string | undefined): FatalCode {
  return code === "token_invalid" || code === "token_expired" || code === "sso_user" || code === "rate_limited"
    ? code
    : "generic";
}

function formatExpiry(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  try {
    return d.toLocaleString(getLocale(), { dateStyle: "medium", timeStyle: "short" });
  } catch {
    return d.toLocaleString();
  }
}

export default function SetPasswordPage() {
  const t = useT();
  const tokenRef = useRef<string | null>(null);
  const [state, setState] = useState<State>({ kind: "loading" });
  const [newPw, setNewPw] = useState("");
  const [confirmPw, setConfirmPw] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  // Incrementato quando arriva un nuovo #token= sulla pagina gia' aperta.
  const [tokenSeq, setTokenSeq] = useState(0);

  useEffect(() => {
    // Un link aperto nella stessa scheda cambia solo il fragment: niente reload.
    const onHashChange = () => {
      if (!readTokenFromHash()) return;
      setNewPw("");
      setConfirmPw("");
      setErr(null);
      setState({ kind: "loading" });
      setTokenSeq((n) => n + 1);
    };
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  /** Legge `#token=` (se presente) nel ref e lo toglie subito dall'URL. */
  function readTokenFromHash(): boolean {
    const hash = window.location.hash.replace(/^#/, "");
    const token = new URLSearchParams(hash).get("token")?.trim();
    if (window.location.hash) {
      window.history.replaceState(null, "", window.location.pathname + window.location.search);
    }
    if (!token) return false;
    tokenRef.current = token;
    return true;
  }

  useEffect(() => {
    // Il token arriva nel fragment (#token=...): lo leggiamo una sola volta e lo
    // togliamo subito dall'URL. Il ref sopravvive al doppio effect di StrictMode.
    if (tokenRef.current === null && !readTokenFromHash()) {
      tokenRef.current = "";
    }
    const token = tokenRef.current;
    if (!token) {
      setState({ kind: "error", code: "token_invalid" });
      return;
    }

    let cancelled = false;
    void (async () => {
      try {
        const { status, data } = await postJson("/auth/password/setup/inspect", { token });
        if (cancelled) return;
        if (status === 200 && data.valid) {
          setState({
            kind: "form",
            info: {
              purpose: (data.purpose as Purpose) || "invite",
              identifier: String(data.identifier || ""),
              display_name: (data.display_name as string | null) ?? null,
              expires_at: (data.expires_at as string | null) ?? null,
            },
          });
          return;
        }
        setState({ kind: "error", code: status === 429 ? "rate_limited" : fatalCode(detailCode(data)) });
      } catch {
        if (!cancelled) setState({ kind: "error", code: "generic" });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [tokenSeq]);

  const info = state.kind === "form" ? state.info : null;
  const identifier = info?.identifier ?? "";
  const policyOk = isPasswordValid(newPw, identifier);
  const mismatch = confirmPw.length > 0 && newPw !== confirmPw;
  const canSubmit = policyOk && newPw === confirmPw && !submitting;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit || !tokenRef.current) return;
    setErr(null);
    setSubmitting(true);
    try {
      const { status, data } = await postJson("/auth/password/setup", {
        token: tokenRef.current,
        new_password: newPw,
      });
      if (status === 200) {
        tokenRef.current = "";
        setNewPw("");
        setConfirmPw("");
        setState({ kind: "success", identifier: String(data.identifier || identifier), isAdmin: Boolean(data.is_admin) });
        return;
      }
      if (status === 422) {
        const violations = policyViolationsFromDetail(data.detail);
        if (violations) {
          setErr(passwordPolicyErrorMessage(t, violations));
          return;
        }
      }
      if (status === 429) {
        setErr(t("set_password.error.rate_limited"));
        return;
      }
      const code = fatalCode(detailCode(data));
      if (code === "generic") {
        setErr(t("set_password.error.generic"));
        return;
      }
      setState({ kind: "error", code });
    } catch {
      setErr(t("set_password.error.network"));
    } finally {
      setSubmitting(false);
    }
  }

  const backToLogin = (
    <Link href="/login" className={authQuietBtnCls}>
      {t("set_password.back_login")}
    </Link>
  );

  if (state.kind === "loading") {
    return (
      <AuthShell>
        <AuthHeading title={t("set_password.title_invite")} srOnly />
        <div className="flex items-center justify-center gap-2 py-6 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin text-primary" aria-hidden />
          {t("set_password.checking")}
        </div>
      </AuthShell>
    );
  }

  if (state.kind === "error") {
    const tokenProblem = state.code === "token_invalid" || state.code === "token_expired";
    return (
      <AuthShell footer={tokenProblem ? backToLogin : null}>
        <AuthHeading
          icon={state.code === "sso_user" ? <ShieldCheck className="h-5 w-5" aria-hidden /> : <Link2Off className="h-5 w-5" aria-hidden />}
          title={t(`set_password.error_title.${state.code}`)}
          description={t(`set_password.error.${state.code}`)}
        />
        {tokenProblem ? (
          <Link href="/forgot-password" className={authPrimaryBtnCls}>
            {t("set_password.request_new")}
          </Link>
        ) : (
          <Link href="/login" className={authPrimaryBtnCls}>
            {t("set_password.go_login")}
          </Link>
        )}
      </AuthShell>
    );
  }

  if (state.kind === "success") {
    const loginHref = `/login?username=${encodeURIComponent(state.identifier)}`;
    return (
      <AuthShell>
        <AuthHeading
          icon={<CheckCircle2 className="h-5 w-5" aria-hidden />}
          title={t("set_password.success_title")}
          description={t("set_password.success_desc")}
        />
        <div className="flex flex-col gap-3">
          <Link href={loginHref} className={authPrimaryBtnCls}>
            {t("set_password.go_login")}
          </Link>
          {state.isAdmin ? (
            <a href={adminUiBase()} className={cn(authOutlineBtnCls, "h-10")}>
              {t("set_password.go_admin")}
            </a>
          ) : null}
        </div>
      </AuthShell>
    );
  }

  const { purpose, display_name } = state.info;
  const expiry = formatExpiry(state.info.expires_at);

  return (
    <AuthShell footer={backToLogin}>
      <AuthHeading
        icon={<KeyRound className="h-5 w-5" aria-hidden />}
        title={t(`set_password.title_${purpose}`)}
        description={t("set_password.greeting", { name: display_name || identifier })}
      />
      <form onSubmit={submit} className="flex flex-col gap-3">
        {purpose === "migration" ? <AuthAlert tone="success">{t("set_password.migration_note")}</AuthAlert> : null}
        <label className="flex flex-col gap-1.5">
          <span className="text-xs font-medium text-muted-foreground">{t("set_password.username")}</span>
          <input
            className={cn(authInputCls, "cursor-default text-muted-foreground")}
            value={identifier}
            readOnly
            autoComplete="username"
            name="username"
          />
        </label>
        <input
          type="password"
          className={authInputCls}
          placeholder={t("set_password.new_password")}
          aria-label={t("set_password.new_password")}
          aria-describedby="set-password-rules"
          value={newPw}
          onChange={(e) => setNewPw(e.target.value)}
          maxLength={PASSWORD_MAX_LENGTH}
          autoComplete="new-password"
          autoFocus
        />
        <PasswordChecklist id="set-password-rules" password={newPw} identifier={identifier} className="px-1" />
        <input
          type="password"
          className={cn(authInputCls, mismatch && "border-destructive/60 focus:border-destructive")}
          placeholder={t("set_password.confirm_password")}
          aria-label={t("set_password.confirm_password")}
          aria-invalid={mismatch}
          value={confirmPw}
          onChange={(e) => setConfirmPw(e.target.value)}
          maxLength={PASSWORD_MAX_LENGTH}
          autoComplete="new-password"
        />
        {mismatch ? <p className="px-1 text-xs text-destructive">{t("set_password.mismatch")}</p> : null}
        {err && <AuthAlert>{err}</AuthAlert>}
        <button type="submit" disabled={!canSubmit} className={cn(authPrimaryBtnCls, "mt-1")}>
          {submitting ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
          {t("set_password.submit")}
        </button>
        {expiry ? (
          <p className="text-center text-xs text-muted-foreground">{t("set_password.expires", { date: expiry })}</p>
        ) : null}
      </form>
    </AuthShell>
  );
}
