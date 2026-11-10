"use client";

/**
 * Admin page: Service accounts (Access → Service accounts).
 *
 * Service accounts are non-human `users` rows (`account_type='service'`,
 * identifier `svc-<slug>`) used by integrations and scripts. They have no
 * password, SSO or 2FA: they authenticate only with API keys created here,
 * which always expire. From this page an admin lists, creates, edits,
 * disables and deletes accounts, manages their keys (`KeysDialog`) and the
 * agent profiles they may use (`ProfilesDialog`, shared with the Users page).
 *
 * Backend: `/admin/service-accounts*` and `/admin/users/{id}/profiles`.
 * Layout and patterns mirror `app/users/page.tsx`.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { Bot, Brain, KeyRound, Loader2, Pencil, Plus, Trash2, UserCog } from "lucide-react";
import { apiBase } from "@/lib/api";
import { apiFetch } from "@/lib/api/headers";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";
import { getLocale } from "@/lib/i18n/i18n-store";
import { PageToast, type ToastState } from "@/components/PageToast";
import { ghostBtn, outlineBtn, solidBtn } from "@/components/ui/classes";
import { SearchField } from "@/components/ui/SearchField";
import { Switch } from "@/components/settings/ui";
import { ColumnFilter, type ColumnFilterLabels } from "@/components/ui/ColumnFilter";
import { DeleteDialog } from "@/components/ui/ConfirmDialogs";
import { ProfilesDialog, type ProfileRow } from "@/components/users/ProfilesDialog";
import { AccountFormDialog, type AccountFormValues } from "@/components/service-accounts/AccountFormDialog";
import { KeysDialog } from "@/components/service-accounts/KeysDialog";
import { StatusBadge, formatDate, k, nameOf, readError, type ServiceAccount } from "@/components/service-accounts/shared";

/**
 * Columns: account, status, keys, last used, memory, actions. Rows become a table only from xl up:
 * the fixed columns need ~34rem, which leaves no room for the name next to the sidebar below ~1280px.
 */
const GRID = "xl:grid-cols-[minmax(0,2.4fr)_6.5rem_4.5rem_minmax(0,1.3fr)_6.5rem_12.5rem]";

type Filters = { account: string; status: string; ltm: string };
const NO_FILTERS: Filters = { account: "", status: "", ltm: "" };
type ListState = "loading" | "ready" | "error";

/** Square action button of a row, labelled for screen readers and on hover. */
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

/** Empty state: explains what a service account is before the first one exists. */
function EmptyState({ t, onCreate }: { t: (key: string, vars?: Record<string, string | number>) => string; onCreate: () => void }) {
  return (
    <div className="flex flex-col items-center rounded-3xl border border-dashed border-border px-6 py-16 text-center">
      <span aria-hidden className="flex h-11 w-11 items-center justify-center rounded-2xl bg-secondary text-muted-foreground">
        <Bot className="h-5 w-5" />
      </span>
      <h2 className="mt-4 text-lg font-semibold tracking-[-0.015em]">{t(`${k}.empty.title`)}</h2>
      <p className="mt-1.5 max-w-[52ch] text-sm text-muted-foreground">{t(`${k}.empty.body`)}</p>
      <ul className="mt-5 flex max-w-[52ch] flex-col gap-1.5 text-left text-sm text-muted-foreground">
        {(["point_keys", "point_scopes", "point_memory"] as const).map((p) => (
          <li key={p} className="flex gap-2">
            <span aria-hidden className="mt-2 h-1 w-1 shrink-0 rounded-full bg-muted-foreground" />
            {t(`${k}.empty.${p}`)}
          </li>
        ))}
      </ul>
      <button type="button" className={cn(solidBtn, "mt-7")} onClick={onCreate}>
        <Plus className="h-4 w-4" aria-hidden />
        {t(`${k}.add`)}
      </button>
    </div>
  );
}

