"use client";

/**
 * API keys of one service account: list, create, revoke.
 *
 * Service accounts have no password, SSO or 2FA, so these keys are their only
 * way to authenticate. The panel loads `GET /admin/service-accounts/{id}/keys`
 * (keys + policy), creates keys within the policy (scopes from
 * `allowed_scopes`, lifetime up to `max_ttl_days`, at most `max_keys` active)
 * and revokes them. A created key's secret is handed to `NewKeyDialog`, the
 * only place it is ever shown.
 *
 * Built on the themed `Dialog` rather than `components/ui/SlideOver`, whose
 * colours are hard-coded for the dark theme.
 */

import { useCallback, useEffect, useState } from "react";
import { Ban, KeyRound, Loader2, Plus, TriangleAlert } from "lucide-react";
import { apiBase } from "@/lib/api";
import { apiFetch } from "@/lib/api/headers";
import { cn } from "@/lib/cn";
import { Dialog } from "@/components/profiles/Dialog";
import { dangerBtn, ghostBtn, inputCls, outlineBtn, solidBtn } from "@/components/ui/classes";
import type { ToastState } from "@/components/PageToast";
import { NewKeyDialog } from "./NewKeyDialog";
import {
  DEFAULT_SCOPES,
  Field,
  StatusBadge,
  formatDate,
  k,
  nameOf,
  parseInRange,
  readError,
  scopeLabel,
  type CreatedKey,
  type KeyPolicy,
  type ServiceAccount,
  type ServiceKey,
  type T,
} from "./shared";

/** Default lifetime offered for a new key, capped by the account's maximum. */
const DEFAULT_KEY_DAYS = 30;

const STATUS_TONE: Record<ServiceKey["status"], "success" | "muted" | "danger"> = {
  active: "success",
  expired: "muted",
  revoked: "danger",
};

/**
 * @param account   Account whose keys are managed.
 * @param onChanged Called after a key is created or revoked, so the page refreshes its active-key counts.
 * @param onToast   Page-level toast for outcomes and errors.
 */
