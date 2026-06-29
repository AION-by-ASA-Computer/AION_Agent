"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { KeyRound, Loader2, AlertCircle, CheckCircle2 } from "lucide-react";

import { apiBase } from "@/lib/config";
import { getStoredToken, setChangePwSkipUntil } from "@/lib/auth/storage";

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
      setErr("The confirmation does not match the new password.");
      return;
    }
    const token = getStoredToken();
    if (!token) {
      setErr("Session expired. Please log in again.");
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
    <div className="flex min-h-screen flex-col items-center justify-center gap-6 bg-background px-4 text-foreground">
      <div className="flex flex-col items-center gap-2">
        <div className="w-14 h-14 rounded-2xl bg-amber-500/15 border border-amber-500/30 flex items-center justify-center">
          <KeyRound className="text-amber-400" size={28} aria-hidden />
        </div>
        <h1 className="text-xl font-semibold tracking-tight">Change password</h1>
        <p className="text-sm text-muted-foreground text-center max-w-sm">
          You are using a temporary password. Update it now or
          remind me tomorrow (skippable for 24h).
        </p>
      </div>

      <form onSubmit={submit} className="flex w-full max-w-sm flex-col gap-3">
        <input
          type="password"
          className="focus-ring rounded-aion border border-input bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground"
          placeholder="Current password"
          value={oldPw}
          onChange={(e) => setOldPw(e.target.value)}
          autoComplete="current-password"
          autoFocus
        />
        <input
          type="password"
          className="focus-ring rounded-aion border border-input bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground"
          placeholder="New password (min. 6 characters)"
          value={newPw}
          onChange={(e) => setNewPw(e.target.value)}
          autoComplete="new-password"
        />
        <input
          type="password"
          className="focus-ring rounded-aion border border-input bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground"
          placeholder="Confirm new password"
          value={confirmPw}
          onChange={(e) => setConfirmPw(e.target.value)}
          autoComplete="new-password"
        />
        {err && (
          <div
            className="flex items-start gap-2 rounded-aion border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive"
            role="alert"
          >
            <AlertCircle size={16} className="mt-0.5 shrink-0" aria-hidden />
            <span>{err}</span>
          </div>
        )}
        {ok && (
          <div
            className="flex items-center gap-2 rounded-aion border border-primary/40 bg-primary/10 p-3 text-sm text-primary"
            role="status"
          >
            <CheckCircle2 size={16} aria-hidden />
            Password updated. Redirecting…
          </div>
        )}
        <button
          type="submit"
          disabled={loading || ok}
          className="focus-ring rounded-aion flex items-center justify-center gap-2 bg-primary py-2.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-60"
        >
          {loading ? <Loader2 className="animate-spin" size={16} aria-hidden /> : null}
          Update password
        </button>
        <button
          type="button"
          onClick={skip}
          className="focus-ring rounded-aion px-4 py-2 text-xs text-muted-foreground hover:text-foreground"
        >
          Remind me tomorrow
        </button>
      </form>
    </div>
  );
}
