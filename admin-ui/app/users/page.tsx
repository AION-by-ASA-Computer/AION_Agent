"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { KeyRound, Loader2, Mail, MailWarning, Pencil, Plus, RectangleEllipsis, ShieldCheck, Trash2, TriangleAlert, UserCog, UserRound } from "lucide-react";
import { apiBase } from "@/lib/api";
import { apiFetch } from "@/lib/api/headers";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";
import { getLocale } from "@/lib/i18n/i18n-store";
import { PageToast, type ToastState } from "@/components/PageToast";
import { Dialog } from "@/components/profiles/Dialog";
import { dangerBtn, ghostBtn, inputCls, outlineBtn, solidBtn } from "@/components/ui/classes";
import { SearchField } from "@/components/ui/SearchField";
import { Switch } from "@/components/settings/ui";
import { ColumnFilter, type ColumnFilterLabels } from "@/components/ui/ColumnFilter";
import { DeleteDialog } from "@/components/ui/ConfirmDialogs";
import { SsoMigrationPanel } from "@/components/sso/SsoMigrationPanel";
import { linkErrorText } from "@/components/sso/setupLinks";
import { MigrationUsers } from "@/components/sso/MigrationUsers";
import { TempPasswordsDialog, type TempPassword } from "@/components/sso/TempPasswordsDialog";
import { TwoFactorPanel } from "@/components/sso/TwoFactorPanel";

const k = "admin_users";
const GRIDS: Record<string, string> = {
  "00": "md:grid-cols-[minmax(0,2fr)_minmax(0,1.6fr)_minmax(0,1.2fr)_12.5rem]",
  "01": "md:grid-cols-[minmax(0,2fr)_minmax(0,1.6fr)_minmax(0,1.2fr)_6.5rem_12.5rem]",
  "10": "md:grid-cols-[minmax(0,2fr)_minmax(0,1.6fr)_minmax(0,1.2fr)_7.5rem_12.5rem]",
  "11": "md:grid-cols-[minmax(0,2fr)_minmax(0,1.6fr)_minmax(0,1.2fr)_7.5rem_6.5rem_12.5rem]",
};

type Filters = { user: string; email: string; access: string; migration: string; twofa: string };
const NO_FILTERS: Filters = { user: "", email: "", access: "", migration: "", twofa: "" };
const METHODS = ["password", "microsoft", "google"] as const;

type Tab = "accounts" | "signin" | "migration";
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
  roles?: string[];
  can_create_api_keys?: boolean;
  max_api_keys?: number;
  api_key_max_ttl_days?: number;
  api_keys_active?: number;
  setup_link_pending?: boolean;
  setup_link_purpose?: "invite" | "reset" | "migration" | null;
  setup_link_expires_at?: string | null;
  setup_link_send_error?: string | null;
  temp_password_pending?: boolean;
  temp_password_expires_at?: string | null;
}

const isAdmin = (u: UserRow) => !!u.roles?.includes("admin");
/** Migrated to SSO: signs in through the identity provider, no local password. */
const isSsoUser = (u: UserRow) => !!u.login_method && u.login_method !== "password";

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

type FormValues = {
  identifier: string;
  displayName: string;
  email: string;
  admin: boolean;
  can_create_api_keys: boolean;
  max_api_keys: number;
  api_key_max_ttl_days: number;
};

/** Per-user API key policy: allowed ranges and the defaults the backend applies to new users. */
const API_KEYS_LIMIT = { min: 1, max: 100, default: 5 };
const API_KEY_DAYS = { min: 1, max: 3650, default: 90 };

/** Whole number within the range, or null when the text isn't one. */
function parseInRange(text: string, range: { min: number; max: number }): number | null {
  if (!/^\d+$/.test(text.trim())) return null;
  const n = Number(text);
  return n >= range.min && n <= range.max ? n : null;
}

const nameOf = (u: UserRow) => u.display_name || u.identifier;

async function errorDetail(res: Response, fallback: string) {
  try {
    const data = await res.json();
    return typeof data?.detail === "string" ? data.detail : typeof data?.detail?.code === "string" ? data.detail.code : fallback;
  } catch {
    return fallback;
  }
}

