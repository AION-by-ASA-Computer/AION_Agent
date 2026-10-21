"use client";

import { useState } from "react";
import { KeyRound, Loader2 } from "lucide-react";

import { apiBase } from "@/lib/config";
import { useStoredToken } from "@/lib/auth/use-stored-auth";
import { useT } from "@/lib/i18n/use-t";
import { Field, FieldGrid, Group, Note, inputCls, solidBtn } from "./ui";

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
  const [loading, setLoading] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
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
      setOldPw("");
      setNewPw("");
      setConfirmPw("");
      onSuccess?.(t("settings.security.password_updated"));
    } catch {
      setErr(t("toast.conn_error"));
    } finally {
      setLoading(false);
    }
  }

  const filled = oldPw.length > 0 && newPw.length > 0 && confirmPw.length > 0;

  return (
    <form onSubmit={submit}>
      <Group
        title={t("settings.security.password_title")}
        description={t("settings.security.password_desc")}
        footer={
          <button type="submit" disabled={loading || !filled} className={solidBtn}>
            {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <KeyRound className="h-3.5 w-3.5" aria-hidden />}
            {t("settings.security.update_password")}
          </button>
        }
      >
        <FieldGrid>
          <Field label={t("settings.security.current_password")} wide>
            <input
              type="password"
              className={`${inputCls} md:max-w-[calc(50%-var(--spacing)*2.5)]`}
              value={oldPw}
              onChange={(e) => setOldPw(e.target.value)}
              autoComplete="current-password"
            />
          </Field>
          <Field label={t("settings.security.new_password")} hint={t("settings.security.password_hint")}>
            <input
              type="password"
              className={inputCls}
              value={newPw}
              onChange={(e) => setNewPw(e.target.value)}
              autoComplete="new-password"
              minLength={6}
            />
          </Field>
          <Field label={t("settings.security.confirm_password")}>
            <input
              type="password"
              className={inputCls}
              value={confirmPw}
              onChange={(e) => setConfirmPw(e.target.value)}
              autoComplete="new-password"
            />
          </Field>
          {err ? (
            <div className="md:col-span-2">
              <Note tone="error">{err}</Note>
            </div>
          ) : null}
        </FieldGrid>
      </Group>
    </form>
  );
}
