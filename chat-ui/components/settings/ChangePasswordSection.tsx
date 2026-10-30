"use client";

import { useState } from "react";
import { KeyRound, Loader2 } from "lucide-react";

import { apiBase } from "@/lib/config";
import { useStoredToken } from "@/lib/auth/use-stored-auth";
import { useT } from "@/lib/i18n/use-t";
import { isPasswordValid, PASSWORD_MAX_LENGTH, policyViolationsFromDetail } from "@/lib/auth/passwordPolicy";
import { PasswordChecklist, passwordPolicyErrorMessage } from "@/components/auth/PasswordChecklist";
import { Field, FieldGrid, Group, Note, inputCls, solidBtn } from "./ui";

export function ChangePasswordSection({
  onSuccess,
  identifier = "",
}: {
  onSuccess?: (message: string) => void;
  /** Username corrente: abilita la regola "non contiene lo username". */
  identifier?: string;
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
    if (!isPasswordValid(newPw, identifier)) {
      setErr(t("settings.security.password_policy"));
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
      const j = (await r.json().catch(() => ({}))) as { detail?: unknown };
      if (!r.ok) {
        const violations = r.status === 422 ? policyViolationsFromDetail(j.detail) : null;
        if (violations) setErr(passwordPolicyErrorMessage(t, violations));
        else setErr(typeof j.detail === "string" ? j.detail : t("settings.security.password_error"));
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
  const valid = filled && isPasswordValid(newPw, identifier) && newPw === confirmPw;

  return (
    <form onSubmit={submit}>
      <Group
        title={t("settings.security.password_title")}
        description={t("settings.security.password_desc")}
        footer={
          <button type="submit" disabled={loading || !valid} className={solidBtn}>
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
          <Field label={t("settings.security.new_password")}>
            <input
              type="password"
              className={inputCls}
              value={newPw}
              onChange={(e) => setNewPw(e.target.value)}
              autoComplete="new-password"
              maxLength={PASSWORD_MAX_LENGTH}
              aria-describedby="settings-password-rules"
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
          <div className="md:col-span-2">
            <PasswordChecklist id="settings-password-rules" password={newPw} identifier={identifier} />
            {confirmPw.length > 0 && newPw !== confirmPw ? (
              <p className="mt-1.5 text-xs text-destructive">{t("settings.security.password_mismatch")}</p>
            ) : null}
          </div>
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