export function KeysDialog({
  account,
  t,
  onChanged,
  onToast,
  onClose,
}: {
  account: ServiceAccount;
  t: T;
  onChanged: () => void;
  onToast: (toast: ToastState) => void;
  onClose: () => void;
}) {
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [policy, setPolicy] = useState<KeyPolicy | null>(null);
  const [keys, setKeys] = useState<ServiceKey[]>([]);
  const [creating, setCreating] = useState(false);
  const [busy, setBusy] = useState(false);
  const [confirmRevoke, setConfirmRevoke] = useState<string | null>(null);
  const [created, setCreated] = useState<CreatedKey | null>(null);

  const base = `${apiBase()}/admin/service-accounts/${account.id}/keys`;

  const load = useCallback(async () => {
    try {
      const res = await apiFetch(base);
      if (!res.ok) throw new Error((await readError(res)).message);
      const data = await res.json();
      setPolicy(data.policy ?? null);
      setKeys(data.keys ?? []);
      setState("ready");
    } catch (err) {
      setState("error");
      onToast({ message: t(`${k}.toast.keys_load_failed`, { error: err instanceof Error ? err.message : String(err) }), variant: "error" });
    }
  }, [base, onToast, t]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch on mount
    void load();
  }, [load]);

  const maxKeys = policy?.max_keys ?? account.max_api_keys;
  const activeCount = policy?.active_count ?? keys.filter((x) => x.status === "active").length;
  const maxDays = policy?.max_ttl_days ?? account.api_key_max_ttl_days;
  const quotaFull = activeCount >= maxKeys;
  // `enabled` is false while the account is disabled: its keys do not authenticate, so no new ones either.
  const accountOff = policy ? !policy.enabled : account.disabled;
  const canCreate = state === "ready" && !quotaFull && !accountOff;

  /** Creates a key, then reveals its secret once. Returns false to keep the form open on errors. */
  const createKey = async (name: string, scopes: string[], days: number): Promise<boolean> => {
    setBusy(true);
    try {
      const res = await apiFetch(base, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, scopes, expires_in_days: days }),
      });
      if (!res.ok) {
        const err = await readError(res);
        const known = ["invalid_scopes", "invalid_expiration", "api_key_quota_exceeded"].includes(err.code);
        onToast({
          message: known ? t(`${k}.errors.${err.code}`, { days: String(err.detail?.max_ttl_days ?? maxDays), max: maxKeys }) : t(`${k}.toast.key_create_failed`, { error: err.message }),
          variant: "error",
        });
        if (err.code === "api_key_quota_exceeded") void load();
        return false;
      }
      setCreated(await res.json());
      setCreating(false);
      void load();
      onChanged();
      return true;
    } catch (err) {
      onToast({ message: t(`${k}.toast.key_create_failed`, { error: err instanceof Error ? err.message : String(err) }), variant: "error" });
      return false;
    } finally {
      setBusy(false);
    }
  };

  /** Revokes a key right away: integrations using it start getting 401. */
  const revokeKey = async (key: ServiceKey) => {
    setBusy(true);
    try {
      const res = await apiFetch(`${base}/${key.id}`, { method: "DELETE" });
      if (!res.ok) throw new Error((await readError(res)).message);
      setConfirmRevoke(null);
      onToast({ message: t(`${k}.toast.key_revoked`, { name: key.name }), variant: "success" });
      void load();
      onChanged();
    } catch (err) {
      onToast({ message: t(`${k}.toast.key_revoke_failed`, { error: err instanceof Error ? err.message : String(err) }), variant: "error" });
    } finally {
      setBusy(false);
    }
  };

  // Active keys first, then the most recent.
  const sorted = [...keys].sort((a, b) => (a.status === "active" ? 0 : 1) - (b.status === "active" ? 0 : 1) || (b.created_at ?? "").localeCompare(a.created_at ?? ""));

  return (
    <>
      <Dialog title={t(`${k}.keys.title`, { name: nameOf(account) })} closeLabel={t(`${k}.keys.close`)} onClose={onClose} className="max-w-3xl">
        <div className="flex flex-col gap-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-sm text-muted-foreground">
              <span className="font-mono text-foreground">{account.identifier}</span>
              {" · "}
              {t(`${k}.keys.policy`, { active: activeCount, max: maxKeys, days: maxDays })}
            </p>
            {!creating && (
              <button type="button" className={solidBtn} disabled={!canCreate} onClick={() => setCreating(true)}>
                <Plus className="h-4 w-4" aria-hidden />
                {t(`${k}.keys.new`)}
              </button>
            )}
          </div>

          {state === "ready" && (accountOff || quotaFull) && (
            <p role="status" className="flex items-start gap-2 rounded-xl bg-warning/10 px-3 py-2 text-xs text-warning">
              <TriangleAlert className="mt-px h-3.5 w-3.5 shrink-0" aria-hidden />
              {accountOff ? t(`${k}.keys.account_disabled`) : t(`${k}.keys.quota_full`, { max: maxKeys })}
            </p>
          )}

          {creating && (
            <NewKeyForm
              allowedScopes={policy?.allowed_scopes?.length ? policy.allowed_scopes : DEFAULT_SCOPES}
              maxDays={maxDays}
              busy={busy}
              t={t}
              onSubmit={createKey}
              onCancel={() => setCreating(false)}
            />
          )}

          {state === "loading" && (
            <div className="flex items-center gap-2 py-8 text-sm text-muted-foreground" role="status">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
              {t(`${k}.loading`)}
            </div>
          )}

          {state === "error" && (
            <div className="flex flex-col items-start gap-3 py-6">
              <p className="text-sm text-destructive">{t(`${k}.keys.error`)}</p>
              <button
                type="button"
                className={outlineBtn}
                onClick={() => {
                  setState("loading");
                  void load();
                }}
              >
                {t(`${k}.retry`)}
              </button>
            </div>
          )}

          {state === "ready" && keys.length === 0 && !creating && (
            <div className="flex flex-col items-center rounded-2xl border border-dashed border-border px-6 py-10 text-center">
              <KeyRound className="h-5 w-5 text-muted-foreground" aria-hidden />
              <p className="mt-2 text-sm font-medium">{t(`${k}.keys.empty_title`)}</p>
              <p className="mt-1 max-w-[44ch] text-xs text-muted-foreground">{t(`${k}.keys.empty_body`)}</p>
            </div>
          )}

          {state === "ready" && keys.length > 0 && (
            <ul className="flex flex-col rounded-2xl border border-border/70">
              {sorted.map((key) => (
                <li key={key.id} className={cn("flex flex-col gap-2 border-b border-border/40 px-4 py-3 last:border-b-0", key.status !== "active" && "opacity-70")}>
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
                    <span className="min-w-0 truncate text-sm font-medium">{key.name}</span>
                    <code className="rounded-md bg-secondary px-1.5 py-0.5 font-mono text-xs text-muted-foreground">aion_{key.prefix}_…</code>
                    <StatusBadge tone={STATUS_TONE[key.status]} label={t(`${k}.keys.status.${key.status}`)} />
                    <div className="ml-auto flex items-center gap-2">
                      {key.status === "active" &&
                        (confirmRevoke === key.id ? (
                          <>
                            <span className="text-xs text-muted-foreground">{t(`${k}.keys.revoke_confirm`)}</span>
                            <button type="button" className={ghostBtn} onClick={() => setConfirmRevoke(null)}>
                              {t(`${k}.form.cancel`)}
                            </button>
                            <button type="button" className={dangerBtn} disabled={busy} onClick={() => void revokeKey(key)} autoFocus>
                              {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <Ban className="h-3.5 w-3.5" aria-hidden />}
                              {t(`${k}.keys.revoke`)}
                            </button>
                          </>
                        ) : (
                          <button type="button" className={ghostBtn} onClick={() => setConfirmRevoke(key.id)} aria-label={t(`${k}.keys.revoke_aria`, { name: key.name })}>
                            <Ban className="h-3.5 w-3.5" aria-hidden />
                            {t(`${k}.keys.revoke`)}
                          </button>
                        ))}
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-1">
                    {key.scopes.map((s) => (
                      <span key={s} title={s} className="rounded-full bg-secondary px-2 py-0.5 text-xs text-muted-foreground">
                        {scopeLabel(t, s)}
                      </span>
                    ))}
                  </div>
                  <p className="flex flex-wrap gap-x-4 gap-y-0.5 text-xs tabular-nums text-muted-foreground">
                    {key.created_at && <span>{t(`${k}.keys.created_on`, { date: formatDate(key.created_at) })}</span>}
                    {key.status === "revoked" && key.revoked_at ? (
                      <span>{t(`${k}.keys.revoked_on`, { date: formatDate(key.revoked_at) })}</span>
                    ) : (
                      key.expires_at && <span>{t(`${k}.keys.${key.status === "expired" ? "expired_on" : "expires_on"}`, { date: formatDate(key.expires_at) })}</span>
                    )}
                    <span>{key.last_used_at ? t(`${k}.keys.last_used`, { date: formatDate(key.last_used_at) }) : t(`${k}.keys.never_used`)}</span>
                  </p>
                </li>
              ))}
            </ul>
          )}
        </div>
      </Dialog>

      {created && <NewKeyDialog created={created} t={t} onClose={() => setCreated(null)} />}
    </>
  );
}