/** Basic shape check; the backend validates the address for real. */
const looksLikeEmail = (v: string) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v.trim());

const emailError = linkErrorText;

const formatDate = (iso: string) => new Date(iso).toLocaleString(getLocale(), { dateStyle: "medium", timeStyle: "short" });

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

/** Suggested username from the display name (or the email's local part): "Mario Rossi" -> "mario.rossi". */
function suggestIdentifier(displayName: string, email: string): string {
  const source = displayName.trim() || email.split("@")[0] || "";
  return source
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/\s+/g, ".")
    .replace(/[^a-z0-9._-]/g, "")
    .replace(/\.{2,}/g, ".")
    .replace(/^[._-]+|[._-]+$/g, "");
}

function Field({ label, htmlFor, optional, hint, children, t }: { label: string; htmlFor: string; optional?: boolean; hint?: string; children: React.ReactNode; t: T }) {
  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <label htmlFor={htmlFor} className="flex items-baseline justify-between gap-2 text-sm font-medium">
        {label}
        {optional && <span className="text-xs font-normal text-muted-foreground">{t(`${k}.form.optional`)}</span>}
      </label>
      {children}
      {hint && <span className="text-xs text-muted-foreground">{hint}</span>}
    </div>
  );
}

function NumberField({
  id,
  label,
  value,
  onChange,
  range,
  disabled,
  t,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (v: string) => void;
  range: { min: number; max: number };
  disabled: boolean;
  t: T;
}) {
  const invalid = !disabled && parseInRange(value, range) === null;
  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <label htmlFor={id} className={cn("text-sm font-medium", disabled && "text-muted-foreground")}>
        {label}
      </label>
      <input
        id={id}
        type="number"
        inputMode="numeric"
        min={range.min}
        max={range.max}
        step={1}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        aria-invalid={invalid}
        aria-describedby={`${id}-hint`}
        className={cn(inputCls, "tabular-nums disabled:cursor-not-allowed disabled:opacity-60", invalid && "border-destructive/60 hover:border-destructive/70 focus:border-destructive")}
      />
      <span id={`${id}-hint`} className={cn("text-xs", invalid ? "text-destructive" : "text-muted-foreground")}>
        {t(`${k}.form.api_keys.${invalid ? "range_error" : "range_hint"}`, { min: range.min, max: range.max })}
      </span>
    </div>
  );
}

/** Whether the user may create their own API keys in chat-ui, how many and for how long. */
function ApiKeyPolicy({
  enabled,
  onEnabled,
  maxKeys,
  onMaxKeys,
  maxDays,
  onMaxDays,
  revoking,
  activeKeys,
  t,
}: {
  enabled: boolean;
  onEnabled: (v: boolean) => void;
  maxKeys: string;
  onMaxKeys: (v: string) => void;
  maxDays: string;
  onMaxDays: (v: string) => void;
  revoking: boolean;
  activeKeys: number;
  t: T;
}) {
  return (
    <fieldset className="flex flex-col gap-4">
      <legend className="sr-only">{t(`${k}.form.api_keys.title`)}</legend>
      <div>
        <p className="text-sm font-medium">{t(`${k}.form.api_keys.title`)}</p>
        <p className="mt-0.5 text-xs text-muted-foreground">{t(`${k}.form.api_keys.description`)}</p>
      </div>
      <div className="flex items-center gap-4">
        <div className="min-w-0 flex-1">
          <p className="text-sm">{t(`${k}.form.api_keys.enable`)}</p>
          <p className="mt-0.5 text-xs text-muted-foreground">{t(`${k}.form.api_keys.enable_description`)}</p>
        </div>
        <Switch checked={enabled} onChange={onEnabled} label={t(`${k}.form.api_keys.enable`)} />
      </div>
      {revoking && (
        <p role="alert" className="flex items-start gap-2 rounded-xl bg-warning/10 px-3 py-2 text-xs text-warning">
          <TriangleAlert className="mt-px h-3.5 w-3.5 shrink-0" aria-hidden />
          {activeKeys > 0 ? t(`${k}.form.api_keys.revoke_warning`, { count: activeKeys }) : t(`${k}.form.api_keys.revoke_warning_none`)}
        </p>
      )}
      <div className="grid gap-4 sm:grid-cols-2">
        <NumberField id="user-form-api-keys-max" label={t(`${k}.form.api_keys.max_keys`)} value={maxKeys} onChange={onMaxKeys} range={API_KEYS_LIMIT} disabled={!enabled} t={t} />
        <NumberField id="user-form-api-keys-days" label={t(`${k}.form.api_keys.max_days`)} value={maxDays} onChange={onMaxDays} range={API_KEY_DAYS} disabled={!enabled} t={t} />
      </div>
    </fieldset>
  );
}

