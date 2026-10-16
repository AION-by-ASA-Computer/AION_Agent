"use client";

import { useEffect, useState } from "react";
import { Loader2, AlertCircle } from "lucide-react";
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
    <form onSubmit={submit} className="flex w-full flex-col gap-3">
      <h2 className="text-lg font-semibold">
        {enroll ? "Configura l'autenticazione a due fattori" : "Verifica in due passaggi"}
      </h2>
      <p className="text-sm text-gray-400">
        {enroll
          ? "Scansiona il QR code con Google Authenticator, Microsoft Authenticator o un'app equivalente, poi inserisci il codice a 6 cifre."
          : "Inserisci il codice a 6 cifre mostrato dalla tua app authenticator."}
      </p>
      {enroll && enrollment && (
        <div className="flex flex-col items-center gap-2">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={enrollment.qr_svg}
            alt="QR code"
            width={192}
            height={192}
            className="rounded-xl bg-white p-1"
          />
          <p className="text-xs text-gray-500">Non riesci a scansionare? Inserisci questa chiave manualmente:</p>
          <code className="select-all break-all rounded bg-white/5 border border-white/10 px-2 py-1 text-xs text-gray-300">
            {enrollment.secret}
          </code>
        </div>
      )}
      <input
        className="w-full rounded-xl border border-[#262626] bg-[#141414] px-4 py-2.5 text-center text-lg tracking-[0.4em] text-white placeholder:text-gray-500 placeholder:tracking-normal outline-none focus:border-emerald-500/50 focus:ring-2 focus:ring-emerald-500/20 transition"
        placeholder="Codice a 6 cifre"
        value={code}
        onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
        inputMode="numeric"
        autoComplete="one-time-code"
        maxLength={6}
        autoFocus
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
        disabled={busy || code.length !== 6 || (enroll && !enrollment)}
        className="mt-1 flex items-center justify-center gap-2 rounded-xl bg-emerald-500/20 px-4 py-2.5 text-sm font-medium text-emerald-300 hover:bg-emerald-500/30 border border-emerald-500/30 disabled:opacity-60 transition"
      >
        {busy ? <Loader2 className="animate-spin" size={16} aria-hidden /> : null}
        {enroll ? "Conferma e accedi" : "Verifica"}
      </button>
      <button
        type="button"
        onClick={onCancel}
        className="text-xs text-emerald-400 hover:underline"
      >
        ← Torna al login
      </button>
    </form>
  );
}