/**
 * Inline form for a new key: name, scopes (checkboxes over the allowed ones)
 * and lifetime in days, bounded by the account's maximum.
 */
function NewKeyForm({
  allowedScopes,
  maxDays,
  busy,
  t,
  onSubmit,
  onCancel,
}: {
  allowedScopes: string[];
  maxDays: number;
  busy: boolean;
  t: T;
  onSubmit: (name: string, scopes: string[], days: number) => Promise<boolean>;
  onCancel: () => void;
}) {
  const [name, setName] = useState("");
  // Start from the narrowest useful grant: chatting only.
  const [scopes, setScopes] = useState<string[]>(allowedScopes.includes("chat") ? ["chat"] : allowedScopes.slice(0, 1));
  const [days, setDays] = useState(String(Math.min(DEFAULT_KEY_DAYS, maxDays)));

  const range = { min: 1, max: maxDays };
  const daysValue = parseInRange(days, range);
  const canSubmit = !busy && !!name.trim() && scopes.length > 0 && daysValue !== null;
  const toggle = (s: string) => setScopes((cur) => (cur.includes(s) ? cur.filter((x) => x !== s) : [...cur, s]));
  // Form opening time, captured once (render must stay pure) to preview the expiry date.
  const [openedAt] = useState(() => Date.now());
  // Expected expiry date, so the admin sees what "N days" means.
  const expiresPreview = daysValue !== null ? formatDate(new Date(openedAt + daysValue * 86_400_000).toISOString()) : null;

  return (
    <form
      className="flex flex-col gap-4 rounded-2xl border border-border bg-secondary/30 p-4"
      onSubmit={(e) => {
        e.preventDefault();
        if (canSubmit) void onSubmit(name.trim(), scopes, daysValue!);
      }}
    >
      <div className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_11rem]">
        <Field label={t(`${k}.keys.name`)} htmlFor="svc-key-name" hint={t(`${k}.keys.name_hint`)} t={t}>
          <input
            id="svc-key-name"
            autoFocus
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={t(`${k}.keys.name_placeholder`)}
            autoComplete="off"
            maxLength={80}
            required
            className={cn(inputCls, "bg-card")}
          />
        </Field>
        <Field
          label={t(`${k}.keys.days`)}
          htmlFor="svc-key-days"
          hint={expiresPreview ? t(`${k}.keys.days_hint`, { max: maxDays, date: expiresPreview }) : undefined}
          error={daysValue === null ? t(`${k}.form.range_error`, { min: 1, max: maxDays }) : undefined}
          t={t}
        >
          <input
            id="svc-key-days"
            type="number"
            inputMode="numeric"
            min={1}
            max={maxDays}
            step={1}
            value={days}
            onChange={(e) => setDays(e.target.value)}
            aria-invalid={daysValue === null}
            aria-describedby="svc-key-days-hint"
            className={cn(inputCls, "bg-card tabular-nums", daysValue === null && "border-destructive/60")}
          />
        </Field>
      </div>

      <fieldset className="flex flex-col gap-2">
        <legend className="mb-1.5 text-sm font-medium">{t(`${k}.keys.scopes`)}</legend>
        <div className="grid gap-1.5 sm:grid-cols-2">
          {allowedScopes.map((s) => {
            const on = scopes.includes(s);
            return (
              <label
                key={s}
                className={cn("flex cursor-pointer items-start gap-2.5 rounded-xl border px-3 py-2 transition-colors", on ? "border-foreground/40 bg-card" : "border-border hover:bg-card/60")}
              >
                <input type="checkbox" checked={on} onChange={() => toggle(s)} className="focus-ring mt-0.5 h-4 w-4 shrink-0 accent-foreground" />
                <span className="min-w-0">
                  <span className="block text-sm">{scopeLabel(t, s)}</span>
                  <span className="block font-mono text-xs text-muted-foreground">{s}</span>
                </span>
              </label>
            );
          })}
        </div>
        {scopes.length === 0 && <span className="text-xs text-destructive">{t(`${k}.keys.scopes_required`)}</span>}
      </fieldset>

      <div className="flex justify-end gap-2">
        <button type="button" className={ghostBtn} onClick={onCancel}>
          {t(`${k}.form.cancel`)}
        </button>
        <button type="submit" className={solidBtn} disabled={!canSubmit}>
          {busy && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />}
          {t(`${k}.keys.create`)}
        </button>
      </div>
    </form>
  );
}
