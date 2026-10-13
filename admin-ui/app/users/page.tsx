"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { KeyRound, Loader2, Pencil, Plus, ShieldCheck, Trash2, TriangleAlert, UserCog } from "lucide-react";
import { apiBase } from "@/lib/api";
import { apiFetch } from "@/lib/api/headers";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";
import { getLocale } from "@/lib/i18n/i18n-store";
import { PageToast, type ToastState } from "@/components/PageToast";
import { Dialog } from "@/components/profiles/Dialog";
import { dangerBtn, ghostBtn, inputCls, outlineBtn, solidBtn } from "@/components/ui/classes";
import { SearchField } from "@/components/ui/SearchField";
import { ColumnFilter, type ColumnFilterLabels } from "@/components/ui/ColumnFilter";
import { DeleteDialog } from "@/components/ui/ConfirmDialogs";
import { SsoMigrationPanel } from "@/components/sso/SsoMigrationPanel";
import { MigrationUsers } from "@/components/sso/MigrationUsers";
import { TwoFactorPanel } from "@/components/sso/TwoFactorPanel";

const k = "admin_users";
const GRIDS: Record<string, string> = {
  "00": "md:grid-cols-[minmax(0,2fr)_minmax(0,1.6fr)_minmax(0,1.2fr)_10.5rem]",
  "01": "md:grid-cols-[minmax(0,2fr)_minmax(0,1.6fr)_minmax(0,1.2fr)_6.5rem_10.5rem]",
  "10": "md:grid-cols-[minmax(0,2fr)_minmax(0,1.6fr)_minmax(0,1.2fr)_7.5rem_10.5rem]",
  "11": "md:grid-cols-[minmax(0,2fr)_minmax(0,1.6fr)_minmax(0,1.2fr)_7.5rem_6.5rem_10.5rem]",
};

type Filters = { user: string; email: string; access: string; migration: string; twofa: string };
const NO_FILTERS: Filters = { user: "", email: "", access: "", migration: "", twofa: "" };
const METHODS = ["password", "microsoft", "google"] as const;

type Tab = "accounts" | "signin";
type ListState = "loading" | "ready" | "error";

interface UserRow {
  id: string;
  identifier: string;
  display_name?: string | null;
  email?: string | null;
  tenant_id?: string | null;
  totp_enabled?: boolean;
  has_password?: boolean;
  login_method?: string | null;
  sso_providers?: string[];
  sso_migration_exempt?: boolean;
  migration_pending?: boolean;
}

/** The single method the account signs in with right now (computed by the backend; stale identities from previous providers are ignored). */
const methodsOf = (u: UserRow) => (u.login_method ? [u.login_method] : []);

type MigrationState = "pending" | "exempt" | "migrated" | "";
const migrationOf = (u: UserRow): MigrationState =>
  u.migration_pending ? "pending" : u.sso_migration_exempt ? "exempt" : u.login_method && u.login_method !== "password" ? "migrated" : "";

interface ProfileRow {
  slug: string;
  name: string;
  description?: string;
}

type T = (key: string, vars?: Record<string, string | number>) => string;

const nameOf = (u: UserRow) => u.display_name || u.identifier;

async function errorDetail(res: Response, fallback: string) {
  try {
    const data = await res.json();
    return typeof data?.detail === "string" ? data.detail : fallback;
  } catch {
    return fallback;
  }
}

function Avatar({ user }: { user: UserRow }) {
  return (
    <span
      aria-hidden
      className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-secondary text-sm font-semibold uppercase text-muted-foreground"
    >
      {nameOf(user).charAt(0)}
    </span>
  );
}

function IconAction({ label, onClick, danger, children }: { label: string; onClick: () => void; danger?: boolean; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={label}
      aria-label={label}
      className={cn(
        "focus-ring inline-flex h-9 w-9 items-center justify-center rounded-xl text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground",
        danger && "hover:bg-destructive/10 hover:text-destructive",
      )}
    >
      {children}
    </button>
  );
}

