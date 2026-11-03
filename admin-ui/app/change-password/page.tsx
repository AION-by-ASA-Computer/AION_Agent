"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { KeyRound, Loader2 } from "lucide-react";

import { apiBase } from "@/lib/api";
import { setChangePwSkipUntil } from "@/lib/auth/storage";
import { apiFetch } from "@/lib/api/headers";
import { cn } from "@/lib/cn";
import { PASSWORD_MIN_LENGTH, checkPassword, type PasswordRule } from "@/lib/passwordPolicy";
import {
  AuthAlert,
  AuthHeading,
  AuthShell,
  authInputCls,
  authPrimaryBtnCls,
  authQuietBtnCls,
} from "@/components/auth/AuthShell";

const ONE_DAY_MS = 24 * 60 * 60 * 1000;

// Same rules the backend enforces (src/data/user_password.py).
const RULE_TEXT: Record<PasswordRule, string> = {
  too_short: `at least ${PASSWORD_MIN_LENGTH} characters`,
  lowercase: "a lowercase letter",
  uppercase: "an uppercase letter",
  digit: "a number",
  symbol: "a symbol (e.g. ! @ # -)",
  contains_username: "must not contain your username",
};

const describe = (codes: string[]) => `The new password needs ${codes.map((c) => RULE_TEXT[c as PasswordRule] ?? c).join(", ")}.`;

export default function ChangePasswordPage() {
  const router = useRouter();
  const [oldPw, setOldPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [confirmPw, setConfirmPw] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [ok, setOk] = useState(false);
  const [loading, setLoading] = useState(false);
  // Temporary password from an admin: the change can't be skipped (the backend blocks everything else meanwhile).
  // null until /auth/me answers, so the skip button never flashes.
  const [required, setRequired] = useState<boolean | null>(null);

  useEffect(() => {
    let cancelled = false;
    apiFetch(`${apiBase()}/auth/me`, { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : {}))
      .then((me: { password_change_required?: boolean }) => !cancelled && setRequired(!!me.password_change_required))
      .catch(() => !cancelled && setRequired(false));
    return () => {
      cancelled = true;
    };
  }, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    const failing = checkPassword(newPw).filter((r) => !r.ok).map((r) => r.code);
    if (failing.length) {
      setErr(describe(failing));
      return;
    }
    if (newPw !== confirmPw) {
      setErr("Confirmation does not match the new password.");
      return;
    }
    setLoading(true);
    try {
      const r = await apiFetch(`${apiBase()}/auth/change-password`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ old_password: oldPw, new_password: newPw }),
      });
      const j = (await r.json().catch(() => ({}))) as { detail?: string | { code?: string; violations?: string[] } };
      if (!r.ok) {
        const d = j?.detail;
        if (typeof d === "object" && d?.code === "password_policy") setErr(describe(d.violations ?? []));
        else setErr((typeof d === "string" && d) || "Password change failed");
        return;
      }
      setOk(true);
      setTimeout(() => router.replace("/"), 900);
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
        title={required ? "Set your own password" : "Change password"}
        description={
          required
            ? "You signed in with a temporary password provided by an administrator. Choose a new password to continue."
            : "You're using a default password. Change it now or remind me tomorrow (skippable for 24h)."
        }
      />
      <form onSubmit={submit} className="flex flex-col gap-3">
        <input
          type="password"
          className={authInputCls}
          placeholder={required ? "Temporary password" : "Current password"}
          aria-label={required ? "Temporary password" : "Current password"}
          value={oldPw}
          onChange={(e) => setOldPw(e.target.value)}
          autoComplete="current-password"
          autoFocus
        />
        <input
          type="password"
          className={authInputCls}
          placeholder="New password (min. 8 characters, mixed case, number, symbol)"
          aria-label="New password (min. 8 characters, mixed case, number, symbol)"
          value={newPw}
          onChange={(e) => setNewPw(e.target.value)}
          autoComplete="new-password"
        />
        <input
          type="password"
          className={authInputCls}
          placeholder="Confirm new password"
          aria-label="Confirm new password"
          value={confirmPw}
          onChange={(e) => setConfirmPw(e.target.value)}
          autoComplete="new-password"
        />
        {err && <AuthAlert>{err}</AuthAlert>}
        {ok && <AuthAlert tone="success">Password updated. Redirecting…</AuthAlert>}
        <button type="submit" disabled={loading || ok} className={cn(authPrimaryBtnCls, "mt-1")}>
          {loading ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
          Update password
        </button>
        {required === false && (
          <button type="button" onClick={skip} className={cn(authQuietBtnCls, "self-center")}>
            Remind me tomorrow
          </button>
        )}
      </form>
    </AuthShell>
  );
}
