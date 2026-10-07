"use client";

import { useEffect, useState } from "react";
import { apiBase } from "@/lib/config";
import { useT } from "@/lib/i18n/use-t";

export type MfaChallenge = {
  stage: "enroll" | "verify";
  token: string;
};

export type MfaLoginResult = {
  access_token?: string;
  user_id?: string;
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
    <form onSubmit={submit} className="flex w-full max-w-sm flex-col gap-3">
      <h2 className="text-lg font-semibold text-foreground">
        {enroll ? t("login.mfa.title_enroll") : t("login.mfa.title_verify")}
      </h2>
      <p className="text-sm text-muted-foreground">
        {enroll ? t("login.mfa.enroll_help") : t("login.mfa.verify_help")}
      </p>
      {enroll && enrollment && (
        <div className="flex flex-col items-center gap-2">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={enrollment.qr_svg}
            alt="QR code"
            width={192}
            height={192}
            className="rounded-aion border border-input bg-white p-1"
          />
          <p className="text-xs text-muted-foreground">{t("login.mfa.manual")}</p>
          <code className="select-all break-all rounded bg-muted px-2 py-1 text-xs">
            {enrollment.secret}
          </code>
        </div>
      )}
      {enroll && !enrollment && !err && (
        <p className="text-sm text-muted-foreground">{t("login.mfa.loading")}</p>
      )}
      <input
        className="focus-ring rounded-aion border border-input bg-background px-3 py-2 text-center text-lg tracking-[0.4em] text-foreground placeholder:text-muted-foreground"
        placeholder={t("login.mfa.code")}
        value={code}
        onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
        inputMode="numeric"
        autoComplete="one-time-code"
        maxLength={6}
        autoFocus
      />
      {err && (
        <p className="text-sm text-destructive" role="alert">
          {err}
        </p>
      )}
      <button
        type="submit"
        disabled={busy || code.length !== 6 || (enroll && !enrollment)}
        className="focus-ring rounded-aion bg-primary py-2.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-60"
      >
        {enroll ? t("login.mfa.confirm") : t("login.mfa.verify")}
      </button>
      <button
        type="button"
        onClick={onCancel}
        className="focus-ring text-xs text-primary underline-offset-2 hover:underline"
      >
        {t("login.mfa.back")}
      </button>
    </form>
  );
}