function UserFormDialog({
  user,
  busy,
  t,
  onSubmit,
  onClose,
}: {
  user: UserRow | null;
  busy: boolean;
  t: T;
  onSubmit: (v: { identifier: string; password: string; displayName: string; email: string }) => void;
  onClose: () => void;
}) {
  const editing = !!user;
  const [identifier, setIdentifier] = useState(user?.identifier ?? "");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState(user?.display_name ?? "");
  const [email, setEmail] = useState(user?.email ?? "");

  return (
    <Dialog title={t(`${k}.form.${editing ? "title_edit" : "title_new"}`)} closeLabel={t(`${k}.form.cancel`)} onClose={onClose} className="max-w-xl">
      <form
        className="flex flex-col gap-4"
        onSubmit={(e) => {
          e.preventDefault();
          onSubmit({ identifier: identifier.trim(), password, displayName: displayName.trim(), email: email.trim() });
        }}
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="flex flex-col gap-1.5">
            <span className="text-sm font-medium">{t(`${k}.form.username`)}</span>
            <input
              autoFocus={!editing}
              type="text"
              value={identifier}
              onChange={(e) => setIdentifier(e.target.value)}
              disabled={editing}
              required={!editing}
              autoComplete="off"
              spellCheck={false}
              placeholder="mario.rossi"
              className={cn(inputCls, "font-mono disabled:cursor-not-allowed disabled:opacity-60")}
            />
            {!editing && <span className="text-xs text-muted-foreground">{t(`${k}.form.username_hint`)}</span>}
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="text-sm font-medium">{t(`${k}.form.password`)}</span>
            <input
              autoFocus={editing}
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required={!editing}
              autoComplete="new-password"
              placeholder="••••••••"
              className={inputCls}
            />
            {editing && <span className="text-xs text-muted-foreground">{t(`${k}.form.password_keep`)}</span>}
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="flex items-baseline justify-between text-sm font-medium">
              {t(`${k}.form.display_name`)}
              <span className="text-xs font-normal text-muted-foreground">{t(`${k}.form.optional`)}</span>
            </span>
            <input
              type="text"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder={t(`${k}.form.display_name_placeholder`)}
              className={inputCls}
            />
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="flex items-baseline justify-between text-sm font-medium">
              {t(`${k}.form.email`)}
              <span className="text-xs font-normal text-muted-foreground">{t(`${k}.form.optional`)}</span>
            </span>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder={t(`${k}.form.email_placeholder`)}
              className={inputCls}
            />
          </label>
        </div>
        <div className="mt-2 flex justify-end gap-2">
          <button type="button" className={ghostBtn} onClick={onClose}>
            {t(`${k}.form.cancel`)}
          </button>
          <button type="submit" className={solidBtn} disabled={busy}>
            {busy && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />}
            {busy ? t(`${k}.form.saving`) : t(`${k}.form.${editing ? "save" : "create"}`)}
          </button>
        </div>
      </form>
    </Dialog>
  );
}

function ProfilesDialog({
  user,
  profiles,
  initial,
  busy,
  t,
  onSave,
  onClose,
}: {
  user: UserRow;
  profiles: ProfileRow[];
  initial: string[];
  busy: boolean;
  t: T;
  onSave: (slugs: string[]) => void;
  onClose: () => void;
}) {
  const [selected, setSelected] = useState<string[]>(initial);
  const toggle = (slug: string) => setSelected((s) => (s.includes(slug) ? s.filter((x) => x !== slug) : [...s, slug]));

  return (
    <Dialog title={t(`${k}.profiles.title`)} closeLabel={t(`${k}.profiles.cancel`)} onClose={onClose} className="max-w-xl">
      <div className="flex flex-col gap-4">
        <p className="text-sm text-muted-foreground">{t(`${k}.profiles.body`, { name: nameOf(user) })}</p>

        <div className="flex items-center justify-between gap-3 text-xs text-muted-foreground">
          <span>{selected.length === 0 ? t(`${k}.profiles.all`) : t(`${k}.profiles.selected`, { count: selected.length })}</span>
          {selected.length > 0 && (
            <button type="button" onClick={() => setSelected([])} className="focus-ring rounded-md font-medium underline underline-offset-4 hover:text-foreground">
              {t(`${k}.profiles.clear`)}
            </button>
          )}
        </div>

        <ul className="-mx-1 flex max-h-[22rem] flex-col gap-0.5 overflow-y-auto px-1">
          {profiles.map((p) => {
            const on = selected.includes(p.slug);
            return (
              <li key={p.slug}>
                <label className={cn("flex cursor-pointer items-start gap-3 rounded-xl px-3 py-2.5 transition-colors", on ? "bg-secondary" : "hover:bg-secondary/60")}>
                  <input type="checkbox" checked={on} onChange={() => toggle(p.slug)} className="focus-ring mt-1 h-4 w-4 shrink-0 accent-foreground" />
                  <span className="min-w-0">
                    <span className="block truncate text-sm font-medium">{p.name}</span>
                    {p.description && <span className="mt-0.5 block text-xs text-muted-foreground">{p.description}</span>}
                  </span>
                </label>
              </li>
            );
          })}
        </ul>
        {profiles.length === 0 && <p className="py-6 text-center text-sm text-muted-foreground">{t(`${k}.profiles.none`)}</p>}
        <p className="text-xs text-muted-foreground">{t(`${k}.profiles.hint`)}</p>

        <div className="flex justify-end gap-2">
          <button type="button" className={ghostBtn} onClick={onClose}>
            {t(`${k}.profiles.cancel`)}
          </button>
          <button type="button" className={solidBtn} disabled={busy} onClick={() => onSave(selected)}>
            {busy && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />}
            {busy ? t(`${k}.profiles.saving`) : t(`${k}.profiles.save`)}
          </button>
        </div>
      </div>
    </Dialog>
  );
}

