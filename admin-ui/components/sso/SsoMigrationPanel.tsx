"use client";

import { useEffect, useState } from "react";
import { apiBase } from "@/lib/api";
import { apiFetch } from "@/lib/api/headers";
import { AlertTriangle, CheckCircle2, ChevronRight, Key, Loader2 } from "lucide-react";
import { cn } from "@/lib/cn";
import { Dialog } from "@/components/profiles/Dialog";
import { ghostBtn, outlineBtn, solidBtn } from "@/components/ui/classes";
import { TempPasswordsDialog } from "./TempPasswordsDialog";
import { SsoConfigPanel } from "./SsoConfigPanel";

type LoginMode = "password" | "microsoft" | "google";

const MODE_ERRORS: Record<string, string> = {
  sso_revalidation_required:
    "La verifica del provider è scaduta (oltre 30 minuti). Premi «Reimposta» e verifica di nuovo con il tuo account.",
  sso_admin_not_linked:
    "Il tuo account amministratore non è collegato a questo provider. Esegui «Salva e verifica con il mio account».",
  migration_in_progress:
    "C'è una migrazione in corso sul provider attuale: attendi che gli utenti si colleghino (o esonerali) prima di cambiare provider.",
  provider_not_configured: "Configura e verifica il provider prima di attivarlo.",
};

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