function RolePicker({ admin, onChange, t }: { admin: boolean; onChange: (v: boolean) => void; t: T }) {
  const options = [
    { value: false, label: t(`${k}.form.role_user`), hint: t(`${k}.form.role_user_hint`), Icon: UserRound },
    { value: true, label: t(`${k}.form.admin`), hint: t(`${k}.form.admin_hint`), Icon: ShieldCheck },
  ];
  return (
    <fieldset className="flex flex-col gap-1.5">
      <legend className="mb-1.5 text-sm font-medium">{t(`${k}.form.role`)}</legend>
      <div className="grid gap-2 sm:grid-cols-2">
        {options.map(({ value, label, hint, Icon }) => {
          const on = admin === value;
          return (
            <label
              key={label}
              className={cn(
                "flex cursor-pointer items-start gap-3 rounded-xl border px-3 py-2.5 transition-colors has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ring/50 has-[:focus-visible]:ring-offset-2 has-[:focus-visible]:ring-offset-background",
                on ? "border-foreground/50 bg-secondary/70" : "border-border hover:border-foreground/25 hover:bg-secondary/40",
              )}
            >
              <input type="radio" name="user-form-role" checked={on} onChange={() => onChange(value)} className="sr-only" />
              <Icon className={cn("mt-0.5 h-4 w-4 shrink-0", on ? "text-foreground" : "text-muted-foreground")} aria-hidden />
              <span className="min-w-0">
                <span className="block text-sm font-medium">{label}</span>
                <span className="mt-0.5 block text-xs text-muted-foreground">{hint}</span>
              </span>
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}

/** Password status of an existing account, with the action that emails a link to (re)set it, or issues a temporary password without SMTP. */
function PasswordAccess({ user, busy, smtpMissing, t, onSendLink }: { user: UserRow; busy: boolean; smtpMissing: boolean; t: T; onSendLink: (u: UserRow) => void }) {
  const pending = !!user.setup_link_pending;
  const status = user.temp_password_pending
    ? user.temp_password_expires_at
      ? t(`${k}.form.temp_pending`, { date: formatDate(user.temp_password_expires_at) })
      : t(`${k}.form.temp_pending_nodate`)
    : user.setup_link_send_error
      ? t(`${k}.form.link_send_failed`, { error: emailError(t, user.setup_link_send_error) })
      : pending && user.setup_link_expires_at
        ? t(`${k}.form.link_pending`, { date: formatDate(user.setup_link_expires_at) })
        : user.has_password
          ? t(`${k}.form.password_set`)
          : t(`${k}.form.password_not_set`);
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-sm font-medium">{t(`${k}.form.password`)}</span>
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-dashed border-border px-3.5 py-2.5">
        <span className={cn("text-sm", user.setup_link_send_error ? "text-destructive" : "text-muted-foreground")}>{status}</span>
        {smtpMissing ? (
          <button type="button" className={outlineBtn} disabled={busy} onClick={() => onSendLink(user)}>
            {busy ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <RectangleEllipsis className="h-4 w-4" aria-hidden />}
            {t(`${k}.form.issue_temp`)}
          </button>
        ) : user.email ? (
          <button type="button" className={outlineBtn} disabled={busy} onClick={() => onSendLink(user)}>
            {busy ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <Mail className="h-4 w-4" aria-hidden />}
            {t(`${k}.form.${user.has_password ? "send_reset" : "resend_invite"}`)}
          </button>
        ) : (
          <span className="text-xs text-muted-foreground">{t(`${k}.form.link_needs_email`)}</span>
        )}
      </div>
      <p className="text-xs text-muted-foreground">{t(`${k}.form.${smtpMissing ? "temp_hint" : "link_hint"}`)}</p>
    </div>
  );
}

function UserFormDialog({
  user,
  busy,
  linkBusy,
  smtpMissing,
  t,
  onSubmit,
  onSendLink,
  onClose,
}: {
  user: UserRow | null;
  busy: boolean;
  linkBusy: boolean;
  smtpMissing: boolean;
  t: T;
  onSubmit: (v: FormValues) => Promise<boolean>;
  onSendLink: (u: UserRow) => void;
  onClose: () => void;
}) {
  const editing = !!user;
  const sso = !!user && isSsoUser(user);
  const [displayName, setDisplayName] = useState(user?.display_name ?? "");
  const [email, setEmail] = useState(user?.email ?? "");
  const [identifier, setIdentifier] = useState(user?.identifier ?? "");
  // Until the admin types a username, keep suggesting one from the name.
  const [identifierTouched, setIdentifierTouched] = useState(editing);
  const [admin, setAdmin] = useState(!!user && isAdmin(user));
  const initialMaxKeys = user?.max_api_keys ?? API_KEYS_LIMIT.default;
  const initialMaxDays = user?.api_key_max_ttl_days ?? API_KEY_DAYS.default;
  const [apiKeysEnabled, setApiKeysEnabled] = useState(!!user?.can_create_api_keys);
  const [maxKeys, setMaxKeys] = useState(String(initialMaxKeys));
  const [maxDays, setMaxDays] = useState(String(initialMaxDays));

  const ident = identifierTouched ? identifier : suggestIdentifier(displayName, email);
  // New accounts get their password through the invitation email, so it must be there (without SMTP they get a temporary password instead).
  const emailOk = editing || smtpMissing ? !email.trim() || looksLikeEmail(email) : looksLikeEmail(email);
  const maxKeysValue = parseInRange(maxKeys, API_KEYS_LIMIT);
  const maxDaysValue = parseInRange(maxDays, API_KEY_DAYS);
  // The limits only matter while the switch is on; when off, unparseable edits fall back to the stored values.
  const apiKeysOk = !apiKeysEnabled || (maxKeysValue !== null && maxDaysValue !== null);
  const revokingKeys = editing && !!user.can_create_api_keys && !apiKeysEnabled;
  const canSubmit = !busy && !!ident.trim() && emailOk && apiKeysOk;

  return (
    <Dialog title={t(`${k}.form.${editing ? "title_edit" : "title_new"}`)} closeLabel={t(`${k}.form.cancel`)} onClose={onClose} className="max-w-xl">
      <form
        className="flex flex-col"
        onSubmit={async (e) => {
          e.preventDefault();
          if (!canSubmit) return;
          const v: FormValues = {
            identifier: ident.trim(),
            displayName: displayName.trim(),
            email: email.trim(),
            admin,
            can_create_api_keys: apiKeysEnabled,
            max_api_keys: maxKeysValue ?? initialMaxKeys,
            api_key_max_ttl_days: maxDaysValue ?? initialMaxDays,
          };
          await onSubmit(v);
        }}
      >
        {editing && (
          <div className="mb-5 flex items-center gap-3">
            <Avatar user={user} />
            <div className="min-w-0">
              <p className="truncate text-sm font-medium">{nameOf(user)}</p>
              <p className="truncate font-mono text-xs text-muted-foreground">{user.identifier}</p>
            </div>
          </div>
        )}

        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={t(`${k}.form.display_name`)} htmlFor="user-form-name" optional t={t}>
            <input
              id="user-form-name"
              autoFocus
              type="text"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder={t(`${k}.form.display_name_placeholder`)}
              autoComplete="off"
              className={inputCls}
            />
          </Field>
          <Field label={t(`${k}.form.email`)} htmlFor="user-form-email" optional={editing || smtpMissing} hint={editing || smtpMissing ? undefined : t(`${k}.form.email_invite_hint`)} t={t}>
            <input
              id="user-form-email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder={t(`${k}.form.email_placeholder`)}
              autoComplete="off"
              required={!editing && !smtpMissing}
              aria-invalid={!!email.trim() && !looksLikeEmail(email)}
              className={inputCls}
            />
          </Field>
        </div>

        <div className="mt-6 flex flex-col gap-4 border-t border-border/60 pt-5">
          {!editing && (
            <Field label={t(`${k}.form.username`)} htmlFor="user-form-username" hint={t(`${k}.form.username_hint`)} t={t}>
              <input
                id="user-form-username"
                type="text"
                value={ident}
                onChange={(e) => {
                  setIdentifierTouched(true);
                  setIdentifier(e.target.value);
                }}
                required
                autoComplete="off"
                autoCapitalize="none"
                spellCheck={false}
                placeholder="mario.rossi"
                className={cn(inputCls, "font-mono")}
              />
            </Field>
          )}

          {!editing ? (
            <p className="rounded-xl bg-secondary/60 px-3 py-2 text-xs text-muted-foreground">{t(`${k}.form.${smtpMissing ? "temp_note" : "invite_note"}`)}</p>
          ) : sso ? (
            <div className="flex flex-col gap-1.5">
              <span className="text-sm font-medium">{t(`${k}.form.password`)}</span>
              <p className="rounded-xl bg-secondary/60 px-3 py-2 text-xs text-muted-foreground">
                {t(`${k}.form.password_sso`, { provider: t(`${k}.access.${user.login_method}`) })}
              </p>
            </div>
          ) : (
            <PasswordAccess user={user} busy={linkBusy} smtpMissing={smtpMissing} t={t} onSendLink={onSendLink} />
          )}
        </div>

        <div className="mt-6 border-t border-border/60 pt-5">
          <RolePicker admin={admin} onChange={setAdmin} t={t} />
        </div>

        <div className="mt-6 border-t border-border/60 pt-5">
          <ApiKeyPolicy
            enabled={apiKeysEnabled}
            onEnabled={setApiKeysEnabled}
            maxKeys={maxKeys}
            onMaxKeys={setMaxKeys}
            maxDays={maxDays}
            onMaxDays={setMaxDays}
            revoking={revokingKeys}
            activeKeys={user?.api_keys_active ?? 0}
            t={t}
          />
        </div>

        <div className="mt-7 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <button type="button" className={cn(ghostBtn, "justify-center")} onClick={onClose}>
            {t(`${k}.form.cancel`)}
          </button>
          <button type="submit" className={cn(solidBtn, "justify-center")} disabled={!canSubmit}>
            {busy && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />}
            {busy ? t(`${k}.form.saving`) : t(`${k}.form.${editing ? "save" : smtpMissing ? "create_with_temp" : "create_and_invite"}`)}
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

/** Without SMTP a reset replaces the current password right away, so it is confirmed first. */
function TempResetDialog({ user, busy, t, onConfirm, onClose }: { user: UserRow; busy: boolean; t: T; onConfirm: () => void; onClose: () => void }) {
  return (
    <Dialog title={t(`${k}.temp_reset.title`)} closeLabel={t(`${k}.temp_reset.cancel`)} onClose={onClose}>
      <div className="flex flex-col gap-5">
        <p className="text-sm text-muted-foreground">{t(`${k}.temp_reset.body`, { name: nameOf(user) })}</p>
        <div className="flex justify-end gap-2">
          <button type="button" className={ghostBtn} autoFocus onClick={onClose}>
            {t(`${k}.temp_reset.cancel`)}
          </button>
          <button type="button" className={dangerBtn} disabled={busy} onClick={onConfirm}>
            {busy && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />}
            {t(`${k}.temp_reset.confirm`)}
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
  const [linkBusy, setLinkBusy] = useState<string | null>(null);
  // null while unknown: the backend decides between email and temporary password anyway.
  const [smtpConfigured, setSmtpConfigured] = useState<boolean | null>(null);
  // Shown once, right after the backend issues them (no SMTP): never stored nor fetched again.
  const [tempPasswords, setTempPasswords] = useState<TempPassword[] | null>(null);
  const [tempResetUser, setTempResetUser] = useState<UserRow | null>(null);
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
    apiFetch(`${apiBase()}/admin/smtp`)
      .then((res) => (res.ok ? res.json() : Promise.reject(res)))
      .then((data) => setSmtpConfigured(!!data.configured))
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
  // With SSO, accounts are created at first sign-in (see the new-account policy), never here.
  const canCreate = loginMode === "password";
  // Without SMTP accounts get a temporary password the admin hands over, changed at first sign-in.
  const smtpMissing = smtpConfigured === false;
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

  /** Resolves true on success. New accounts get an invitation email, or a one-time temporary password without SMTP. */
  const saveUser = async (v: FormValues): Promise<boolean> => {
    const editing = formUser !== null && formUser !== "new";
    const current = editing ? (formUser as UserRow) : null;
    if (!editing && (!v.identifier || (v.email ? !looksLikeEmail(v.email) : !smtpMissing))) {
      setToast({ message: t(`${k}.form.required`), variant: "error" });
      return false;
    }
    setSaving(true);
    try {
      // Keep any non-admin roles the user already has; only toggle "admin".
      const roles = [...(current?.roles ?? []).filter((r) => r !== "admin"), ...(v.admin ? ["admin"] : [])];
      const payload: Record<string, unknown> = {
        display_name: v.displayName,
        email: v.email,
        roles,
        can_create_api_keys: v.can_create_api_keys,
        max_api_keys: v.max_api_keys,
        api_key_max_ttl_days: v.api_key_max_ttl_days,
      };
      if (!editing) payload.identifier = v.identifier;
      const res = await apiFetch(editing ? `${apiBase()}/admin/users/${(formUser as UserRow).id}` : `${apiBase()}/admin/users`, {
        method: editing ? "PUT" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!editing && res.status === 409) {
        const code = await errorDetail(res, "");
        if (code === "sso_active_user_creation_disabled") {
          // SSO was switched on meanwhile: creation is no longer allowed.
          setFormUser(null);
          setToast({ message: t(`${k}.toast.sso_user_creation_disabled`), variant: "warning" });
          void loadUsers();
          return false;
        }
        throw new Error(code || "409");
      }
      if (!res.ok) throw new Error(await errorDetail(res, String(res.status)));
      setFormUser(null);
      if (editing) {
        setToast({ message: t(`${k}.toast.updated`), variant: "success" });
      } else {
        const data = await res.json().catch(() => ({}));
        if (data?.delivery === "temp_password" && data.temp_password?.password) {
          setSmtpConfigured(false);
          setTempPasswords([{ user_id: data.id, identifier: v.identifier, email: v.email || null, ...data.temp_password }]);
        } else {
          const invite = data?.invite;
          setToast(
            invite?.sent
              ? { message: t(`${k}.toast.invite_sent`, { email: v.email }), variant: "success" }
              : { message: t(`${k}.toast.invite_failed`, { email: v.email, error: emailError(t, invite?.error) }), variant: "warning" },
          );
        }
      }
      void loadUsers();
      return true;
    } catch (err) {
      fail("save_failed", err);
      return false;
    } finally {
      setSaving(false);
    }
  };

  /** Emails a one-time link to set (invite) or reset the password; without SMTP issues a temporary password instead. */
  const sendLink = async (user: UserRow) => {
    if (smtpMissing && user.has_password && tempResetUser?.id !== user.id) {
      setTempResetUser(user);
      return;
    }
    setTempResetUser(null);
    setLinkBusy(user.id);
    try {
      const res = await apiFetch(`${apiBase()}/admin/users/${user.id}/password-link`, { method: "POST" });
      if (!res.ok) {
        const code = await errorDetail(res, String(res.status));
        setToast({ message: t(`${k}.toast.link_failed`, { error: emailError(t, code) }), variant: "error" });
        return;
      }
      const data = await res.json();
      if (data.delivery === "temp_password" && data.temp_password?.password) {
        setSmtpConfigured(false);
        setTempPasswords([{ user_id: user.id, identifier: user.identifier, email: user.email, ...data.temp_password }]);
        void loadUsers();
        return;
      }
      setToast(
        data.sent
          ? { message: t(`${k}.toast.link_sent_${data.purpose === "reset" ? "reset" : "invite"}`, { email: user.email || "" }), variant: "success" }
          : { message: t(`${k}.toast.link_failed`, { error: emailError(t, data.error) }), variant: "warning" },
      );
      void loadUsers();
    } catch (err) {
      fail("save_failed", err);
    } finally {
      setLinkBusy(null);
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

  const tabs: { id: Tab; label: string; count?: number; alert?: boolean }[] = [
    { id: "accounts", label: t(`${k}.tabs.accounts`), count: listState === "ready" ? users.length : undefined },
    { id: "signin", label: t(`${k}.tabs.signin`) },
    ...(showMigration
      ? [{ id: "migration" as const, label: t(`${k}.tabs.migration`), count: listState === "ready" ? users.filter((u) => migrationOf(u) === "pending").length : undefined, alert: true }]
      : []),
  ];

  return (
    <div className="mx-auto flex max-w-[84rem] flex-col gap-6">
      <header className="flex flex-col gap-4 pt-2 sm:flex-row sm:items-end">
        <div className="min-w-0 flex-1">
          <h1 className="text-balance text-2xl font-semibold tracking-[-0.02em] sm:text-[28px]">{t(`${k}.title`)}</h1>
          <p className="mt-1 max-w-[60ch] text-sm text-muted-foreground">{t(`${k}.subtitle`)}</p>
        </div>
        {canCreate ? (
          <button type="button" className={solidBtn} onClick={() => setFormUser("new")}>
            <Plus className="h-4 w-4" aria-hidden />
            {t(`${k}.add`)}
          </button>
        ) : (
          listState === "ready" && (
            <p className="max-w-[34ch] text-sm text-muted-foreground sm:text-right">
              {t(`${k}.sso_add_hint`)}{" "}
              <button type="button" className="focus-ring rounded font-medium text-foreground underline underline-offset-4" onClick={() => setTab("signin")}>
                {t(`${k}.sso_add_manage`)}
              </button>
            </p>
          )
        )}
      </header>

      {smtpMissing && (
        <div className="flex items-start gap-2.5 rounded-2xl bg-secondary/60 px-4 py-3 text-sm" role="status">
          <MailWarning className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
          <p className="min-w-0 flex-1 leading-relaxed text-muted-foreground">
            {t(`${k}.smtp_missing.body`)}{" "}
            <Link href="/settings#smtp" className="focus-ring rounded font-medium text-foreground underline underline-offset-4">
              {t(`${k}.smtp_missing.link`)}
            </Link>
          </p>
        </div>
      )}

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
                <span className={cn("rounded-full px-1.5 py-px text-xs tabular-nums", x.alert ? "bg-warning/15 font-medium text-warning" : "bg-secondary text-muted-foreground")}>{x.count}</span>
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
                <p className="mt-1.5 max-w-[46ch] text-sm text-muted-foreground">{t(canCreate ? `${k}.empty.body` : `${k}.empty.sso_body`)}</p>
                {canCreate && (
                  <button type="button" className={cn(solidBtn, "mt-6")} onClick={() => setFormUser("new")}>
                    <Plus className="h-4 w-4" aria-hidden />
                    {t(`${k}.add`)}
                  </button>
                )}
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
                                  <div className="flex min-w-0 items-center gap-2">
                                    <span className="truncate text-sm font-medium">{name}</span>
                                    {isAdmin(u) && <span className="shrink-0 rounded-full bg-secondary px-2 py-0.5 text-xs font-medium text-muted-foreground">{t(`${k}.badge.admin`)}</span>}
                                    {u.can_create_api_keys && (
                                      <span
                                        title={t(`${k}.form.api_keys.badge_title`, { active: u.api_keys_active ?? 0, max: u.max_api_keys ?? API_KEYS_LIMIT.default })}
                                        className="shrink-0 rounded-full bg-secondary px-2 py-0.5 text-xs font-medium tabular-nums text-muted-foreground"
                                      >
                                        {t(`${k}.form.api_keys.badge`, { active: u.api_keys_active ?? 0, max: u.max_api_keys ?? API_KEYS_LIMIT.default })}
                                      </span>
                                    )}
                                    {u.temp_password_pending ? (
                                      <span
                                        title={u.temp_password_expires_at ? t(`${k}.badge.link_expires`, { date: formatDate(u.temp_password_expires_at) }) : undefined}
                                        className="inline-flex shrink-0 items-center gap-1 rounded-full bg-secondary px-2 py-0.5 text-xs font-medium text-muted-foreground"
                                      >
                                        <RectangleEllipsis className="h-3 w-3" aria-hidden />
                                        {t(`${k}.badge.temp_password`)}
                                      </span>
                                    ) : u.setup_link_send_error ? (
                                      <span
                                        title={emailError(t, u.setup_link_send_error)}
                                        className="inline-flex shrink-0 items-center gap-1 rounded-full bg-destructive/10 px-2 py-0.5 text-xs font-medium text-destructive"
                                      >
                                        <MailWarning className="h-3 w-3" aria-hidden />
                                        {t(`${k}.badge.link_failed`)}
                                      </span>
                                    ) : (
                                      u.setup_link_pending && (
                                        <span
                                          title={u.setup_link_expires_at ? t(`${k}.badge.link_expires`, { date: formatDate(u.setup_link_expires_at) }) : undefined}
                                          className="inline-flex shrink-0 items-center gap-1 rounded-full bg-secondary px-2 py-0.5 text-xs font-medium text-muted-foreground"
                                        >
                                          <Mail className="h-3 w-3" aria-hidden />
                                          {t(`${k}.badge.link_${u.setup_link_purpose === "reset" ? "reset" : "invite"}`)}
                                        </span>
                                      )
                                    )}
                                  </div>
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
                                {!isSsoUser(u) && (smtpMissing || !!u.email) && (
                                  <IconAction
                                    label={t(`${k}.row.${smtpMissing ? "issue_temp" : u.has_password ? "send_reset" : "resend_invite"}`, { name })}
                                    onClick={() => linkBusy !== u.id && void sendLink(u)}
                                  >
                                    {linkBusy === u.id ? (
                                      <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                                    ) : smtpMissing ? (
                                      <RectangleEllipsis className="h-4 w-4" aria-hidden />
                                    ) : (
                                      <Mail className="h-4 w-4" aria-hidden />
                                    )}
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

        {tab === "migration" && showMigration && (
          <section aria-labelledby="users-mig-title" className="flex flex-col gap-4">
            <div>
              <h2 id="users-mig-title" className="text-lg font-semibold tracking-[-0.015em]">
                {t(`${k}.migration.title`)}
              </h2>
              <p className="mt-1 max-w-[60ch] text-sm text-muted-foreground">{t(`${k}.migration.subtitle`)}</p>
            </div>
            <MigrationUsers onChanged={() => void loadUsers()} />
          </section>
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
              {/* "Nuovi account" lives under the Microsoft/Google tabs: only SSO creates accounts on its own. */}
              <SsoMigrationPanel
                onManage={showMigration ? () => setTab("migration") : undefined}
                onModeChanged={() => void loadUsers()}
                onToast={setToast}
              />
            </section>

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

      {formUser && (formUser !== "new" || canCreate) && (
        <UserFormDialog
          user={formUser === "new" ? null : (users.find((u) => u.id === formUser.id) ?? formUser)}
          busy={saving}
          linkBusy={formUser !== "new" && linkBusy === formUser.id}
          smtpMissing={smtpMissing}
          t={t}
          onSubmit={saveUser}
          onSendLink={(u) => void sendLink(u)}
          onClose={() => !saving && setFormUser(null)}
        />
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

      {tempResetUser && (
        <TempResetDialog user={tempResetUser} busy={linkBusy === tempResetUser.id} t={t} onConfirm={() => void sendLink(tempResetUser)} onClose={() => setTempResetUser(null)} />
      )}
      {tempPasswords && <TempPasswordsDialog passwords={tempPasswords} t={t} onClose={() => setTempPasswords(null)} />}
      {resetUser && <ResetDialog user={resetUser} busy={saving} t={t} onConfirm={resetTwoFactor} onClose={() => !saving && setResetUser(null)} />}

      {deleteUser && (
        <DeleteDialog name={deleteUser.identifier} busy={saving} ns={`${k}.delete`} t={t} onConfirm={removeUser} onClose={() => !saving && setDeleteUser(null)} />
      )}

      <PageToast toast={toast} onDismiss={() => setToast(null)} />
    </div>
  );
}
