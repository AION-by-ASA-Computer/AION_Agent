"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft, Key, Loader2, Search, ShieldOff, UserCheck, UserX } from "lucide-react";
import { apiBase } from "@/lib/api";
import { apiFetch } from "@/lib/api/headers";
import { PageToast, ToastState } from "@/components/PageToast";
import { TempPasswordsDialog } from "@/components/sso/TempPasswordsDialog";

type Tab = "pending" | "migrated" | "exempt" | "no_access";

interface MigrationUser {
  id: string;
  identifier: string;
  email: string | null;
  display_name: string | null;
  sso_migration_exempt: boolean;
  has_temp_password?: boolean;
  temp_password_expires_at?: string | null;
  identity_id?: string;
  sso_email?: string;
  linked_at?: string;
}

const TABS: { id: Tab; label: string; hint: string }[] = [
  { id: "pending", label: "In attesa", hint: "Hanno ancora la password e non hanno collegato l'account SSO." },
  { id: "no_access", label: "Senza accesso", hint: "Nessuna password e nessun collegamento SSO: non possono entrare." },
  { id: "migrated", label: "Migrati", hint: "Hanno collegato l'account SSO." },
  { id: "exempt", label: "Esonerati", hint: "Esclusi dalla migrazione (es. account di servizio)." },
];

