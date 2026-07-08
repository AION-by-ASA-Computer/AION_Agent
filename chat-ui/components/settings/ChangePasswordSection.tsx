"use client";

import { useState } from "react";
import { AlertCircle, CheckCircle2, KeyRound, Loader2 } from "lucide-react";

import { apiBase } from "@/lib/config";
import { useStoredToken } from "@/lib/auth/use-stored-auth";
import { useT } from "@/lib/i18n/use-t";
import { SettingsFieldRow } from "./SettingsCard";

export function ChangePasswordSection({
  onSuccess,
}: {
  onSuccess?: (message: string) => void;
}) {
  const t = useT();
  const token = useStoredToken();
  const [oldPw, setOldPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [confirmPw, setConfirmPw] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [ok, setOk] = useState(false);
  const [loading, setLoading] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    setOk(false);
    if (newPw.length < 6) {
      setErr(t("settings.security.password_min"));
      return;
    }
    if (newPw !== confirmPw) {
      setErr(t("settings.security.password_mismatch"));
      return;
    }
    if (!token) {
      setErr(t("toast.no_token"));
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
      const j = (await r.json().catch(() => ({}))) as { detail?: string };
      if (!r.ok) {
        setErr(j?.detail || t("settings.security.password_error"));
        return;
      }
      setOk(true);
      setOldPw("");
      setNewPw("");
      setConfirmPw("");
      onSuccess?.(t("settings.security.password_updated"));
    } finally {
      setLoading(false);
    }
  }

  const inputClass =
    "focus-ring w-full rounded-xl border border-border/50 bg-background/50 px-3.5 py-2.5 text-sm text-foreground outline-none transition focus:border-primary focus:ring-1 focus:ring-primary";

  return (
    <form onSubmit={submit} className="space-y-1">
      <SettingsFieldRow label={t("settings.security.current_password")}>
        <input
          type="password"
          className={inputClass}
          value={oldPw}
          onChange={(e) => setOldPw(e.target.value)}
          autoComplete="current-password"
        />
      </SettingsFieldRow>
      <SettingsFieldRow label={t("settings.security.new_password")}>
        <input
          type="password"
          className={inputClass}
          value={newPw}
          onChange={(e) => setNewPw(e.target.value)}
          autoComplete="new-password"
        />
      </SettingsFieldRow>
      <SettingsFieldRow
        label={t("settings.security.confirm_password")}
        hint={t("settings.security.password_hint")}
      >
        <input
          type="password"
          className={inputClass}
          value={confirmPw}
          onChange={(e) => setConfirmPw(e.target.value)}
          autoComplete="new-password"
        />
      </SettingsFieldRow>

      {err ? (
        <div className="flex items-start gap-2 rounded-xl border border-destructive/40 bg-destructive/10 px-3 py-2.5 text-xs text-destructive">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
          <span>{err}</span>
        </div>
      ) : null}
      {ok ? (
        <div className="flex items-center gap-2 rounded-xl border border-primary/40 bg-primary/10 px-3 py-2.5 text-xs text-primary">
          <CheckCircle2 className="h-4 w-4" aria-hidden />
          <span>{t("settings.security.password_updated")}</span>
        </div>
      ) : null}

      <div className="flex justify-end pt-3">
        <button
          type="submit"
          disabled={loading}
          className="focus-ring inline-flex items-center gap-2 rounded-xl bg-primary px-4 py-2.5 text-xs font-semibold text-primary-foreground transition hover:bg-primary/90 disabled:opacity-50"
        >
          {loading ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <KeyRound className="h-4 w-4" aria-hidden />}
          {t("settings.security.update_password")}
        </button>
      </div>
    </form>
  );
}
