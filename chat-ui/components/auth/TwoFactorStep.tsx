"use client";

import { useEffect, useState } from "react";
import { apiBase } from "@/lib/config";
import { useT } from "@/lib/i18n/use-t";
import { Loader2, ShieldCheck } from "lucide-react";
import { cn } from "@/lib/cn";
import { AuthAlert, AuthHeading, authInputCls, authPrimaryBtnCls, authQuietBtnCls } from "@/components/auth/AuthShell";

export type MfaChallenge = {
  stage: "enroll" | "verify";
  token: string;
};

export type MfaLoginResult = {
  access_token?: string;
  user_id?: string;
  password_change_required?: boolean;
};

type Enrollment = { qr_svg: string; secret: string };

type ErrorDetail = { code?: string; retry_after?: number } | string | unknown;

/**
 * Secondo step del login con password quando il 2FA e' attivo.
 * `enroll`: mostra il QR e conferma il primo codice; `verify`: solo il codice.
 */
export function TwoFactorStep({
  challenge,
  onSuccess,
  onCancel,
}: {
  challenge: MfaChallenge;
  onSuccess: (result: MfaLoginResult) => void | Promise<void>;
  onCancel: () => void;
}) {
  const t = useT();
  const [enrollment, setEnrollment] = useState<Enrollment | null>(null);
  const [code, setCode] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function errorMessage(detail: ErrorDetail): string {
    const d = (detail ?? {}) as { code?: string; retry_after?: number };
    if (d.code === "mfa_locked") {
      return t("login.mfa.error.mfa_locked", { seconds: d.retry_after ?? 300 });
    }
    if (d.code === "invalid_code") return t("login.mfa.error.invalid_code");
    if (d.code === "invalid_mfa_token") return t("login.mfa.error.invalid_mfa_token");
    return t("login.mfa.error.generic");
  }

  useEffect(() => {
    if (challenge.stage !== "enroll") return;
    let cancelled = false;
    (async () => {
      const r = await fetch(`${apiBase()}/auth/2fa/enroll/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mfa_token: challenge.token }),
      });
      const j = await r.json().catch(() => ({}));
      if (cancelled) return;
      if (!r.ok) {
        setErr(errorMessage((j as { detail?: ErrorDetail }).detail));
        return;
      }
      setEnrollment(j as Enrollment);
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [challenge.stage, challenge.token]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    setBusy(true);
    try {
      const path = challenge.stage === "enroll" ? "enroll/confirm" : "verify";
      const r = await fetch(`${apiBase()}/auth/2fa/${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mfa_token: challenge.token, code }),
      });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) {
        setErr(errorMessage((j as { detail?: ErrorDetail }).detail));
        setCode("");
        return;
      }
      await onSuccess(j as MfaLoginResult);
    } catch {
      setErr(t("login.mfa.error.generic"));
    } finally {
      setBusy(false);
    }
  }

  const enroll = challenge.stage === "enroll";

  return (
    <form onSubmit={submit} className="flex flex-col gap-4">
      <AuthHeading
        as="h2"
        icon={<ShieldCheck className="h-5 w-5" aria-hidden />}
        title={enroll ? t("login.mfa.title_enroll") : t("login.mfa.title_verify")}
        description={enroll ? t("login.mfa.enroll_help") : t("login.mfa.verify_help")}
      />
      {enroll && enrollment && (
        <div className="-mt-2 flex flex-col items-center gap-3">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={enrollment.qr_svg}
            alt="QR code"
            width={176}
            height={176}
            className="rounded-xl border border-border/70 bg-white p-2 shadow-sm"
          />
          <p className="text-center text-xs text-muted-foreground">{t("login.mfa.manual")}</p>
          <code className="w-full select-all break-all rounded-lg bg-muted/80 px-2.5 py-1.5 text-center font-mono text-xs text-foreground ring-1 ring-border/50">
            {enrollment.secret}
          </code>
        </div>
      )}
      {enroll && !enrollment && !err && (
        <p className="flex items-center justify-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin text-primary" aria-hidden />
          {t("login.mfa.loading")}
        </p>
      )}
      <input
        className={cn(
          authInputCls,
          "py-3 text-center font-mono text-xl tabular-nums tracking-[0.5em] placeholder:font-sans placeholder:text-sm placeholder:tracking-normal",
        )}
        placeholder={t("login.mfa.code")}
        aria-label={t("login.mfa.code")}
        value={code}
        onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
        inputMode="numeric"
        autoComplete="one-time-code"
        maxLength={6}
        autoFocus
      />
      {err && <AuthAlert>{err}</AuthAlert>}
      <button
        type="submit"
        disabled={busy || code.length !== 6 || (enroll && !enrollment)}
        className={authPrimaryBtnCls}
      >
        {busy ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
        {enroll ? t("login.mfa.confirm") : t("login.mfa.verify")}
      </button>
      <button type="button" onClick={onCancel} className={cn(authQuietBtnCls, "self-center")}>
        {t("login.mfa.back")}
      </button>
    </form>
  );
}
