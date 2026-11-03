"use client";

import Link from "next/link";
import { useState } from "react";
import { KeyRound, Loader2, MailCheck } from "lucide-react";

import { apiBase } from "@/lib/config";
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

export default function ForgotPasswordPage() {
  const t = useT();
  const [identifier, setIdentifier] = useState("");
  const [sent, setSent] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const value = identifier.trim();
    if (!value || loading) return;
    setErr(null);
    setLoading(true);
    try {
      const r = await fetch(`${apiBase()}/auth/password/forgot`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ identifier: value }),
        cache: "no-store",
      });
      if (r.status === 429) {
        setErr(t("forgot_password.error.rate_limited"));
        return;
      }
      // Risposta neutra (anti-enumeration): conferma sempre, salvo errori del server.
      if (!r.ok && r.status >= 500) {
        setErr(t("forgot_password.error.generic"));
        return;
      }
      setSent(true);
    } catch {
      setErr(t("forgot_password.error.network"));
    } finally {
      setLoading(false);
    }
  }

  const footer = (
    <Link href="/login" className={authQuietBtnCls}>
      {t("forgot_password.back_login")}
    </Link>
  );

  if (sent) {
    return (
      <AuthShell footer={footer}>
        <AuthHeading
          icon={<MailCheck className="h-5 w-5" aria-hidden />}
          title={t("forgot_password.sent_title")}
          description={t("forgot_password.sent_desc")}
        />
        <button
          type="button"
          onClick={() => {
            setSent(false);
            setErr(null);
          }}
          className={cn(authQuietBtnCls, "w-full")}
        >
          {t("forgot_password.try_again")}
        </button>
      </AuthShell>
    );
  }

  return (
    <AuthShell footer={footer}>
      <AuthHeading
        icon={<KeyRound className="h-5 w-5" aria-hidden />}
        title={t("forgot_password.title")}
        description={t("forgot_password.desc")}
      />
      <form onSubmit={submit} className="flex flex-col gap-3">
        <input
          className={authInputCls}
          placeholder={t("forgot_password.identifier")}
          aria-label={t("forgot_password.identifier")}
          value={identifier}
          onChange={(e) => setIdentifier(e.target.value)}
          autoComplete="username"
          autoCapitalize="none"
          spellCheck={false}
          autoFocus
        />
        {err && <AuthAlert>{err}</AuthAlert>}
        <button type="submit" disabled={loading || !identifier.trim()} className={cn(authPrimaryBtnCls, "mt-1")}>
          {loading ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
          {t("forgot_password.submit")}
        </button>
      </form>
    </AuthShell>
  );
}
