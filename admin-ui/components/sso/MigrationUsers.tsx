"use client";

import { useCallback, useEffect, useState } from "react";
import { Loader2, Mail, RectangleEllipsis, ShieldOff, UserCheck, UserX } from "lucide-react";
import { apiBase } from "@/lib/api";
import { apiFetch } from "@/lib/api/headers";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";
import { PageToast, type ToastState } from "@/components/PageToast";
import { Dialog } from "@/components/profiles/Dialog";
import { SearchField } from "@/components/ui/SearchField";
import { dangerBtn, ghostBtn, outlineBtn, solidBtn } from "@/components/ui/classes";
import { fullWhen, toMs } from "@/lib/datetime";
import { linkErrorText, setupLinksToast, type SetupLinks } from "./setupLinks";
import { TempPasswordsDialog, type TempPassword } from "./TempPasswordsDialog";

const k = "admin_users.migration";
type Tab = "pending" | "no_access" | "migrated" | "exempt";
const TABS: Tab[] = ["pending", "no_access", "migrated", "exempt"];

interface MigrationUser {
  id: string;
  identifier: string;
  email: string | null;
  display_name: string | null;
  sso_migration_exempt: boolean;
  has_password?: boolean;
  setup_link_pending?: boolean;
  setup_link_expires_at?: string | null;
  setup_link_send_error?: string | null;
  identity_id?: string;
  sso_email?: string;
  linked_at?: string;
}

type Confirm = { kind: "link" | "unlink"; user: MigrationUser } | null;

const rowBtn = cn(outlineBtn, "h-8 px-2.5 text-[13px]");