export default function SsoMigrationUsersPage() {
  const router = useRouter();
  const [tab, setTab] = useState<Tab>("pending");
  const [q, setQ] = useState("");
  const [users, setUsers] = useState<MigrationUser[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [toast, setToast] = useState<ToastState>(null);
  const [tempPasswords, setTempPasswords] = useState<any[]>([]);
  const [showTemp, setShowTemp] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await apiFetch(
        `${apiBase()}/admin/auth/sso-migration/users?status=${tab}&q=${encodeURIComponent(q)}&page_size=100`
      );
      if (res.ok) {
        const data = await res.json();
        setUsers(data.users || []);
        setTotal(data.total || 0);
      } else {
        setToast({ message: "Impossibile caricare gli utenti.", variant: "error" });
      }
    } catch {
      setToast({ message: "Errore di rete.", variant: "error" });
    } finally {
      setLoading(false);
    }
  }, [tab, q]);

  useEffect(() => {
    const t = setTimeout(load, q ? 250 : 0);
    return () => clearTimeout(t);
  }, [load, q]);

  async function run(userId: string, action: () => Promise<Response>, okMsg: string) {
    setBusyId(userId);
    try {
      const res = await action();
      if (!res.ok) {
        let code = "";
        try {
          code = (await res.json())?.detail?.code || "";
        } catch {}
        setToast({ message: `Operazione non riuscita${code ? ` (${code})` : ""}.`, variant: "error" });
        return null;
      }
      setToast({ message: okMsg, variant: "success" });
      await load();
      return res;
    } finally {
      setBusyId(null);
    }
  }

  const setExempt = (u: MigrationUser, exempt: boolean) =>
    run(
      u.id,
      () =>
        apiFetch(`${apiBase()}/admin/auth/sso-migration/users/${u.id}/exempt`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ exempt }),
        }),
      exempt ? "Utente esonerato." : "Utente reintegrato nella migrazione."
    );

  async function tempPassword(u: MigrationUser) {
    if (!window.confirm(`Generare una nuova password temporanea per ${u.identifier}? La precedente non sarà più valida.`)) return;
    setBusyId(u.id);
    try {
      const res = await apiFetch(`${apiBase()}/admin/auth/temp-passwords`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_ids: [u.id] }),
      });
      if (!res.ok) {
        setToast({ message: "Generazione password non riuscita.", variant: "error" });
        return;
      }
      const data = await res.json();
      setTempPasswords(data.temp_passwords || []);
      setShowTemp(true);
      await load();
    } finally {
      setBusyId(null);
    }
  }

  const unlink = (u: MigrationUser) => {
    if (!u.identity_id) return;
    if (
      !window.confirm(
        `Scollegare l'account SSO di ${u.identifier}? Se non ha una password non potrà più accedere finché non gli generi una password temporanea.`
      )
    )
      return;
    return run(
      u.id,
      () => apiFetch(`${apiBase()}/admin/auth/users/${u.id}/sso-identities/${u.identity_id}`, { method: "DELETE" }),
      "Account SSO scollegato."
    );
  };

  const current = TABS.find((t) => t.id === tab)!;

  return (
    <div className="space-y-6 p-6 max-w-5xl mx-auto">
      <button
        onClick={() => router.push("/settings")}
        className="flex items-center gap-2 text-xs text-gray-400 hover:text-white transition-colors"
      >
        <ArrowLeft className="w-4 h-4" /> Torna alle impostazioni
      </button>

      <div>
        <h1 className="text-2xl font-bold text-white">Migrazione utenti SSO</h1>
        <p className="text-sm text-gray-400">Gestisci chi ha già collegato l&apos;account aziendale e chi no.</p>
      </div>

      <div className="flex flex-wrap gap-2">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`px-4 py-2 rounded-lg text-sm font-semibold border transition-all ${
              tab === t.id
                ? "bg-blue-500/10 border-blue-500 text-white"
                : "bg-[#070707] border-[#222] text-gray-400 hover:border-gray-500"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      <p className="text-xs text-gray-500">{current.hint}</p>

      <div className="relative">
        <Search className="w-4 h-4 text-gray-500 absolute left-3 top-1/2 -translate-y-1/2" />
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Cerca per username o email"
          className="w-full bg-black border border-[#333] rounded-xl pl-9 pr-4 py-2.5 text-sm text-gray-200 outline-none focus:border-blue-500/50"
        />
      </div>

      <div className="rounded-xl border border-[#222] bg-[#070707] divide-y divide-[#1a1a1a]">
        {loading ? (
          <div className="p-6 text-sm text-gray-500 flex items-center gap-2">
            <Loader2 className="w-4 h-4 animate-spin" /> Caricamento…
          </div>
        ) : users.length === 0 ? (
          <div className="p-6 text-sm text-gray-500">Nessun utente in questa lista.</div>
        ) : (
          users.map((u) => (
            <div key={u.id} className="flex items-center justify-between gap-4 p-4">
              <div className="min-w-0">
                <div className="text-sm font-medium text-white truncate">{u.display_name || u.identifier}</div>
                <div className="text-xs text-gray-500 truncate">
                  {u.identifier}
                  {u.email ? ` · ${u.email}` : ""}
                  {u.sso_email ? ` · SSO: ${u.sso_email}` : ""}
                </div>
                {tab === "pending" && u.has_temp_password && (
                  <div className="text-[11px] text-yellow-500 mt-1">
                    Password temporanea attiva
                    {u.temp_password_expires_at ? ` fino al ${new Date(u.temp_password_expires_at).toLocaleString()}` : ""}
                  </div>
                )}
              </div>

              <div className="flex items-center gap-2 shrink-0">
                {busyId === u.id && <Loader2 className="w-4 h-4 animate-spin text-gray-400" />}
                {(tab === "pending" || tab === "no_access") && (
                  <>
                    <button
                      disabled={busyId === u.id}
                      onClick={() => tempPassword(u)}
                      className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-[#1a1a1a] text-gray-200 hover:bg-[#262626] disabled:opacity-50"
                    >
                      <Key className="w-3.5 h-3.5" /> Password temporanea
                    </button>
                    <button
                      disabled={busyId === u.id}
                      onClick={() => setExempt(u, true)}
                      className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-[#1a1a1a] text-gray-200 hover:bg-[#262626] disabled:opacity-50"
                    >
                      <UserX className="w-3.5 h-3.5" /> Esonera
                    </button>
                  </>
                )}
                {tab === "migrated" && (
                  <button
                    disabled={busyId === u.id || !u.identity_id}
                    onClick={() => unlink(u)}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-red-500/10 text-red-300 hover:bg-red-500/20 disabled:opacity-50"
                  >
                    <ShieldOff className="w-3.5 h-3.5" /> Scollega
                  </button>
                )}
                {tab === "exempt" && (
                  <button
                    disabled={busyId === u.id}
                    onClick={() => setExempt(u, false)}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-emerald-500/10 text-emerald-300 hover:bg-emerald-500/20 disabled:opacity-50"
                  >
                    <UserCheck className="w-3.5 h-3.5" /> Reintegra
                  </button>
                )}
              </div>
            </div>
          ))
        )}
      </div>
      {!loading && total > users.length && (
        <p className="text-xs text-gray-500">Mostrati {users.length} di {total}: restringi la ricerca.</p>
      )}

      <TempPasswordsDialog
        isOpen={showTemp}
        onClose={() => {
          setShowTemp(false);
          setTempPasswords([]);
        }}
        passwords={tempPasswords}
        title="Password temporanea generata"
        message="Comunica la password all'utente in modo sicuro: è mostrata una sola volta e scade automaticamente."
      />
      <PageToast toast={toast} onDismiss={() => setToast(null)} />
    </div>
  );
}
