"use client";

import { useEffect, useState } from "react";
import { AlertTriangle, Loader2, ShieldCheck } from "lucide-react";
import { apiBase } from "@/lib/api";
import { apiFetch } from "@/lib/api/headers";

interface TwoFactorStatus {
  required: boolean;
  effective: boolean;
  available: boolean;
  force_disabled: boolean;
  enrolled_users: number;
  password_users: number;
}

/** Interruttore admin per il 2FA (TOTP) del login con password. */
export function TwoFactorPanel() {
  const [status, setStatus] = useState<TwoFactorStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    try {
      const res = await apiFetch(`${apiBase()}/admin/auth/2fa`);
      if (res.ok) setStatus(await res.json());
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const toggle = async (required: boolean) => {
    if (
      required &&
      !window.confirm(
        "Attivando il 2FA, al prossimo login ogni utente con password dovrà configurare un'app authenticator (anche tu). Continuare?",
      )
    ) {
      return;
    }
    setError(null);
    setSaving(true);
    try {
      const res = await apiFetch(`${apiBase()}/admin/auth/2fa`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ required }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const code = data?.detail?.code;
        setError(
          code === "sso_active"
            ? "Il 2FA è disponibile solo con il login classico (password): disattiva prima l'SSO."
            : "Impossibile aggiornare l'impostazione.",
        );
        return;
      }
      setStatus(data);
    } catch (e: any) {
      setError(e?.message || "Errore di rete");
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return <Loader2 className="w-5 h-5 animate-spin text-gray-500" />;
  }
  if (!status) return null;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-4 rounded-xl border border-[#262626] bg-[#141414] p-4">
        <div className="flex items-start gap-3">
          <ShieldCheck className="w-5 h-5 text-emerald-400 mt-0.5" />
          <div>
            <div className="text-sm font-semibold text-white">Richiedi 2FA al login con password</div>
            <div className="text-xs text-gray-400 mt-1">
              Utenti configurati: {status.enrolled_users} / {status.password_users}
              {status.required && !status.effective && !status.force_disabled && " · non attivo con SSO"}
            </div>
          </div>
        </div>
        <button
          type="button"
          role="switch"
          aria-checked={status.required}
          disabled={saving || (!status.available && !status.required)}
          onClick={() => toggle(!status.required)}
          className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full border transition disabled:opacity-50 ${
            status.required ? "bg-emerald-500/40 border-emerald-500/50" : "bg-white/5 border-white/10"
          }`}
        >
          <span
            className={`inline-block h-4 w-4 rounded-full bg-white transition-transform ${
              status.required ? "translate-x-6" : "translate-x-1"
            }`}
          />
        </button>
      </div>
      {!status.available && (
        <div className="flex items-start gap-2 text-xs text-amber-300">
          <AlertTriangle className="w-4 h-4 shrink-0" />
          Il 2FA vale solo per il login classico: con SSO attivo non viene applicato.
        </div>
      )}
      {status.force_disabled && (
        <div className="flex items-start gap-2 text-xs text-amber-300">
          <AlertTriangle className="w-4 h-4 shrink-0" />
          AION_2FA_FORCE_DISABLE=1 è impostato sul server: il 2FA è temporaneamente ignorato.
        </div>
      )}
      {error && <div className="text-xs text-red-400">{error}</div>}
    </div>
  );
}
