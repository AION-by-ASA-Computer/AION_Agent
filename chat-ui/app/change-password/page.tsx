"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { KeyRound, Loader2 } from "lucide-react";

import { apiBase } from "@/lib/config";
import { getStoredToken, setChangePwSkipUntil } from "@/lib/auth/storage";
import { isPasswordValid, PASSWORD_MAX_LENGTH, policyViolationsFromDetail } from "@/lib/auth/passwordPolicy";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";
import {
  AuthAlert,
  AuthHeading,
  AuthShell,
  authInputCls,
  authPrimaryBtnCls,
  authQuietBtnCls,
} from "@/components/auth/AuthShell";
import { PasswordChecklist, passwordPolicyErrorMessage } from "@/components/auth/PasswordChecklist";

const ONE_DAY_MS = 24 * 60 * 60 * 1000;

export default function ChangePasswordPage() {
  const router = useRouter();
  const t = useT();
  const [oldPw, setOldPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [confirmPw, setConfirmPw] = useState("");
  const [identifier, setIdentifier] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [ok, setOk] = useState(false);
  const [loading, setLoading] = useState(false);
  // null finche' /auth/me non risponde: evita il flash del bottone "skip".
  const [required, setRequired] = useState<boolean | null>(null);

  // Identifier per la regola "non contiene lo username" della checklist;
  // password_change_required = password temporanea da cambiare (niente skip).
  useEffect(() => {
    // Senza token /auth/me risponde 401 → required=false (setState solo nel callback).
    const token = getStoredToken();
    let cancelled = false;
    void fetch(`${apiBase()}/auth/me`, {
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      cache: "no-store",
    })
      .then((r) => (r.ok ? r.json() : null))
      .then((me: { identifier?: string; password_change_required?: boolean } | null) => {
        if (cancelled) return;
        if (me?.identifier) setIdentifier(me.identifier);
        setRequired(Boolean(me?.password_change_required));
      })
      .catch(() => {
        if (!cancelled) setRequired(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const mismatch = confirmPw.length > 0 && newPw !== confirmPw;
  const canSubmit = oldPw.length > 0 && isPasswordValid(newPw, identifier) && newPw === confirmPw && !loading && !ok;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    setErr(null);
    const token = getStoredToken();
    if (!token) {
      setErr(t("change_password.session_expired"));
      return;
    }
    setLoading(true);
    try {
      const r = await fetch(`${apiBase()}/auth/change-password`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ old_password: oldPw, new_password: newPw }),
      });
      const j = (await r.json().catch(() => ({}))) as { detail?: unknown };
      if (!r.ok) {
        const violations = r.status === 422 ? policyViolationsFromDetail(j.detail) : null;
        if (violations) setErr(passwordPolicyErrorMessage(t, violations));
        else setErr(typeof j.detail === "string" ? j.detail : t("change_password.error"));
        return;
      }
      setOk(true);
      setTimeout(() => router.replace("/"), 900);
    } catch {
      setErr(t("toast.conn_error"));
    } finally {
      setLoading(false);
    }
  }

  function skip() {
    setChangePwSkipUntil(Date.now() + ONE_DAY_MS);
    router.replace("/");
  }

  return (
    <AuthShell>
      <AuthHeading
        icon={<KeyRound className="h-5 w-5" aria-hidden />}
        title={required ? t("change_password.title_required") : t("change_password.title")}
        description={required ? t("change_password.desc_required") : t("change_password.desc")}
      />
      <form onSubmit={submit} className="flex flex-col gap-3">
        <input
          type="password"
          className={authInputCls}
          placeholder={required ? t("change_password.current_temp") : t("change_password.current")}
          aria-label={required ? t("change_password.current_temp") : t("change_password.current")}
          value={oldPw}
          onChange={(e) => setOldPw(e.target.value)}
          autoComplete="current-password"
          autoFocus
        />
        <input
          type="password"
          className={authInputCls}
          placeholder={t("change_password.new")}
          aria-label={t("change_password.new")}
          aria-describedby="change-password-rules"
          value={newPw}
          onChange={(e) => setNewPw(e.target.value)}
          maxLength={PASSWORD_MAX_LENGTH}
          autoComplete="new-password"
        />
        <PasswordChecklist id="change-password-rules" password={newPw} identifier={identifier} className="px-1" />
        <input
          type="password"
          className={cn(authInputCls, mismatch && "border-destructive/60 focus:border-destructive")}
          placeholder={t("change_password.confirm")}
          aria-label={t("change_password.confirm")}
          aria-invalid={mismatch}
          value={confirmPw}
          onChange={(e) => setConfirmPw(e.target.value)}
          maxLength={PASSWORD_MAX_LENGTH}
          autoComplete="new-password"
        />
        {mismatch ? <p className="px-1 text-xs text-destructive">{t("change_password.mismatch")}</p> : null}
        {err && <AuthAlert>{err}</AuthAlert>}
        {ok && <AuthAlert tone="success">{t("change_password.success")}</AuthAlert>}
        <button type="submit" disabled={!canSubmit} className={cn(authPrimaryBtnCls, "mt-1")}>
          {loading ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
          {t("change_password.submit")}
        </button>
        {required === false ? (
          <button type="button" onClick={skip} className={cn(authQuietBtnCls, "self-center")}>
            {t("change_password.skip")}
          </button>
        ) : null}
      </form>
    </AuthShell>
  );
}
