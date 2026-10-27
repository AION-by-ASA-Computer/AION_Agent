"use client";

import { useState } from "react";
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
        title="Change password"
        description="You're using a default password. Change it now or remind me tomorrow (skippable for 24h)."
      />
      <form onSubmit={submit} className="flex flex-col gap-3">
        <input
          type="password"
          className={authInputCls}
          placeholder="Current password"
          aria-label="Current password"
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
        <button type="button" onClick={skip} className={cn(authQuietBtnCls, "self-center")}>
          Remind me tomorrow
        </button>
      </form>
    </AuthShell>
  );
}