export function SsoMigrationPanel({ onManage }: { onManage?: () => void } = {}) {
  const [status, setStatus] = useState<AuthStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  
  const [selectedTab, setSelectedTab] = useState<LoginMode>("password");
  const [showTempDialog, setShowTempDialog] = useState(false);
  const [tempPasswords, setTempPasswords] = useState<any[]>([]);
  const [dialogTitle, setDialogTitle] = useState("");
  const [dialogMessage, setDialogMessage] = useState("");

  const [showConfirmDialog, setShowConfirmDialog] = useState(false);
  const [showEnableSsoDialog, setShowEnableSsoDialog] = useState(false);
  const [affectedUsers, setAffectedUsers] = useState<any[]>([]);
  const [pendingModeChange, setPendingModeChange] = useState<LoginMode | null>(null);
  const [loadingSimulation, setLoadingSimulation] = useState(false);

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

  const handleModeChangeRequest = async (newMode: LoginMode) => {
    if (status?.login_mode === "password" && newMode !== "password") {
      setPendingModeChange(newMode);
      setShowEnableSsoDialog(true);
      return;
    }
    await proceedWithModeChange(newMode);
  };

  const proceedWithModeChange = async (newMode: LoginMode) => {
    if (status?.login_mode && status.login_mode !== "password" && status.login_mode !== newMode) {
      setLoadingSimulation(true);
      setError(null);
      try {
        const res = await apiFetch(`${apiBase()}/admin/auth/login-mode/simulate?mode=${newMode}`);
        if (res.ok) {
          const data = await res.json();
          if (data.affected_users && data.affected_users.length > 0) {
            setAffectedUsers(data.affected_users);
            setPendingModeChange(newMode);
            setShowConfirmDialog(true);
            setLoadingSimulation(false);
            return; // Wait for user confirmation
          }
        }
      } catch (e) {
        console.error("Simulation error", e);
      }
      setLoadingSimulation(false);
    }
    
    await handleModeChange(newMode);
  };

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
          if (j.detail?.code) msg = MODE_ERRORS[j.detail.code] ?? `Errore: ${j.detail.code}`;
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
    return (
      <div className="flex items-center gap-2 px-1 py-6 text-sm text-muted-foreground" role="status">
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
        Caricamento stato…
      </div>
    );
  }

  if (!status) return null;

  const stats: { label: string; value: number; tone?: string }[] = [
    { label: "Totali", value: status.total || 0 },
    { label: "Migrati", value: status.migrated || 0, tone: "text-success" },
    { label: "In attesa", value: status.pending || 0, tone: "text-warning" },
    { label: "Esonerati", value: status.exempt || 0, tone: "text-muted-foreground" },
  ];

  return (
    <div className="flex flex-col gap-5">
      <div role="group" aria-label="Modalità di accesso" className="grid gap-2 sm:grid-cols-3">
        {(["password", "microsoft", "google"] as LoginMode[]).map((m) => {
          const isActive = status.login_mode === m;
          const isSelected = selectedTab === m;
          return (
            <button
              key={m}
              type="button"
              disabled={saving}
              aria-pressed={isSelected}
              onClick={() => setSelectedTab(m)}
              className={cn(
                "focus-ring flex items-center gap-3 rounded-2xl border px-4 py-3.5 text-left transition-colors disabled:opacity-50",
                isSelected ? "border-foreground/40 bg-secondary" : "border-border/70 bg-card hover:bg-secondary/60",
              )}
            >
              {m === "password" && <Key className="h-5 w-5 shrink-0 text-muted-foreground" aria-hidden />}
              {m === "microsoft" && (
                <svg className="h-5 w-5 shrink-0" viewBox="0 0 21 21" fill="none" aria-hidden><path d="M0 0H10V10H0V0Z" fill="#f25022"/><path d="M11 0H21V10H11V0Z" fill="#7fba00"/><path d="M0 11H10V21H0V11Z" fill="#00a4ef"/><path d="M11 11H21V21H11V11Z" fill="#ffb900"/></svg>
              )}
              {m === "google" && (
                <svg className="h-5 w-5 shrink-0" viewBox="0 0 48 48" aria-hidden><path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/><path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/><path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/><path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/></svg>
              )}
              <span className="min-w-0 flex-1 text-sm font-medium capitalize">{m === "password" ? "Password" : m}</span>
              {isActive && (
                <span className="inline-flex shrink-0 items-center gap-1.5 text-xs font-medium text-success">
                  <span className="h-1.5 w-1.5 rounded-full bg-success" aria-hidden />
                  Attivo
                </span>
              )}
            </button>
          );
        })}
      </div>

      {error && (
        <div className="flex items-start gap-3 rounded-2xl bg-destructive/10 px-4 py-3 text-sm text-destructive" role="alert">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
          <div>{error}</div>
        </div>
      )}

      {selectedTab !== "password" && status.login_mode === selectedTab && (
        <div className="rounded-2xl border border-border/70 bg-card p-5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-sm font-semibold">Stato migrazione utenti</h3>
            {status.sso_origin !== "migration" ? (
              <span className="rounded-full bg-secondary px-2.5 py-0.5 text-xs font-medium text-muted-foreground">Setup iniziale</span>
            ) : status.sso_migration_active ? (
              <span className="rounded-full bg-warning/15 px-2.5 py-0.5 text-xs font-medium text-warning">In corso</span>
            ) : (
              <span className="inline-flex items-center gap-1 rounded-full bg-success/15 px-2.5 py-0.5 text-xs font-medium text-success">
                <CheckCircle2 className="h-3 w-3" aria-hidden /> Completata
              </span>
            )}
          </div>

          <dl className="mt-4 grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-4">
            {stats.map((x) => (
              <div key={x.label}>
                <dd className={cn("order-2 text-xl font-semibold tabular-nums", x.tone)}>{x.value}</dd>
                <dt className="text-xs text-muted-foreground">{x.label}</dt>
              </div>
            ))}
          </dl>

          <div className="mt-5 flex justify-end">
            <button type="button" onClick={onManage} className={outlineBtn}>
              Gestisci utenti <ChevronRight className="h-4 w-4" aria-hidden />
            </button>
          </div>
        </div>
      )}

      {selectedTab !== "password" && (
        <SsoConfigPanel
          forcedProvider={selectedTab as any}
          onActivate={() => handleModeChangeRequest(selectedTab)}
          isActive={status.login_mode === selectedTab}
        />
      )}

      {selectedTab === "password" && status.login_mode !== "password" && (
        <div className="rounded-2xl border border-border/70 bg-card p-6">
          <h3 className="text-sm font-semibold">Autenticazione a password</h3>
          <p className="mt-1 max-w-[56ch] text-sm text-muted-foreground">
            Disattiva il Single Sign-On e torna all'accesso standard tramite password per tutti gli utenti.
          </p>
          <button type="button" onClick={() => handleModeChangeRequest("password")} disabled={loadingSimulation} className={cn(solidBtn, "mt-4")}>
            {loadingSimulation && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />}
            {loadingSimulation ? "Verifica in corso…" : "Imposta come predefinita"}
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

      {showConfirmDialog && pendingModeChange && (
        <Dialog
          title="Conferma cambio metodo di accesso"
          closeLabel="Annulla"
          className="max-w-xl"
          onClose={() => {
            setShowConfirmDialog(false);
            setPendingModeChange(null);
          }}
        >
          <div className="flex flex-col gap-4">
            <p className="text-sm text-muted-foreground">
              Stai per cambiare il metodo di accesso in uso. I seguenti {affectedUsers.length} utenti non hanno una password. Ne verrà generata una temporanea per ciascuno, mostrata una sola volta: comunicala in modo sicuro.
            </p>
            <ul className="-mx-1 flex max-h-64 flex-col overflow-y-auto px-1">
              {affectedUsers.map((u, i) => (
                <li key={i} className="border-b border-border/40 py-2.5 last:border-b-0">
                  <div className="text-sm font-medium">{u.identifier}</div>
                  {u.email && <div className="text-xs text-muted-foreground">{u.email}</div>}
                </li>
              ))}
            </ul>
            <div className="flex justify-end gap-2">
              <button
                type="button"
                className={ghostBtn}
                disabled={saving}
                onClick={() => {
                  setShowConfirmDialog(false);
                  setPendingModeChange(null);
                }}
              >
                Annulla
              </button>
              <button
                type="button"
                className={solidBtn}
                disabled={saving}
                onClick={async () => {
                  setShowConfirmDialog(false);
                  await handleModeChange(pendingModeChange);
                  setPendingModeChange(null);
                }}
              >
                {saving && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />}
                Conferma e genera password
              </button>
            </div>
          </div>
        </Dialog>
      )}

      {showEnableSsoDialog && pendingModeChange && (
        <Dialog
          title="Attivare il Single Sign-On?"
          closeLabel="Annulla"
          onClose={() => {
            setShowEnableSsoDialog(false);
            setPendingModeChange(null);
          }}
        >
          <div className="flex flex-col gap-5">
            <p className="text-sm text-muted-foreground">
              Gli utenti esistenti potranno accedere con la password solo per collegare il proprio account aziendale al primo accesso; poi entreranno solo via SSO. Il tuo account admin conserva la password come accesso di emergenza.
            </p>
            <div className="flex justify-end gap-2">
              <button
                type="button"
                className={ghostBtn}
                disabled={saving || loadingSimulation}
                onClick={() => {
                  setShowEnableSsoDialog(false);
                  setPendingModeChange(null);
                }}
              >
                Annulla
              </button>
              <button
                type="button"
                className={solidBtn}
                disabled={saving || loadingSimulation}
                onClick={async () => {
                  setShowEnableSsoDialog(false);
                  const mode = pendingModeChange;
                  setPendingModeChange(null);
                  await proceedWithModeChange(mode);
                }}
              >
                {(saving || loadingSimulation) && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />}
                Attiva SSO
              </button>
            </div>
          </div>
        </Dialog>
      )}
    </div>
  );
}
