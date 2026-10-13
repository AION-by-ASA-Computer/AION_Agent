"use client";

import { useCallback, useEffect, useState } from "react";
import { Key, Loader2, ShieldOff, UserCheck, UserX } from "lucide-react";
import { apiBase } from "@/lib/api";
import { apiFetch } from "@/lib/api/headers";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";
import { PageToast, type ToastState } from "@/components/PageToast";
import { Dialog } from "@/components/profiles/Dialog";
import { SearchField } from "@/components/ui/SearchField";
import { dangerBtn, ghostBtn, outlineBtn, solidBtn } from "@/components/ui/classes";
import { fullWhen, toMs } from "@/components/conversations/format";
import { TempPasswordsDialog } from "./TempPasswordsDialog";

const k = "admin_users.migration";
type Tab = "pending" | "no_access" | "migrated" | "exempt";
const TABS: Tab[] = ["pending", "no_access", "migrated", "exempt"];

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

type Confirm = { kind: "temp" | "unlink"; user: MigrationUser } | null;

const rowBtn = cn(outlineBtn, "h-8 px-2.5 text-[13px]");

export function MigrationUsers() {
  const t = useT();
  const [tab, setTab] = useState<Tab>("pending");
  const [q, setQ] = useState("");
  const [users, setUsers] = useState<MigrationUser[]>([]);
  const [total, setTotal] = useState(0);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [busyId, setBusyId] = useState<string | null>(null);
  const [toast, setToast] = useState<ToastState>(null);
  const [tempPasswords, setTempPasswords] = useState<any[]>([]);
  const [showTemp, setShowTemp] = useState(false);
  const [confirm, setConfirm] = useState<Confirm>(null);

  const load = useCallback(async () => {
    setState("loading");
    try {
      const res = await apiFetch(`${apiBase()}/admin/auth/sso-migration/users?status=${tab}&q=${encodeURIComponent(q)}&page_size=100`);
      if (!res.ok) throw new Error();
      const data = await res.json();
      setUsers(data.users || []);
      setTotal(data.total || 0);
      setState("ready");
    } catch {
      setState("error");
    }
  }, [tab, q]);

  useEffect(() => {
    const id = setTimeout(load, q ? 250 : 0);
    return () => clearTimeout(id);
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
        setToast({ message: code ? t(`${k}.failed_code`, { code }) : t(`${k}.failed`), variant: "error" });
        return;
      }
      setToast({ message: okMsg, variant: "success" });
      await load();
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
      exempt ? t(`${k}.did_exempt`) : t(`${k}.did_reinstate`),
    );

  const generateTemp = async (u: MigrationUser) => {
    setBusyId(u.id);
    try {
      const res = await apiFetch(`${apiBase()}/admin/auth/temp-passwords`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_ids: [u.id] }),
      });
      if (!res.ok) {
        setToast({ message: t(`${k}.temp_failed`), variant: "error" });
        return;
      }
      const data = await res.json();
      setTempPasswords(data.temp_passwords || []);
      setShowTemp(true);
      await load();
    } finally {
      setBusyId(null);
    }
  };

  const unlink = (u: MigrationUser) =>
    run(u.id, () => apiFetch(`${apiBase()}/admin/auth/users/${u.id}/sso-identities/${u.identity_id}`, { method: "DELETE" }), t(`${k}.did_unlink`));

  const accept = () => {
    const c = confirm;
    setConfirm(null);
    if (!c) return;
    if (c.kind === "temp") generateTemp(c.user);
    else unlink(c.user);
  };

  const name = (u: MigrationUser) => u.display_name || u.identifier;

  return (
    <div className="flex flex-col gap-6">
      <div role="tablist" aria-label={t(`${k}.tabs_aria`)} className="no-scrollbar flex gap-1 overflow-x-auto border-b border-border/60">
        {TABS.map((id) => {
          const active = tab === id;
          return (
            <button
              key={id}
              type="button"
              role="tab"
              id={`mig-tab-${id}`}
              aria-selected={active}
              aria-controls="mig-panel"
              onClick={() => setTab(id)}
              className={cn(
                "focus-ring relative inline-flex h-11 shrink-0 items-center px-3 text-sm font-medium transition-colors",
                active ? "text-foreground" : "text-muted-foreground hover:text-foreground",
              )}
            >
              {t(`${k}.tab_${id}`)}
              <span aria-hidden className={cn("absolute inset-x-3 bottom-0 h-0.5 rounded-full bg-foreground transition-opacity", active ? "opacity-100" : "opacity-0")} />
            </button>
          );
        })}
      </div>

      <div id="mig-panel" role="tabpanel" aria-labelledby={`mig-tab-${tab}`} className="flex flex-col gap-4">
        <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
          <div className="min-w-[14rem] flex-1 sm:max-w-sm">
            <SearchField value={q} onChange={setQ} placeholder={t(`${k}.search`)} />
          </div>
          <p className="min-w-0 flex-1 text-sm text-muted-foreground">{t(`${k}.hint_${tab}`)}</p>
        </div>

        {state === "loading" && users.length === 0 ? (
          <div className="flex items-center gap-2 px-1 py-10 text-sm text-muted-foreground" role="status">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
            {t(`${k}.loading`)}
          </div>
        ) : state === "error" ? (
          <div className="flex flex-col items-start gap-3 px-1 py-10">
            <p className="text-sm text-destructive">{t(`${k}.load_error`)}</p>
            <button type="button" className={outlineBtn} onClick={load}>
              {t(`${k}.retry`)}
            </button>
          </div>
        ) : users.length === 0 ? (
          <div className="rounded-3xl border border-dashed border-border px-6 py-16 text-center text-sm text-muted-foreground">{t(`${k}.empty`)}</div>
        ) : (
          <ul className={cn("overflow-hidden rounded-3xl border border-border/70 bg-card transition-opacity", state === "loading" && "opacity-60")} aria-busy={state === "loading"}>
            {users.map((u) => {
              const busy = busyId === u.id;
              return (
                <li key={u.id} className="flex flex-col gap-3 border-b border-border/40 px-5 py-3.5 last:border-b-0 sm:flex-row sm:items-center sm:gap-4">
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium">{name(u)}</div>
                    <div className="truncate text-xs text-muted-foreground">
                      {u.identifier}
                      {u.email ? ` · ${u.email}` : ""}
                      {u.sso_email ? ` · SSO: ${u.sso_email}` : ""}
                    </div>
                    {tab === "pending" && u.has_temp_password && (
                      <div className="mt-1 text-xs font-medium text-warning">
                        {u.temp_password_expires_at
                          ? t(`${k}.temp_until`, { when: fullWhen(toMs(u.temp_password_expires_at)) })
                          : t(`${k}.temp_active`)}
                      </div>
                    )}
                  </div>

                  <div className="flex shrink-0 flex-wrap items-center gap-1.5">
                    {busy && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" aria-hidden />}
                    {(tab === "pending" || tab === "no_access") && (
                      <>
                        <button type="button" className={rowBtn} disabled={busy} onClick={() => setConfirm({ kind: "temp", user: u })}>
                          <Key className="h-3.5 w-3.5" aria-hidden />
                          {t(`${k}.act_temp`)}
                        </button>
                        <button type="button" className={rowBtn} disabled={busy} onClick={() => setExempt(u, true)}>
                          <UserX className="h-3.5 w-3.5" aria-hidden />
                          {t(`${k}.act_exempt`)}
                        </button>
                      </>
                    )}
                    {tab === "migrated" && (
                      <button type="button" className={cn(rowBtn, "text-destructive")} disabled={busy || !u.identity_id} onClick={() => setConfirm({ kind: "unlink", user: u })}>
                        <ShieldOff className="h-3.5 w-3.5" aria-hidden />
                        {t(`${k}.act_unlink`)}
                      </button>
                    )}
                    {tab === "exempt" && (
                      <button type="button" className={rowBtn} disabled={busy} onClick={() => setExempt(u, false)}>
                        <UserCheck className="h-3.5 w-3.5" aria-hidden />
                        {t(`${k}.act_reinstate`)}
                      </button>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        )}

        {state !== "error" && total > users.length && <p className="px-1 text-xs text-muted-foreground">{t(`${k}.shown`, { shown: users.length, total })}</p>}
      </div>

      {confirm && (
        <Dialog
          title={confirm.kind === "temp" ? t(`${k}.confirm_temp_title`) : t(`${k}.confirm_unlink_title`)}
          closeLabel={t(`${k}.cancel`)}
          onClose={() => setConfirm(null)}
        >
          <div className="flex flex-col gap-5">
            <p className="text-sm text-muted-foreground">
              {t(confirm.kind === "temp" ? `${k}.confirm_temp_body` : `${k}.confirm_unlink_body`, { name: name(confirm.user) })}
            </p>
            <div className="flex justify-end gap-2">
              <button type="button" className={ghostBtn} onClick={() => setConfirm(null)}>
                {t(`${k}.cancel`)}
              </button>
              <button type="button" className={confirm.kind === "unlink" ? dangerBtn : solidBtn} autoFocus onClick={accept}>
                {confirm.kind === "temp" ? t(`${k}.confirm_temp`) : t(`${k}.confirm_unlink`)}
              </button>
            </div>
          </div>
        </Dialog>
      )}

      <TempPasswordsDialog
        isOpen={showTemp}
        onClose={() => {
          setShowTemp(false);
          setTempPasswords([]);
        }}
        passwords={tempPasswords}
        title={t(`${k}.temp_dialog_title`)}
        message={t(`${k}.temp_dialog_message`)}
      />
      <PageToast toast={toast} onDismiss={() => setToast(null)} />
    </div>
  );
}
