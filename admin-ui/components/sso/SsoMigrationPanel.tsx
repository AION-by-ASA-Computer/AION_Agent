"use client";

import { useEffect, useState } from "react";
import { apiBase } from "@/lib/api";
import { apiFetch } from "@/lib/api/headers";
import { Shield, Users, Key, AlertTriangle, CheckCircle2, ChevronRight, Loader2 } from "lucide-react";
import { TempPasswordsDialog } from "./TempPasswordsDialog";
import { SsoConfigPanel } from "./SsoConfigPanel";

type LoginMode = "password" | "microsoft" | "google";

interface AuthStatus {
  login_mode: LoginMode;
  sso_origin: "first_setup" | "migration" | null;
  sso_migration_active: boolean;
  migration_started_at: string | null;
  migration_completed_at: string | null;
  total?: number;
  migrated?: number;
  pending?: number;
  exempt?: number;
}

export function SsoMigrationPanel() {
  const [status, setStatus] = useState<AuthStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  
  const [selectedTab, setSelectedTab] = useState<LoginMode>("password");
  const [showTempDialog, setShowTempDialog] = useState(false);
  const [tempPasswords, setTempPasswords] = useState<any[]>([]);
  const [dialogTitle, setDialogTitle] = useState("");
  const [dialogMessage, setDialogMessage] = useState("");

  const fetchStatus = async () => {
    try {
      const res = await apiFetch(`${apiBase()}/admin/auth/login-mode`);
      if (res.ok) {
        const data = await res.json();
        setStatus(data);
        setSelectedTab(data.login_mode);
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchStatus();
  }, []);

  const handleModeChange = async (newMode: LoginMode) => {
    setError(null);
    setSaving(true);
    try {
      const res = await apiFetch(`${apiBase()}/admin/auth/login-mode`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: newMode }),
      });

      if (!res.ok) {
        let msg = "Errore durante il cambio modalità.";
        try {
          const j = await res.json();
          if (j.detail?.code) msg = `Errore: ${j.detail.code}`;
          else if (typeof j.detail === "string") msg = j.detail;
        } catch {}
        setError(msg);
        setSaving(false);
        return;
      }

      const data = await res.json();
      
      if (data.temp_passwords && data.temp_passwords.length > 0) {
        setTempPasswords(data.temp_passwords);
        setDialogTitle("Password Temporanee Generate");
        setDialogMessage(
          newMode === "password"
            ? "Hai disattivato il login SSO. I seguenti utenti non avevano una password e hanno ricevuto una password temporanea per poter accedere."
            : "Hai cambiato provider SSO durante una migrazione. I seguenti utenti necessitano di una password temporanea per ricollegare il loro account."
        );
        setShowTempDialog(true);
      }
      
      await fetchStatus();
    } catch (e) {
      console.error(e);
      setError("Errore di rete.");
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return <div className="p-8 text-center text-gray-500 animate-pulse">Caricamento stato...</div>;
  }

  if (!status) return null;

  return (
    <div className="space-y-6">
      {/* Mode Selector */}
      <div className="flex gap-4">
        {(["password", "microsoft", "google"] as LoginMode[]).map((m) => {
          const isActive = status.login_mode === m;
          const isSelected = selectedTab === m;
          
          return (
            <button
              key={m}
              disabled={saving}
              onClick={() => setSelectedTab(m)}
              className={`relative flex-1 flex flex-col items-center justify-center gap-2 p-4 rounded-xl border transition-all ${
                isSelected
                  ? "bg-blue-500/10 border-blue-500 text-white"
                  : "bg-[#070707] border-[#222] text-gray-400 hover:border-gray-500 hover:text-gray-200"
              } ${saving ? "opacity-50 cursor-not-allowed" : ""}`}
            >
              {isActive && (
                <div className="absolute top-2 right-2 w-2 h-2 rounded-full bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.8)]" title="Modalità attualmente attiva" />
              )}
              {m === "password" && <Key className={`w-6 h-6 ${isActive ? "text-emerald-400" : ""}`} />}
              {m === "microsoft" && (
                <svg className={`h-6 w-6 ${isActive ? "" : "opacity-80"}`} viewBox="0 0 21 21" fill="none"><path d="M0 0H10V10H0V0Z" fill="#f25022"/><path d="M11 0H21V10H11V0Z" fill="#7fba00"/><path d="M0 11H10V21H0V11Z" fill="#00a4ef"/><path d="M11 11H21V21H11V11Z" fill="#ffb900"/></svg>
              )}
              {m === "google" && (
                <svg className={`h-6 w-6 ${isActive ? "" : "opacity-80"}`} viewBox="0 0 48 48"><path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/><path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/><path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/><path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/></svg>
              )}
              <span className="font-semibold text-sm capitalize">{m === "password" ? "Normale" : m}</span>
              {isActive && <span className="text-[10px] text-emerald-500 font-bold uppercase mt-1">Attivo</span>}
            </button>
          );
        })}
      </div>

      {error && (
        <div className="p-3 rounded-xl bg-red-500/10 border border-red-500/20 text-red-400 flex items-start gap-3 text-sm">
          <AlertTriangle className="w-5 h-5 shrink-0 mt-0.5" />
          <div>{error}</div>
        </div>
      )}

      {/* Migration Tracker (shown only if the selected tab is the active SSO mode and migration is active) */}
      {selectedTab !== "password" && status.login_mode === selectedTab && status.sso_origin === "migration" && status.sso_migration_active && (
        <div className="p-6 rounded-xl border border-emerald-500/20 bg-emerald-500/5 space-y-4 animate-in fade-in slide-in-from-top-4">
          <div className="flex items-center justify-between">
            <h4 className="text-lg font-bold tracking-tight text-white flex items-center gap-2">
              <Users className="w-5 h-5 text-emerald-400" />
              Stato Migrazione Utenti
            </h4>
            {status.sso_migration_active ? (
              <span className="px-2 py-1 bg-yellow-500/20 text-yellow-500 text-[10px] font-bold uppercase rounded border border-yellow-500/30">
                In Corso
              </span>
            ) : (
              <span className="px-2 py-1 bg-green-500/20 text-green-500 text-[10px] font-bold uppercase rounded border border-green-500/30 flex items-center gap-1">
                <CheckCircle2 className="w-3 h-3" /> Completata
              </span>
            )}
          </div>
          
          <div className="grid grid-cols-4 gap-4">
            <div className="p-4 bg-black/40 rounded-lg text-center">
              <div className="text-2xl font-black text-white">{status.total || 0}</div>
              <div className="text-[10px] text-gray-500 uppercase font-bold tracking-wider">Totali (con pass)</div>
            </div>
            <div className="p-4 bg-black/40 rounded-lg text-center">
              <div className="text-2xl font-black text-green-400">{status.migrated || 0}</div>
              <div className="text-[10px] text-gray-500 uppercase font-bold tracking-wider">Migrati</div>
            </div>
            <div className="p-4 bg-black/40 rounded-lg text-center">
              <div className="text-2xl font-black text-yellow-400">{status.pending || 0}</div>
              <div className="text-[10px] text-gray-500 uppercase font-bold tracking-wider">In Attesa</div>
            </div>
            <div className="p-4 bg-black/40 rounded-lg text-center">
              <div className="text-2xl font-black text-gray-400">{status.exempt || 0}</div>
              <div className="text-[10px] text-gray-500 uppercase font-bold tracking-wider">Esonerati</div>
            </div>
          </div>

          <div className="flex justify-end pt-2">
            <button
              onClick={() => window.location.href = "/security/migration"}
              className="flex items-center gap-2 px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold rounded-lg transition-all"
            >
              Gestisci Utenti <ChevronRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}

      {/* Sso Config panel for the selected SSO provider */}
      {selectedTab !== "password" && (
        <div className="animate-in fade-in slide-in-from-top-4">
          <SsoConfigPanel
            forcedProvider={selectedTab as any}
            onValidationSuccess={() => handleModeChange(selectedTab)}
            isActive={status.login_mode === selectedTab}
          />
        </div>
      )}

      {/* Se siamo in password e non è attiva, mostriamo il tasto per attivarla */}
      {selectedTab === "password" && status.login_mode !== "password" && (
        <div className="p-6 rounded-xl border border-[#333] bg-[#0a0a0a] space-y-4 animate-in fade-in slide-in-from-top-4 text-center">
          <Key className="w-8 h-8 text-gray-400 mx-auto" />
          <h4 className="text-white font-bold">Autenticazione a Password</h4>
          <p className="text-sm text-gray-400 max-w-md mx-auto">
            Disattiva il Single Sign-On e torna all'accesso standard tramite password per tutti gli utenti.
          </p>
          <button
            onClick={() => handleModeChange("password")}
            className="mt-4 px-6 py-2 bg-white text-black font-bold rounded-lg hover:bg-gray-200 transition-colors"
          >
            Imposta come predefinita
          </button>
        </div>
      )}

      <TempPasswordsDialog
        isOpen={showTempDialog}
        onClose={() => { setShowTempDialog(false); setTempPasswords([]); }}
        passwords={tempPasswords}
        title={dialogTitle}
        message={dialogMessage}
      />
    </div>
  );
}
