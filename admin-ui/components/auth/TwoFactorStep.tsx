"use client";

import { useEffect, useState } from "react";
import { ArrowLeft, Loader2, ShieldCheck } from "lucide-react";
import { cn } from "@/lib/cn";
import { AuthAlert, AuthHeading, authInputCls, authPrimaryBtnCls, authQuietBtnCls } from "@/components/auth/AuthShell";
import { apiBase } from "@/lib/api";

export type MfaChallenge = { stage: "enroll" | "verify"; token: string };

export type MfaLoginResult = {
  access_token?: string;
  user_id?: string;
  roles?: string[];
  must_change_password?: boolean;
};

type Enrollment = { qr_svg: string; secret: string };

function errorMessage(detail: unknown): string {
  const d = (detail ?? {}) as { code?: string; retry_after?: number };
  switch (d.code) {
    case "mfa_locked":
      return `Troppi tentativi. Riprova tra ${d.retry_after ?? 300} secondi.`;
    case "invalid_code":
      return "Codice non valido. Riprova.";
    case "invalid_mfa_token":
      return "Sessione scaduta. Effettua di nuovo il login.";
    default:
      return "Errore durante la verifica.";
  }
}

/** Secondo step del login admin quando il 2FA e' attivo (enroll con QR oppure verify). */
export function TwoFactorStep({
  challenge,
  onSuccess,
  onCancel,
}: {
  challenge: MfaChallenge;
  onSuccess: (result: MfaLoginResult) => void | Promise<void>;
  onCancel: () => void;
}) {
  const [enrollment, setEnrollment] = useState<Enrollment | null>(null);
  const [code, setCode] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const enroll = challenge.stage === "enroll";

  useEffect(() => {
    if (!enroll) return;
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
        setErr(errorMessage((j as { detail?: unknown }).detail));
        return;
      }
      setEnrollment(j as Enrollment);
    })();
    return () => {
      cancelled = true;
    };
  }, [enroll, challenge.token]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    setBusy(true);
    try {
      const r = await fetch(
        `${apiBase()}/auth/2fa/${enroll ? "enroll/confirm" : "verify"}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ mfa_token: challenge.token, code }),
        },
      );
      const j = await r.json().catch(() => ({}));
      if (!r.ok) {
        setErr(errorMessage((j as { detail?: unknown }).detail));
        setCode("");
        return;
      }
      await onSuccess(j as MfaLoginResult);
    } catch {
      setErr("Errore di rete");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-4">
      <AuthHeading
        as="h2"
        icon={<ShieldCheck className="h-5 w-5" aria-hidden />}
        title={enroll ? "Configura l'autenticazione a due fattori" : "Verifica in due passaggi"}
        description={
          enroll
            ? "Scansiona il QR code con Google Authenticator, Microsoft Authenticator o un'app equivalente, poi inserisci il codice a 6 cifre."
            : "Inserisci il codice a 6 cifre mostrato dalla tua app authenticator."
        }
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
          <p className="text-center text-xs text-muted-foreground">Non riesci a scansionare? Inserisci questa chiave manualmente:</p>
          <code className="w-full select-all break-all rounded-lg border border-border/60 bg-muted px-2.5 py-1.5 text-center font-mono text-xs text-foreground">
            {enrollment.secret}
          </code>
        </div>
      )}
      <input
        className={cn(
          authInputCls,
          "py-3 text-center font-mono text-xl tabular-nums tracking-[0.5em] placeholder:font-sans placeholder:text-sm placeholder:tracking-normal",
        )}
        placeholder="Codice a 6 cifre"
        aria-label="Codice a 6 cifre"
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
        {enroll ? "Conferma e accedi" : "Verifica"}
      </button>
      <button type="button" onClick={onCancel} className={cn(authQuietBtnCls, "self-center")}>
        <ArrowLeft className="h-3.5 w-3.5" aria-hidden />
        Torna al login
      </button>
    </form>
  );
}