/** Route component for `/service-accounts`. */
export default function ServiceAccountsPage() {
  const t = useT();

  const [accounts, setAccounts] = useState<ServiceAccount[]>([]);
  const [listState, setListState] = useState<ListState>("loading");
  const [allProfiles, setAllProfiles] = useState<ProfileRow[]>([]);
  const [query, setQuery] = useState("");
  const [filters, setFilters] = useState<Filters>(NO_FILTERS);
  const [toast, setToast] = useState<ToastState>(null);

  const [formAccount, setFormAccount] = useState<ServiceAccount | "new" | null>(null);
  const [slugError, setSlugError] = useState<string | undefined>();
  const [saving, setSaving] = useState(false);
  // Id of the account whose enable/disable switch is being saved.
  const [toggling, setToggling] = useState<string | null>(null);
  const [keysAccount, setKeysAccount] = useState<ServiceAccount | null>(null);
  const [deleteAccount, setDeleteAccount] = useState<ServiceAccount | null>(null);
  const [profileAccount, setProfileAccount] = useState<{ account: ServiceAccount; initial: string[] } | null>(null);

  const fail = useCallback(
    (key: string, err: unknown) => setToast({ message: t(`${k}.toast.${key}`, { error: err instanceof Error ? err.message : String(err) }), variant: "error" }),
    [t],
  );

  const loadAccounts = useCallback(async () => {
    try {
      const res = await apiFetch(`${apiBase()}/admin/service-accounts`);
      if (!res.ok) throw new Error((await readError(res)).message);
      const data = await res.json();
      setAccounts(data.items || []);
      setListState("ready");
    } catch (err) {
      setListState("error");
      fail("load_failed", err);
    }
  }, [fail]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch on mount
    void loadAccounts();
    // Profiles only feed the access dialog: a failure just leaves the list empty.
    apiFetch(`${apiBase()}/admin/profiles`)
      .then((res) => (res.ok ? res.json() : Promise.reject(res)))
      .then((data) => setAllProfiles(data || []))
      .catch(() => {});
  }, [loadAccounts]);

  const plural = (n: number) => t(`${k}.count_${new Intl.PluralRules(getLocale()).select(n) === "one" ? "one" : "other"}`, { count: n });

  const setFilter = (col: keyof Filters, value: string) => setFilters((f) => ({ ...f, [col]: value }));
  const filtering = !!query.trim() || Object.values(filters).some(Boolean);
  const clearFilters = () => {
    setQuery("");
    setFilters(NO_FILTERS);
  };

  const rows = useMemo(() => {
    const has = (v: string | null | undefined, needle: string) => (v || "").toLowerCase().includes(needle.trim().toLowerCase());
    const q = query.trim();
    return accounts.filter((a) => {
      if (filters.account && !has(a.identifier, filters.account) && !has(a.display_name, filters.account)) return false;
      if (filters.status && (filters.status === "disabled") !== a.disabled) return false;
      if (filters.ltm && (filters.ltm === "on") !== a.ltm_enabled) return false;
      return !q || [a.identifier, a.display_name, a.description].some((v) => has(v, q));
    });
  }, [accounts, query, filters]);

  const filterLabels: ColumnFilterLabels = {
    aria: (col) => t(`${k}.filter.aria`, { col }),
    clear: t(`${k}.filter.clear`),
    search: t(`${k}.filter.search`),
    all: t(`${k}.filter.all`),
  };
  const statusOptions = (["active", "disabled"] as const).map((v) => ({ value: v, label: t(`${k}.status.${v}`) }));
  const ltmOptions = (["on", "off"] as const).map((v) => ({ value: v, label: t(`${k}.ltm.${v}`) }));

  /** Creates (POST) or updates (PATCH) the account from the form. A taken slug stays in the form as a field error. */
  const saveAccount = async (v: AccountFormValues) => {
    const editing = formAccount !== null && formAccount !== "new";
    setSaving(true);
    setSlugError(undefined);
    try {
      const common = {
        display_name: v.display_name || null,
        description: v.description || null,
        ltm_enabled: v.ltm_enabled,
        max_api_keys: v.max_api_keys,
        api_key_max_ttl_days: v.api_key_max_ttl_days,
      };
      const res = await apiFetch(editing ? `${apiBase()}/admin/service-accounts/${(formAccount as ServiceAccount).id}` : `${apiBase()}/admin/service-accounts`, {
        method: editing ? "PATCH" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(editing ? common : { slug: v.slug, ...common }),
      });
      if (!res.ok) {
        const err = await readError(res);
        if (!editing && (res.status === 409 || err.code === "user_exists")) {
          setSlugError(t(`${k}.errors.user_exists`, { identifier: `svc-${v.slug}` }));
          return;
        }
        throw new Error(err.message);
      }
      setFormAccount(null);
      setToast({ message: t(`${k}.toast.${editing ? "updated" : "created"}`), variant: "success" });
      void loadAccounts();
    } catch (err) {
      fail("save_failed", err);
    } finally {
      setSaving(false);
    }
  };

  /** Enables or disables an account; while disabled none of its keys authenticate. */
  const toggleDisabled = async (a: ServiceAccount, disabled: boolean) => {
    setToggling(a.id);
    // Optimistic: flip the switch now, roll back on failure.
    setAccounts((list) => list.map((x) => (x.id === a.id ? { ...x, disabled } : x)));
    try {
      const res = await apiFetch(`${apiBase()}/admin/service-accounts/${a.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ disabled }),
      });
      if (!res.ok) throw new Error((await readError(res)).message);
      setToast({ message: t(`${k}.toast.${disabled ? "disabled" : "enabled"}`, { name: nameOf(a) }), variant: "success" });
      void loadAccounts();
    } catch (err) {
      setAccounts((list) => list.map((x) => (x.id === a.id ? { ...x, disabled: a.disabled } : x)));
      fail("save_failed", err);
    } finally {
      setToggling(null);
    }
  };

  const removeAccount = async () => {
    if (!deleteAccount) return;
    setSaving(true);
    try {
      const res = await apiFetch(`${apiBase()}/admin/service-accounts/${deleteAccount.id}`, { method: "DELETE" });
      if (!res.ok) throw new Error((await readError(res)).message);
      setDeleteAccount(null);
      setToast({ message: t(`${k}.toast.deleted`), variant: "success" });
      void loadAccounts();
    } catch (err) {
      fail("delete_failed", err);
    } finally {
      setSaving(false);
    }
  };

  const openProfiles = async (a: ServiceAccount) => {
    try {
      const res = await apiFetch(`${apiBase()}/admin/users/${a.id}/profiles`);
      if (!res.ok) throw new Error((await readError(res)).message);
      const data = await res.json();
      setProfileAccount({ account: a, initial: data.allowed_profiles || [] });
    } catch (err) {
      fail("profiles_load_failed", err);
    }
  };

  const saveProfiles = async (slugs: string[]) => {
    if (!profileAccount) return;
    setSaving(true);
    try {
      const res = await apiFetch(`${apiBase()}/admin/users/${profileAccount.account.id}/profiles`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ allowed_profiles: slugs }),
      });
      if (!res.ok) throw new Error((await readError(res)).message);
      setProfileAccount(null);
      setToast({ message: t(`${k}.toast.profiles_saved`), variant: "success" });
      void loadAccounts();
    } catch (err) {
      fail("save_failed", err);
    } finally {
      setSaving(false);
    }
  };

  const openCreate = () => {
    setSlugError(undefined);
    setFormAccount("new");
  };

  return (
    <div className="mx-auto flex max-w-[84rem] flex-col gap-6">
      <header className="flex flex-col gap-4 pt-2 sm:flex-row sm:items-end">
        <div className="min-w-0 flex-1">
          <h1 className="text-balance text-2xl font-semibold tracking-[-0.02em] sm:text-[28px]">{t(`${k}.title`)}</h1>
          <p className="mt-1 max-w-[64ch] text-sm text-muted-foreground">{t(`${k}.subtitle`)}</p>
        </div>
        {listState === "ready" && accounts.length > 0 && (
          <button type="button" className={solidBtn} onClick={openCreate}>
            <Plus className="h-4 w-4" aria-hidden />
            {t(`${k}.add`)}
          </button>
        )}
      </header>

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
              void loadAccounts();
            }}
          >
            {t(`${k}.retry`)}
          </button>
        </div>
      )}

      {listState === "ready" && accounts.length === 0 && <EmptyState t={t} onCreate={openCreate} />}

      {listState === "ready" && accounts.length > 0 && (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <div className="min-w-[14rem] flex-1 sm:max-w-sm">
              <SearchField value={query} onChange={setQuery} placeholder={t(`${k}.search`)} />
            </div>
            <span className="ml-auto text-sm tabular-nums text-muted-foreground">
              {filtering ? t(`${k}.count_filtered`, { shown: rows.length, total: accounts.length }) : plural(accounts.length)}
            </span>
          </div>

          <div className="rounded-3xl border border-border/70 bg-card">
            <div className={cn("hidden items-center gap-4 border-b border-border/60 px-5 py-2 xl:grid", GRID)}>
              <ColumnFilter label={t(`${k}.cols.account`)} value={filters.account} onChange={(v) => setFilter("account", v)} labels={filterLabels} />
              <ColumnFilter label={t(`${k}.cols.status`)} value={filters.status} onChange={(v) => setFilter("status", v)} options={statusOptions} labels={filterLabels} />
              <span className="text-xs font-medium text-muted-foreground">{t(`${k}.cols.keys`)}</span>
              <span className="text-xs font-medium text-muted-foreground">{t(`${k}.cols.last_used`)}</span>
              <ColumnFilter label={t(`${k}.cols.memory`)} value={filters.ltm} onChange={(v) => setFilter("ltm", v)} options={ltmOptions} labels={filterLabels} />
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
                {rows.map((a) => {
                  const name = nameOf(a);
                  return (
                    <li key={a.id} className="border-b border-border/40 last:border-b-0">
                      <div className={cn("grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 gap-y-1 px-5 py-3 transition-colors hover:bg-secondary/40", GRID)}>
                        <div className="flex min-w-0 items-center gap-3">
                          <span
                            aria-hidden
                            className={cn("flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-secondary", a.disabled ? "text-muted-foreground/60" : "text-muted-foreground")}
                          >
                            <Bot className="h-4 w-4" />
                          </span>
                          <div className="min-w-0">
                            <div className={cn("truncate text-sm font-medium", a.disabled && "text-muted-foreground")}>{name}</div>
                            <div className="truncate text-xs text-muted-foreground">
                              {a.display_name && <span className="font-mono">{a.identifier}</span>}
                              {a.display_name && a.description && " · "}
                              {a.description}
                            </div>
                          </div>
                        </div>

                        <div className="flex items-center justify-end gap-0.5 xl:order-last">
                          <IconAction label={t(`${k}.row.keys`, { name })} onClick={() => setKeysAccount(a)}>
                            <KeyRound className="h-4 w-4" aria-hidden />
                          </IconAction>
                          <IconAction label={t(`${k}.row.profiles`, { name })} onClick={() => void openProfiles(a)}>
                            <UserCog className="h-4 w-4" aria-hidden />
                          </IconAction>
                          <IconAction label={t(`${k}.row.edit`, { name })} onClick={() => setFormAccount(a)}>
                            <Pencil className="h-4 w-4" aria-hidden />
                          </IconAction>
                          <IconAction label={t(`${k}.row.delete`, { name })} onClick={() => setDeleteAccount(a)} danger>
                            <Trash2 className="h-4 w-4" aria-hidden />
                          </IconAction>
                          <span className="ml-1.5 inline-flex" title={t(`${k}.row.${a.disabled ? "enable" : "disable"}`, { name })}>
                            <Switch
                              checked={!a.disabled}
                              disabled={toggling === a.id}
                              onChange={(on) => void toggleDisabled(a, !on)}
                              label={t(`${k}.row.${a.disabled ? "enable" : "disable"}`, { name })}
                            />
                          </span>
                        </div>

                        {/* On mobile these cells wrap under the name; from xl up they become grid columns (display: contents). */}
                        <div className="col-span-2 flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 pl-12 text-xs text-muted-foreground xl:contents">
                          <span className="xl:block">
                            <StatusBadge
                              tone={a.disabled ? "muted" : "success"}
                              label={t(`${k}.status.${a.disabled ? "disabled" : "active"}`)}
                            />
                          </span>
                          <span
                            className="text-sm tabular-nums xl:text-foreground"
                            title={t(`${k}.keys_badge_title`, { active: a.active_keys, max: a.max_api_keys })}
                          >
                            <span className="xl:hidden">{t(`${k}.cols.keys`)} </span>
                            {a.active_keys}
                            <span className="text-muted-foreground">/{a.max_api_keys}</span>
                          </span>
                          <span className="min-w-0 truncate text-sm tabular-nums" title={a.last_used_at ? formatDate(a.last_used_at) : undefined}>
                            {a.last_used_at ? formatDate(a.last_used_at) : <span className="text-muted-foreground">{t(`${k}.never_used`)}</span>}
                          </span>
                          <span className={cn("inline-flex items-center gap-1 text-sm", a.ltm_enabled ? "text-foreground" : "text-muted-foreground")}>
                            <Brain className="h-3.5 w-3.5" aria-hidden />
                            {t(`${k}.ltm.${a.ltm_enabled ? "on" : "off"}`)}
                          </span>
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

      {formAccount && (
        <AccountFormDialog
          account={formAccount === "new" ? null : (accounts.find((a) => a.id === formAccount.id) ?? formAccount)}
          busy={saving}
          slugError={slugError}
          t={t}
          onSubmit={saveAccount}
          onClose={() => !saving && setFormAccount(null)}
        />
      )}

      {keysAccount && (
        <KeysDialog
          account={accounts.find((a) => a.id === keysAccount.id) ?? keysAccount}
          t={t}
          onChanged={() => void loadAccounts()}
          onToast={setToast}
          onClose={() => setKeysAccount(null)}
        />
      )}

      {profileAccount && (
        <ProfilesDialog
          name={nameOf(profileAccount.account)}
          profiles={allProfiles}
          initial={profileAccount.initial}
          busy={saving}
          t={t}
          ns={`${k}.profiles`}
          onSave={saveProfiles}
          onClose={() => !saving && setProfileAccount(null)}
        />
      )}

      {deleteAccount && (
        <DeleteDialog name={deleteAccount.identifier} busy={saving} ns={`${k}.delete`} t={t} onConfirm={removeAccount} onClose={() => !saving && setDeleteAccount(null)} />
      )}

      <PageToast toast={toast} onDismiss={() => setToast(null)} />
    </div>
  );
}