function ResetDialog({ user, busy, t, onConfirm, onClose }: { user: UserRow; busy: boolean; t: T; onConfirm: () => void; onClose: () => void }) {
  return (
    <Dialog title={t(`${k}.reset.title`)} closeLabel={t(`${k}.reset.cancel`)} onClose={onClose}>
      <div className="flex flex-col gap-5">
        <p className="text-sm text-muted-foreground">{t(`${k}.reset.body`, { name: nameOf(user) })}</p>
        <div className="flex justify-end gap-2">
          <button type="button" className={ghostBtn} autoFocus onClick={onClose}>
            {t(`${k}.reset.cancel`)}
          </button>
          <button type="button" className={dangerBtn} disabled={busy} onClick={onConfirm}>
            {busy && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />}
            {busy ? t(`${k}.reset.resetting`) : t(`${k}.reset.confirm`)}
          </button>
        </div>
      </div>
    </Dialog>
  );
}

export default function UsersPage() {
  const t = useT();

  const [users, setUsers] = useState<UserRow[]>([]);
  const [listState, setListState] = useState<ListState>("loading");
  const [allProfiles, setAllProfiles] = useState<ProfileRow[]>([]);
  const [query, setQuery] = useState("");
  const [filters, setFilters] = useState<Filters>(NO_FILTERS);
  const [loginMode, setLoginMode] = useState("password");
  const [tab, setTab] = useState<Tab>("accounts");
  const [toast, setToast] = useState<ToastState>(null);

  const [formUser, setFormUser] = useState<UserRow | "new" | null>(null);
  const [saving, setSaving] = useState(false);
  const [deleteUser, setDeleteUser] = useState<UserRow | null>(null);
  const [resetUser, setResetUser] = useState<UserRow | null>(null);
  const [profileUser, setProfileUser] = useState<{ user: UserRow; initial: string[] } | null>(null);

  const fail = useCallback((key: string, err: unknown) => setToast({ message: t(`${k}.toast.${key}`, { error: err instanceof Error ? err.message : String(err) }), variant: "error" }), [t]);

  const loadUsers = useCallback(async () => {
    try {
      const res = await apiFetch(`${apiBase()}/admin/users`);
      if (!res.ok) throw new Error(await errorDetail(res, String(res.status)));
      const data = await res.json();
      setUsers(data.users || []);
      setLoginMode(data.login_mode || "password");
      setListState("ready");
    } catch (err) {
      setListState("error");
      fail("load_failed", err);
    }
  }, [fail]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch on mount
    void loadUsers();
    apiFetch(`${apiBase()}/admin/profiles`)
      .then((res) => (res.ok ? res.json() : Promise.reject(res)))
      .then((data) => setAllProfiles(data || []))
      .catch(() => {});
  }, [loadUsers]);

  const plural = (n: number) => t(`${k}.count_${new Intl.PluralRules(getLocale()).select(n) === "one" ? "one" : "other"}`, { count: n });

  const setFilter = (col: keyof Filters, value: string) => setFilters((f) => ({ ...f, [col]: value }));
  const filtering = !!query.trim() || Object.values(filters).some(Boolean);
  const clearFilters = () => {
    setQuery("");
    setFilters(NO_FILTERS);
  };
  const showMigration = loginMode !== "password" || users.some((u) => migrationOf(u) !== "");
  // TOTP is a classic-login feature: with SSO the provider's own 2FA applies.
  const showSecurity = loginMode === "password";
  const grid = GRIDS[`${showMigration ? 1 : 0}${showSecurity ? 1 : 0}`];

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    const has = (v: string | null | undefined, needle: string) => (v || "").toLowerCase().includes(needle.trim().toLowerCase());
    return users.filter((u) => {
      if (filters.user && !has(u.identifier, filters.user) && !has(u.display_name, filters.user)) return false;
      if (filters.email && !has(u.email, filters.email)) return false;
      if (filters.access) {
        const m = methodsOf(u);
        if (filters.access === "none" ? m.length > 0 : !m.includes(filters.access)) return false;
      }
      if (filters.migration && migrationOf(u) !== filters.migration) return false;
      if (showSecurity && filters.twofa && (filters.twofa === "on") !== !!u.totp_enabled) return false;
      return !q || [u.identifier, u.display_name, u.email].some((v) => has(v, q));
    });
  }, [users, query, filters, showSecurity]);

  const filterLabels: ColumnFilterLabels = {
    aria: (col) => t(`${k}.filter.aria`, { col }),
    clear: t(`${k}.filter.clear`),
    search: t(`${k}.filter.search`),
    all: t(`${k}.filter.all`),
  };
  const accessOptions = [...METHODS, "none"].map((v) => ({ value: v, label: t(`${k}.access.${v}`) }));
  const migrationOptions = (["pending", "migrated", "exempt"] as const).map((v) => ({ value: v, label: t(`${k}.migration.${v}`) }));
  const twofaOptions = [
    { value: "on", label: t(`${k}.badge.twofa`) },
    { value: "off", label: t(`${k}.badge.twofa_off`) },
  ];

  const saveUser = async (v: { identifier: string; password: string; displayName: string; email: string }) => {
    const editing = formUser !== null && formUser !== "new";
    if (!editing && (!v.identifier || !v.password)) {
      setToast({ message: t(`${k}.form.required`), variant: "error" });
      return;
    }
    setSaving(true);
    try {
      const payload: Record<string, string> = { display_name: v.displayName, email: v.email };
      if (!editing) payload.identifier = v.identifier;
      if (v.password) payload.password = v.password;
      const res = await apiFetch(editing ? `${apiBase()}/admin/users/${(formUser as UserRow).id}` : `${apiBase()}/admin/users`, {
        method: editing ? "PUT" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error(await errorDetail(res, String(res.status)));
      setFormUser(null);
      setToast({ message: t(`${k}.toast.${editing ? "updated" : "created"}`), variant: "success" });
      void loadUsers();
    } catch (err) {
      fail("save_failed", err);
    } finally {
      setSaving(false);
    }
  };

  const removeUser = async () => {
    if (!deleteUser) return;
    setSaving(true);
    try {
      const res = await apiFetch(`${apiBase()}/admin/users/${deleteUser.id}`, { method: "DELETE" });
      if (!res.ok) throw new Error(await errorDetail(res, String(res.status)));
      setDeleteUser(null);
      setToast({ message: t(`${k}.toast.deleted`), variant: "success" });
      void loadUsers();
    } catch (err) {
      fail("delete_failed", err);
    } finally {
      setSaving(false);
    }
  };

  const resetTwoFactor = async () => {
    if (!resetUser) return;
    setSaving(true);
    try {
      const res = await apiFetch(`${apiBase()}/admin/auth/users/${resetUser.id}/2fa`, { method: "DELETE" });
      if (!res.ok) throw new Error(await errorDetail(res, String(res.status)));
      setResetUser(null);
      setToast({ message: t(`${k}.toast.reset`), variant: "success" });
      void loadUsers();
    } catch (err) {
      fail("reset_failed", err);
    } finally {
      setSaving(false);
    }
  };

  const openProfiles = async (user: UserRow) => {
    try {
      const res = await apiFetch(`${apiBase()}/admin/users/${user.id}/profiles`);
      if (!res.ok) throw new Error(await errorDetail(res, String(res.status)));
      const data = await res.json();
      setProfileUser({ user, initial: data.allowed_profiles || [] });
    } catch (err) {
      fail("profiles_load_failed", err);
    }
  };

  const saveProfiles = async (slugs: string[]) => {
    if (!profileUser) return;
    setSaving(true);
    try {
      const res = await apiFetch(`${apiBase()}/admin/users/${profileUser.user.id}/profiles`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ allowed_profiles: slugs }),
      });
      if (!res.ok) throw new Error(await errorDetail(res, String(res.status)));
      setProfileUser(null);
      setToast({ message: t(`${k}.toast.profiles_saved`), variant: "success" });
    } catch (err) {
      fail("save_failed", err);
    } finally {
      setSaving(false);
    }
  };

  const tabs: { id: Tab; label: string; count?: number }[] = [
    { id: "accounts", label: t(`${k}.tabs.accounts`), count: listState === "ready" ? users.length : undefined },
    { id: "signin", label: t(`${k}.tabs.signin`) },
  ];

  return (
    <div className="mx-auto flex max-w-[84rem] flex-col gap-6">
      <header className="flex flex-col gap-4 pt-2 sm:flex-row sm:items-end">
        <div className="min-w-0 flex-1">
          <h1 className="text-balance text-2xl font-semibold tracking-[-0.02em] sm:text-[28px]">{t(`${k}.title`)}</h1>
          <p className="mt-1 max-w-[60ch] text-sm text-muted-foreground">{t(`${k}.subtitle`)}</p>
        </div>
        <button type="button" className={solidBtn} onClick={() => setFormUser("new")}>
          <Plus className="h-4 w-4" aria-hidden />
          {t(`${k}.add`)}
        </button>
      </header>

      <div role="tablist" aria-label={t(`${k}.tabs.aria`)} className="no-scrollbar -mt-2 flex gap-1 overflow-x-auto border-b border-border/60">
        {tabs.map((x) => {
          const active = tab === x.id;
          return (
            <button
              key={x.id}
              type="button"
              role="tab"
              id={`users-tab-${x.id}`}
              aria-selected={active}
              aria-controls="users-panel"
              onClick={() => setTab(x.id)}
              className={cn(
                "focus-ring relative inline-flex h-11 shrink-0 items-center gap-2 px-3 text-sm font-medium transition-colors",
                active ? "text-foreground" : "text-muted-foreground hover:text-foreground",
              )}
            >
              {x.label}
              {x.count !== undefined && x.count > 0 && (
                <span className="rounded-full bg-secondary px-1.5 py-px text-xs tabular-nums text-muted-foreground">{x.count}</span>
              )}
              <span aria-hidden className={cn("absolute inset-x-3 bottom-0 h-0.5 rounded-full bg-foreground transition-opacity", active ? "opacity-100" : "opacity-0")} />
            </button>
          );
        })}
      </div>

      <div id="users-panel" role="tabpanel" aria-labelledby={`users-tab-${tab}`} className="flex flex-col gap-4">
        {tab === "accounts" && (
          <>
            {listState === "loading" && (
              <div className="flex items-center gap-2 px-1 py-10 text-sm text-muted-foreground" role="status">
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                {t(`${k}.loading`)}
              </div>
            )}

            {listState === "error" && (
              <div className="flex flex-col items-start gap-3 px-1 py-10">
                <p className="text-sm text-destructive">{t(`${k}.error`)}</p>
                <button
                  type="button"
                  className={outlineBtn}
                  onClick={() => {
                    setListState("loading");
                    void loadUsers();
                  }}
                >
                  {t(`${k}.retry`)}
                </button>
              </div>
            )}

            {listState === "ready" && users.length === 0 && (
              <div className="flex flex-col items-center rounded-3xl border border-dashed border-border px-6 py-20 text-center">
                <h2 className="text-lg font-semibold tracking-[-0.015em]">{t(`${k}.empty.title`)}</h2>
                <p className="mt-1.5 max-w-[46ch] text-sm text-muted-foreground">{t(`${k}.empty.body`)}</p>
                <button type="button" className={cn(solidBtn, "mt-6")} onClick={() => setFormUser("new")}>
                  <Plus className="h-4 w-4" aria-hidden />
                  {t(`${k}.add`)}
                </button>
              </div>
            )}

            {listState === "ready" && users.length > 0 && (
              <>
                <div className="flex flex-wrap items-center gap-2">
                  <div className="min-w-[14rem] flex-1 sm:max-w-sm">
                    <SearchField value={query} onChange={setQuery} placeholder={t(`${k}.search`)} />
                  </div>
                  <span className="ml-auto text-sm tabular-nums text-muted-foreground">
                    {filtering ? t(`${k}.count_filtered`, { shown: rows.length, total: users.length }) : plural(users.length)}
                  </span>
                </div>

                <div className="rounded-3xl border border-border/70 bg-card">
                  <div className={cn("hidden items-center gap-4 border-b border-border/60 px-5 py-2 md:grid", grid)}>
                    <ColumnFilter label={t(`${k}.cols.user`)} value={filters.user} onChange={(v) => setFilter("user", v)} labels={filterLabels} />
                    <ColumnFilter label={t(`${k}.cols.email`)} value={filters.email} onChange={(v) => setFilter("email", v)} labels={filterLabels} />
                    <ColumnFilter label={t(`${k}.cols.access`)} value={filters.access} onChange={(v) => setFilter("access", v)} options={accessOptions} labels={filterLabels} />
                    {showMigration && (
                      <ColumnFilter label={t(`${k}.cols.migration`)} value={filters.migration} onChange={(v) => setFilter("migration", v)} options={migrationOptions} labels={filterLabels} />
                    )}
                    {showSecurity && <ColumnFilter label={t(`${k}.cols.security`)} value={filters.twofa} onChange={(v) => setFilter("twofa", v)} options={twofaOptions} labels={filterLabels} />}
                    <span className="text-right text-xs font-medium text-muted-foreground">{t(`${k}.cols.actions`)}</span>
                  </div>

                  {rows.length === 0 ? (
                    <div className="px-6 py-16 text-center">
                      <p className="text-sm text-muted-foreground">{t(`${k}.empty.search`)}</p>
                      <button type="button" className={cn(ghostBtn, "mt-3")} onClick={clearFilters}>
                        {t(`${k}.empty.clear_filters`)}
                      </button>
                    </div>
                  ) : (
                    <ul className="overflow-hidden rounded-b-3xl">
                      {rows.map((u) => {
                        const name = nameOf(u);
                        const migration = migrationOf(u);
                        return (
                          <li key={u.id} className="border-b border-border/40 last:border-b-0">
                            <div className={cn("grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 gap-y-1 px-5 py-3 transition-colors hover:bg-secondary/40", grid)}>
                              <div className="flex min-w-0 items-center gap-3">
                                <Avatar user={u} />
                                <div className="min-w-0">
                                  <div className="truncate text-sm font-medium">{name}</div>
                                  {u.display_name && <div className="truncate font-mono text-xs text-muted-foreground">{u.identifier}</div>}
                                </div>
                              </div>

                              <div className="flex items-center justify-end gap-0.5 md:order-last">
                                <IconAction label={t(`${k}.row.profiles`, { name })} onClick={() => void openProfiles(u)}>
                                  <UserCog className="h-4 w-4" aria-hidden />
                                </IconAction>
                                {u.totp_enabled && (
                                  <IconAction label={t(`${k}.row.reset`, { name })} onClick={() => setResetUser(u)}>
                                    <KeyRound className="h-4 w-4" aria-hidden />
                                  </IconAction>
                                )}
                                <IconAction label={t(`${k}.row.edit`, { name })} onClick={() => setFormUser(u)}>
                                  <Pencil className="h-4 w-4" aria-hidden />
                                </IconAction>
                                <IconAction label={t(`${k}.row.delete`, { name })} onClick={() => setDeleteUser(u)} danger>
                                  <Trash2 className="h-4 w-4" aria-hidden />
                                </IconAction>
                              </div>

                              <div className="col-span-2 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 pl-12 text-xs text-muted-foreground md:contents">
                                <span className="truncate text-sm md:text-muted-foreground">{u.email || <span className="hidden md:inline">—</span>}</span>
                                <span className="min-w-0 truncate text-sm">
                                  {methodsOf(u).length === 0 ? (
                                    <span className="text-muted-foreground">{t(`${k}.access.none`)}</span>
                                  ) : (
                                    methodsOf(u).map((m) => t(`${k}.access.${m}`)).join(" · ")
                                  )}
                                </span>
                                {showMigration && (
                                  <span className="md:block">
                                    {migration === "pending" ? (
                                      <span title={t(`${k}.migration.pending_hint`)} className="inline-flex items-center gap-1 rounded-full bg-warning/15 px-2 py-0.5 text-xs font-medium text-warning">
                                        <TriangleAlert className="h-3 w-3" aria-hidden />
                                        {t(`${k}.migration.pending`)}
                                      </span>
                                    ) : migration ? (
                                      <span className={cn("text-sm", migration === "migrated" ? "text-success" : "text-muted-foreground")}>{t(`${k}.migration.${migration}`)}</span>
                                    ) : (
                                      <span className="hidden text-sm text-muted-foreground md:inline">—</span>
                                    )}
                                  </span>
                                )}
                                {showSecurity && (
                                  <span className="md:block">
                                    {u.totp_enabled ? (
                                      <span className="inline-flex items-center gap-1 text-sm font-medium text-success">
                                        <ShieldCheck className="h-3.5 w-3.5" aria-hidden />
                                        {t(`${k}.badge.twofa`)}
                                      </span>
                                    ) : (
                                      <span className="hidden text-sm text-muted-foreground md:inline">{t(`${k}.badge.twofa_off`)}</span>
                                    )}
                                  </span>
                                )}
                              </div>
                            </div>
                          </li>
                        );
                      })}
                    </ul>
                  )}
                </div>
              </>
            )}
          </>
        )}

        {tab === "signin" && (
          <div className="flex flex-col gap-10">
            <section aria-labelledby="users-sso" className="flex flex-col gap-4">
              <div>
                <h2 id="users-sso" className="text-lg font-semibold tracking-[-0.015em]">
                  {t(`${k}.signin.sso_title`)}
                </h2>
                <p className="mt-1 max-w-[60ch] text-sm text-muted-foreground">{t(`${k}.signin.sso_body`)}</p>
              </div>
              <SsoMigrationPanel />
            </section>

            {showMigration && (
              <section id="users-migration" aria-labelledby="users-mig-title" className="flex scroll-mt-6 flex-col gap-4 border-t border-border/60 pt-8">
                <div>
                  <h2 id="users-mig-title" className="text-lg font-semibold tracking-[-0.015em]">
                    {t(`${k}.migration.title`)}
                  </h2>
                  <p className="mt-1 max-w-[60ch] text-sm text-muted-foreground">{t(`${k}.migration.subtitle`)}</p>
                </div>
                <MigrationUsers />
              </section>
            )}

            {/* TOTP exists only for the classic login; with SSO the provider's own 2FA applies. */}
            {listState === "ready" && loginMode === "password" && (
              <section aria-labelledby="users-tfa" className="flex flex-col gap-4 border-t border-border/60 pt-8">
                <div>
                  <h2 id="users-tfa" className="text-lg font-semibold tracking-[-0.015em]">
                    {t(`${k}.signin.tfa_title`)}
                  </h2>
                  <p className="mt-1 max-w-[60ch] text-sm text-muted-foreground">{t(`${k}.signin.tfa_body`)}</p>
                </div>
                <TwoFactorPanel />
              </section>
            )}
          </div>
        )}
      </div>

      {formUser && (
        <UserFormDialog user={formUser === "new" ? null : formUser} busy={saving} t={t} onSubmit={saveUser} onClose={() => !saving && setFormUser(null)} />
      )}

      {profileUser && (
        <ProfilesDialog
          user={profileUser.user}
          profiles={allProfiles}
          initial={profileUser.initial}
          busy={saving}
          t={t}
          onSave={saveProfiles}
          onClose={() => !saving && setProfileUser(null)}
        />
      )}

      {resetUser && <ResetDialog user={resetUser} busy={saving} t={t} onConfirm={resetTwoFactor} onClose={() => !saving && setResetUser(null)} />}

      {deleteUser && (
        <DeleteDialog name={deleteUser.identifier} busy={saving} ns={`${k}.delete`} t={t} onConfirm={removeUser} onClose={() => !saving && setDeleteUser(null)} />
      )}

      <PageToast toast={toast} onDismiss={() => setToast(null)} />
    </div>
  );
}