/** ``onChanged``: lo stato di migrazione di qualche utente e' cambiato (aggiorna la lista utenti). */
export function MigrationUsers({ onChanged }: { onChanged?: () => void } = {}) {
  const t = useT();
  const [tab, setTab] = useState<Tab>("pending");
  const [q, setQ] = useState("");
  const [users, setUsers] = useState<MigrationUser[]>([]);
  const [total, setTotal] = useState(0);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [busyId, setBusyId] = useState<string | null>(null);
  const [toast, setToast] = useState<ToastState>(null);
  const [confirm, setConfirm] = useState<Confirm>(null);
  // Senza SMTP il backend genera password temporanee invece dei link: mostrate una sola volta.
  const [smtpMissing, setSmtpMissing] = useState(false);
  const [tempPasswords, setTempPasswords] = useState<TempPassword[] | null>(null);

  useEffect(() => {
    apiFetch(`${apiBase()}/admin/smtp`)
      .then((res) => (res.ok ? res.json() : Promise.reject(res)))
      .then((data) => setSmtpMissing(!data.configured))
      .catch(() => {});
  }, []);

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
      onChanged?.();
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

  // Il link arriva solo all'utente: qui si vede l'esito dell'invio, mai il link.
  const sendLink = async (u: MigrationUser) => {
    setBusyId(u.id);
    try {
      const res = await apiFetch(`${apiBase()}/admin/auth/setup-links`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_ids: [u.id] }),
      });
      if (!res.ok) {
        let code = "";
        try {
          code = (await res.json())?.detail?.code || "";
        } catch {}
        setToast({ message: code ? linkErrorText(t, code) : t(`${k}.link_failed`), variant: "error" });
        return;
      }
      const data = (await res.json()) as { setup_links?: SetupLinks; temp_passwords?: TempPassword[] };
      if (data.temp_passwords?.length) {
        setSmtpMissing(true);
        setTempPasswords(data.temp_passwords);
      } else setToast(setupLinksToast(t, data.setup_links));
      await load();
      onChanged?.();
    } catch {
      setToast({ message: t(`${k}.network_error`), variant: "error" });
    } finally {
      setBusyId(null);
    }
  };

  // Senza password il backend invia all'utente il link per impostarla: rientra
  // con quella e ricollega l'account aziendale (flusso standard di migrazione).
  const unlink = async (u: MigrationUser) => {
    setBusyId(u.id);
    try {
      const res = await apiFetch(`${apiBase()}/admin/auth/users/${u.id}/sso-identities/${u.identity_id}`, { method: "DELETE" });
      if (!res.ok) {
        setToast({ message: t(`${k}.failed`), variant: "error" });
        return;
      }
      const data = await res.json().catch(() => ({}));
      if (data.setup_link_error) {
        setToast({ message: t(`${k}.did_unlink_no_link`, { error: linkErrorText(t, data.setup_link_error) }), variant: "warning" });
      } else if (data.temp_passwords?.length) {
        setTempPasswords(data.temp_passwords);
      } else if (data.setup_links) {
        setToast(setupLinksToast(t, data.setup_links));
      } else {
        setToast({ message: t(`${k}.did_unlink`), variant: "success" });
      }
      await load();
      onChanged?.();
    } catch {
      setToast({ message: t(`${k}.network_error`), variant: "error" });
    } finally {
      setBusyId(null);
    }
  };

  const accept = () => {
    const c = confirm;
    setConfirm(null);
    if (!c) return;
    if (c.kind === "link") sendLink(c.user);
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
                    {tab === "pending" && u.setup_link_pending && (
                      <div className={cn("mt-1 text-xs font-medium", u.setup_link_send_error ? "text-destructive" : "text-warning")}>
                        {u.setup_link_send_error
                          ? t(`${k}.link_send_error`, { error: linkErrorText(t, u.setup_link_send_error) })
                          : u.setup_link_expires_at
                            ? t(`${k}.link_until`, { when: fullWhen(toMs(u.setup_link_expires_at)) })
                            : t(`${k}.link_active`)}
                      </div>
                    )}
                  </div>

                  <div className="flex shrink-0 flex-wrap items-center gap-1.5">
                    {busy && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" aria-hidden />}
                    {(tab === "pending" || tab === "no_access") && (
                      <>
                        <button
                          type="button"
                          className={rowBtn}
                          disabled={busy || (!smtpMissing && !u.email)}
                          title={smtpMissing || u.email ? undefined : t(`${k}.link_needs_email`)}
                          onClick={() => setConfirm({ kind: "link", user: u })}
                        >
                          {smtpMissing ? <RectangleEllipsis className="h-3.5 w-3.5" aria-hidden /> : <Mail className="h-3.5 w-3.5" aria-hidden />}
                          {t(smtpMissing ? `${k}.act_temp` : u.setup_link_pending ? `${k}.act_link_resend` : `${k}.act_link`)}
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
          title={confirm.kind === "link" ? t(`${k}.${smtpMissing ? "confirm_temp_title" : "confirm_link_title"}`) : t(`${k}.confirm_unlink_title`)}
          closeLabel={t(`${k}.cancel`)}
          onClose={() => setConfirm(null)}
        >
          <div className="flex flex-col gap-5">
            <p className="text-sm text-muted-foreground">
              {t(`${k}.${confirm.kind === "link" ? "confirm_link_body" : "confirm_unlink_body"}${smtpMissing ? "_temp" : ""}`, {
                name: name(confirm.user),
                email: confirm.user.email || "",
              })}
            </p>
            <div className="flex justify-end gap-2">
              <button type="button" className={ghostBtn} onClick={() => setConfirm(null)}>
                {t(`${k}.cancel`)}
              </button>
              <button type="button" className={confirm.kind === "unlink" ? dangerBtn : solidBtn} autoFocus onClick={accept}>
                {confirm.kind === "link" ? t(`${k}.${smtpMissing ? "confirm_temp" : "confirm_link"}`) : t(`${k}.confirm_unlink`)}
              </button>
            </div>
          </div>
        </Dialog>
      )}

      {tempPasswords && <TempPasswordsDialog passwords={tempPasswords} t={t} onClose={() => setTempPasswords(null)} />}

      <PageToast toast={toast} onDismiss={() => setToast(null)} />
    </div>
  );
}
