"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { KeyRound, Loader2 } from "lucide-react";

import { apiBase } from "@/lib/api";
import { setChangePwSkipUntil } from "@/lib/auth/storage";
import { apiFetch } from "@/lib/api/headers";
import { cn } from "@/lib/cn";
import {
  AuthAlert,
  AuthHeading,
  AuthShell,
  authInputCls,
  authPrimaryBtnCls,
  authQuietBtnCls,
} from "@/components/auth/AuthShell";

const ONE_DAY_MS = 24 * 60 * 60 * 1000;

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
    if (newPw.length < 6) {
      setErr("The new password must be at least 6 characters long.");
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
      const j = (await r.json().catch(() => ({}))) as { detail?: string };
      if (!r.ok) {
        setErr(j?.detail || "Password change failed");
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
          placeholder="New password (min. 6 characters)"
          aria-label="New password (min. 6 characters)"
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
