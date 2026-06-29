"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { KeyRound, Loader2, AlertCircle, CheckCircle2 } from "lucide-react";

import { apiBase } from "@/lib/api";
import { setChangePwSkipUntil } from "@/lib/auth/storage";
import { apiFetch } from "@/lib/api/headers";

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
    <div className="min-h-screen w-full flex items-center justify-center bg-[#0a0a0a] px-4 py-12 text-white">
      <div className="w-full max-w-sm flex flex-col items-center gap-6">
        <div className="flex flex-col items-center gap-3">
          <div className="w-14 h-14 rounded-2xl bg-amber-500/15 border border-amber-500/30 flex items-center justify-center">
            <KeyRound className="text-amber-400" size={28} aria-hidden />
          </div>
          <h1 className="text-2xl font-bold tracking-tight">Change password</h1>
          <p className="text-sm text-gray-400 text-center max-w-xs">
            You're using a default password. Change it now or remind me tomorrow (skippable for 24h).
          </p>
        </div>

        <form onSubmit={submit} className="flex w-full flex-col gap-3">
          <input
            type="password"
            className="w-full rounded-xl border border-[#262626] bg-[#141414] px-4 py-2.5 text-sm text-white placeholder:text-gray-500 outline-none focus:border-emerald-500/50 focus:ring-2 focus:ring-emerald-500/20 transition"
            placeholder="Current password"
            value={oldPw}
            onChange={(e) => setOldPw(e.target.value)}
            autoComplete="current-password"
            autoFocus
          />
          <input
            type="password"
            className="w-full rounded-xl border border-[#262626] bg-[#141414] px-4 py-2.5 text-sm text-white placeholder:text-gray-500 outline-none focus:border-emerald-500/50 focus:ring-2 focus:ring-emerald-500/20 transition"
            placeholder="New password (min. 6 characters)"
            value={newPw}
            onChange={(e) => setNewPw(e.target.value)}
            autoComplete="new-password"
          />
          <input
            type="password"
            className="w-full rounded-xl border border-[#262626] bg-[#141414] px-4 py-2.5 text-sm text-white placeholder:text-gray-500 outline-none focus:border-emerald-500/50 focus:ring-2 focus:ring-emerald-500/20 transition"
            placeholder="Confirm new password"
            value={confirmPw}
            onChange={(e) => setConfirmPw(e.target.value)}
            autoComplete="new-password"
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
          {ok && (
            <div
              className="flex items-center gap-2 rounded-xl border border-emerald-500/30 bg-emerald-500/10 p-3 text-sm text-emerald-300"
              role="status"
            >
              <CheckCircle2 size={16} aria-hidden />
              Password updated. Redirecting…
            </div>
          )}
          <button
            type="submit"
            disabled={loading || ok}
            className="mt-1 flex items-center justify-center gap-2 rounded-xl bg-emerald-500/20 px-4 py-2.5 text-sm font-medium text-emerald-300 hover:bg-emerald-500/30 border border-emerald-500/30 disabled:opacity-60 transition"
          >
            {loading ? <Loader2 className="animate-spin" size={16} aria-hidden /> : null}
            Update password
          </button>
          <button
            type="button"
            onClick={skip}
            className="rounded-xl px-4 py-2 text-xs text-gray-500 hover:text-gray-300 hover:bg-white/5 border border-transparent hover:border-white/10 transition"
          >
            Remind me tomorrow
          </button>
        </form>
      </div>
    </div>
  );
}
