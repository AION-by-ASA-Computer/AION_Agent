"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Check, Copy, Loader2, Plus, RefreshCw, ShieldOff } from "lucide-react";

import {
  ApiKeyError,
  createApiKey,
  listApiKeys,
  revokeApiKey,
  type ApiKeyItem,
  type ApiKeyPolicy,
  type ApiKeysResponse,
  type CreatedApiKey,
} from "@/lib/api/api-keys";
import { useStoredToken, useStoredUserId } from "@/lib/auth/use-stored-auth";
import { cn } from "@/lib/cn";
import { getLocale } from "@/lib/i18n/i18n-store";
import { useT } from "@/lib/i18n/use-t";
import { Select } from "./Select";
import {
  Badge,
  Dialog,
  Group,
  Mono,
  Note,
  SectionHead,
  dangerBtn,
  ghostBtn,
  inputCls,
  outlineBtn,
  solidBtn,
} from "./ui";

type TFn = ReturnType<typeof useT>;
type ToastFn = (message: string, type?: "success" | "error") => void;

const EXPIRY_PRESETS = [7, 30, 90, 180, 365];
const DEFAULT_EXPIRY_CAP = 90;

/** Scope id -> i18n key segment (dots/colons are not usable in dotted i18n paths). */
const SCOPE_I18N: Record<string, string> = {
  chat: "chat",
  "conversations:read": "conversations_read",
  "conversations:write": "conversations_write",
  "files:read": "files_read",
  "files:write": "files_write",
};

function scopeLabel(scope: string, t: TFn): string {
  const k = SCOPE_I18N[scope];
  return k ? t(`settings.api_keys.scope.${k}.label`) : scope;
}

function scopeDesc(scope: string, t: TFn): string | null {
  const k = SCOPE_I18N[scope];
  return k ? t(`settings.api_keys.scope.${k}.desc`) : null;
}

function errorMessage(err: unknown, t: TFn): string {
  if (err instanceof ApiKeyError) {
    switch (err.code) {
      case "api_keys_disabled":
        return t("settings.api_keys.err.disabled");
      case "api_key_quota_exceeded": {
        const max = err.details?.max_keys;
        return typeof max === "number"
          ? t("settings.api_keys.err.quota", { max })
          : t("settings.api_keys.err.quota_generic");
      }
      case "invalid_scopes":
        return t("settings.api_keys.err.invalid_scopes");
      case "invalid_expiration":
        return t("settings.api_keys.err.invalid_expiration");
      case "user_token_required":
        return t("settings.api_keys.err.user_token_required");
      default:
        if (err.status === 404) return t("settings.api_keys.err.not_found");
        return err.message || t("settings.api_keys.err.generic");
    }
  }
  if (err instanceof Error && err.message) return err.message;
  return t("settings.api_keys.err.generic");
}

function formatDate(iso: string | null, withTime = false): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const locale = getLocale();
  return withTime
    ? d.toLocaleString(locale, { dateStyle: "medium", timeStyle: "short" })
    : d.toLocaleDateString(locale, { dateStyle: "medium" });
}

function expiryOptions(maxTtlDays: number): number[] {
  const max = Math.max(1, Math.floor(maxTtlDays || 0));
  const opts = EXPIRY_PRESETS.filter((d) => d <= max);
  if (!opts.includes(max)) opts.push(max);
  return opts.sort((a, b) => a - b);
}

function defaultExpiry(options: number[]): number {
  const capped = options.filter((d) => d <= DEFAULT_EXPIRY_CAP);
  return capped.length ? capped[capped.length - 1] : options[0];
}

async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    /* fall through to legacy path */
  }
  try {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(ta);
    return ok;
  } catch {
    return false;
  }
}

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; data: ApiKeysResponse };

export function ApiKeysSection({ onToast }: { onToast?: ToastFn }) {
  const t = useT();
  const userId = useStoredUserId();
  const token = useStoredToken();

  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [reloadKey, setReloadKey] = useState(0);
  const [showCreate, setShowCreate] = useState(false);
  const [created, setCreated] = useState<CreatedApiKey | null>(null);
  const [revokeTarget, setRevokeTarget] = useState<ApiKeyItem | null>(null);
  const [revoking, setRevoking] = useState(false);
  const [inlineError, setInlineError] = useState<string | null>(null);

  const notify = useCallback<ToastFn>(
    (message, type = "success") => {
      if (onToast) onToast(message, type);
      else if (type === "error") setInlineError(message);
    },
    [onToast],
  );

  useEffect(() => {
    let cancelled = false;
    listApiKeys(userId, token)
      .then((data) => {
        if (!cancelled) setState({ status: "ready", data });
      })
      .catch((err: unknown) => {
        if (!cancelled) setState({ status: "error", message: errorMessage(err, t) });
      });
    return () => {
      cancelled = true;
    };
    // `t` is a stable module-level function; reloadKey triggers refreshes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId, token, reloadKey]);

  const refresh = useCallback(() => setReloadKey((k) => k + 1), []);

  const retry = () => {
    setState({ status: "loading" });
    refresh();
  };

  const handleCreated = (key: CreatedApiKey) => {
    setShowCreate(false);
    setCreated(key);
    setInlineError(null);
    notify(t("settings.api_keys.toast.created"));
    refresh();
  };

  const handleRevoke = async () => {
    if (!revokeTarget) return;
    setRevoking(true);
    try {
      await revokeApiKey(userId, token, revokeTarget.id);
      setRevokeTarget(null);
      setInlineError(null);
      notify(t("settings.api_keys.toast.revoked"));
      refresh();
    } catch (err) {
      setRevokeTarget(null);
      notify(errorMessage(err, t), "error");
    } finally {
      setRevoking(false);
    }
  };

  const ready = state.status === "ready" ? state.data : null;
  const quotaReached = ready ? ready.policy.active_count >= ready.policy.max_keys : false;

  const head = (
    <SectionHead
      title={t("settings.api_keys.title")}
      description={t("settings.api_keys.desc")}
      action={
        ready?.policy.enabled ? (
          <button
            type="button"
            onClick={() => {
              setInlineError(null);
              setShowCreate(true);
            }}
            disabled={quotaReached}
            title={quotaReached ? t("settings.api_keys.quota_hint") : undefined}
            className={solidBtn}
          >
            <Plus className="h-3.5 w-3.5" aria-hidden />
            {t("settings.api_keys.new_key")}
          </button>
        ) : null
      }
    />
  );

  if (state.status === "loading") {
    return (
      <>
        {head}
        <p className="flex items-center gap-2 py-8 text-sm text-muted-foreground" role="status">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
          {t("settings.api_keys.loading")}
        </p>
      </>
    );
  }

  if (state.status === "error") {
    return (
      <>
        {head}
        <Note tone="error">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <span>{state.message}</span>
            <button type="button" onClick={retry} className={cn(outlineBtn, "text-foreground")}>
              <RefreshCw className="h-3.5 w-3.5" aria-hidden />
              {t("settings.api_keys.retry")}
            </button>
          </div>
        </Note>
      </>
    );
  }

  const { policy, keys } = state.data;

  if (!policy.enabled) {
    return (
      <>
        {head}
        <Note>{t("settings.api_keys.disabled")}</Note>
      </>
    );
  }

  return (
    <>
      {head}

      {created ? <SecretBanner created={created} onDismiss={() => setCreated(null)} /> : null}
      {inlineError ? <Note tone="error">{inlineError}</Note> : null}

      <Group
        title={t("settings.api_keys.list_title")}
        description={quotaReached ? t("settings.api_keys.quota_hint") : undefined}
        action={
          <span className="text-xs tabular-nums text-muted-foreground">
            {t("settings.api_keys.counter", { active: policy.active_count, max: policy.max_keys })}
          </span>
        }
      >
        {keys.length === 0 ? (
          <p className="px-5 py-10 text-center text-sm text-muted-foreground">{t("settings.api_keys.empty")}</p>
        ) : (
          <ul className="divide-y divide-border/40">
            {keys.map((k) => (
              <ApiKeyRow key={k.id} item={k} onRevoke={() => setRevokeTarget(k)} />
            ))}
          </ul>
        )}
      </Group>

      <Group title={t("settings.api_keys.usage_title")} description={t("settings.api_keys.usage_desc")}>
        <div className="flex flex-col gap-2 px-5 py-4">
          {["X-Api-Key: <key>", "Authorization: Bearer <key>"].map((line) => (
            <code
              key={line}
              className="block overflow-x-auto whitespace-nowrap rounded-xl bg-secondary/60 px-3.5 py-2.5 font-mono text-[0.893rem] text-foreground/90"
            >
              {line}
            </code>
          ))}
        </div>
      </Group>

      {showCreate ? (
        <CreateApiKeyDialog
          policy={policy}
          userId={userId}
          token={token}
          onClose={() => setShowCreate(false)}
          onCreated={handleCreated}
        />
      ) : null}

      {revokeTarget ? (
        <RevokeApiKeyDialog
          item={revokeTarget}
          revoking={revoking}
          onClose={() => {
            if (!revoking) setRevokeTarget(null);
          }}
          onConfirm={handleRevoke}
        />
      ) : null}
    </>
  );
}

const STATUS_TONE: Record<ApiKeyItem["status"], "success" | "warning" | "danger"> = {
  active: "success",
  expired: "warning",
  revoked: "danger",
};

function ApiKeyRow({ item, onRevoke }: { item: ApiKeyItem; onRevoke: () => void }) {
  const t = useT();
  const inactive = item.status !== "active";
  return (
    <li className="px-5 py-4">
      <div className="flex items-start gap-3">
        <div className={cn("min-w-0 flex-1", inactive && "opacity-70")}>
          <div className="flex flex-wrap items-center gap-2">
            <span className="truncate text-sm font-medium">{item.name}</span>
            <Badge tone={STATUS_TONE[item.status] ?? "neutral"}>{t(`settings.api_keys.status.${item.status}`)}</Badge>
          </div>
          <Mono className="mt-1 block truncate text-muted-foreground">aion_{item.prefix}_…</Mono>
        </div>
        {item.status === "active" ? (
          <button
            type="button"
            onClick={onRevoke}
            className={cn(ghostBtn, "-mr-2 h-8 shrink-0 text-destructive hover:bg-destructive/10 hover:text-destructive")}
          >
            <ShieldOff className="h-3.5 w-3.5" aria-hidden />
            {t("settings.api_keys.revoke")}
          </button>
        ) : null}
      </div>

      <div className={cn(inactive && "opacity-70")}>
        {item.scopes.length ? (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {item.scopes.map((s) => (
              <span key={s} title={s}>
                <Badge>{scopeLabel(s, t)}</Badge>
              </span>
            ))}
          </div>
        ) : null}

        <dl className="mt-3 grid grid-cols-1 gap-x-6 gap-y-1.5 text-xs sm:grid-cols-3">
          <div className="flex gap-1.5 sm:block">
            <dt className="text-muted-foreground">{t("settings.api_keys.created")}</dt>
            <dd className="sm:mt-0.5">{formatDate(item.created_at)}</dd>
          </div>
          <div className="flex gap-1.5 sm:block">
            <dt className="text-muted-foreground">
              {item.status === "revoked" ? t("settings.api_keys.revoked_on") : t("settings.api_keys.expires")}
            </dt>
            <dd className="sm:mt-0.5">
              {item.status === "revoked"
                ? formatDate(item.revoked_at)
                : item.expires_at
                  ? formatDate(item.expires_at)
                  : t("settings.api_keys.no_expiry")}
            </dd>
          </div>
          <div className="flex gap-1.5 sm:block">
            <dt className="text-muted-foreground">{t("settings.api_keys.last_used")}</dt>
            <dd className="sm:mt-0.5">
              {item.last_used_at ? formatDate(item.last_used_at, true) : t("settings.api_keys.never")}
            </dd>
          </div>
        </dl>
      </div>
    </li>
  );
}

function SecretBanner({ created, onDismiss }: { created: CreatedApiKey; onDismiss: () => void }) {
  const t = useT();
  const [copied, setCopied] = useState(false);
  const [copyFailed, setCopyFailed] = useState(false);

  const onCopy = async () => {
    const ok = await copyText(created.key);
    setCopied(ok);
    setCopyFailed(!ok);
    if (ok) window.setTimeout(() => setCopied(false), 2000);
  };

  return (
    <Group
      tone="warn"
      title={t("settings.api_keys.secret.title", { name: created.name })}
      description={t("settings.api_keys.secret.warning")}
      footer={
        <button type="button" onClick={onDismiss} className={outlineBtn}>
          {t("settings.api_keys.secret.dismiss")}
        </button>
      }
    >
      <div className="px-5 py-4">
        <div className="flex flex-col gap-2 sm:flex-row">
          <input
            type="text"
            readOnly
            value={created.key}
            onFocus={(e) => e.currentTarget.select()}
            aria-label={t("settings.api_keys.secret.key_label")}
            className={cn(inputCls, "h-9 py-0 font-mono text-[0.893rem]")}
          />
          <button type="button" onClick={() => void onCopy()} className={cn(solidBtn, "shrink-0 justify-center")}>
            {copied ? <Check className="h-3.5 w-3.5" aria-hidden /> : <Copy className="h-3.5 w-3.5" aria-hidden />}
            {copied ? t("settings.api_keys.secret.copied") : t("settings.api_keys.secret.copy")}
          </button>
        </div>
        {copyFailed ? (
          <p className="mt-2 text-xs text-destructive" role="alert">
            {t("settings.api_keys.secret.copy_failed")}
          </p>
        ) : null}
      </div>
    </Group>
  );
}

function CreateApiKeyDialog({
  policy,
  userId,
  token,
  onClose,
  onCreated,
}: {
  policy: ApiKeyPolicy;
  userId: string;
  token: string | null;
  onClose: () => void;
  onCreated: (key: CreatedApiKey) => void;
}) {
  const t = useT();
  const options = useMemo(() => expiryOptions(policy.max_ttl_days), [policy.max_ttl_days]);
  const [name, setName] = useState("");
  const [scopes, setScopes] = useState<string[]>(() =>
    policy.allowed_scopes.includes("chat") ? ["chat"] : [],
  );
  const [days, setDays] = useState<number>(() => defaultExpiry(options));
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const close = useCallback(() => {
    if (!submitting) onClose();
  }, [submitting, onClose]);

  const trimmed = name.trim();
  const canSubmit = trimmed.length > 0 && scopes.length > 0 && !submitting;

  const toggleScope = (scope: string, on: boolean) => {
    setScopes((prev) => (on ? [...prev, scope] : prev.filter((s) => s !== scope)));
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);
    try {
      const created = await createApiKey(userId, token, {
        name: trimmed,
        // keep server order for a stable display
        scopes: policy.allowed_scopes.filter((s) => scopes.includes(s)),
        expires_in_days: days,
      });
      onCreated(created);
    } catch (err) {
      setError(errorMessage(err, t));
      setSubmitting(false);
    }
  };

  return (
    <Dialog
      title={t("settings.api_keys.create.title")}
      description={t("settings.api_keys.create.subtitle")}
      closeLabel={t("settings.api_keys.create.cancel")}
      onClose={close}
    >
      <form className="flex flex-col gap-5 pt-3" onSubmit={submit}>
        <label className="flex flex-col gap-1.5">
          <span className="text-sm font-medium">{t("settings.api_keys.create.name_label")}</span>
          <input
            type="text"
            autoFocus
            maxLength={100}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={t("settings.api_keys.create.name_placeholder")}
            className={inputCls}
          />
          <span className="text-xs text-muted-foreground">{t("settings.api_keys.create.name_hint")}</span>
        </label>

        <fieldset className="flex flex-col gap-1.5">
          <legend className="text-sm font-medium">{t("settings.api_keys.create.scopes_label")}</legend>
          <p className="text-xs text-muted-foreground">{t("settings.api_keys.create.scopes_hint")}</p>
          <div className="mt-1 overflow-hidden rounded-xl border border-border">
            {policy.allowed_scopes.map((scope, i) => {
              const checked = scopes.includes(scope);
              const desc = scopeDesc(scope, t);
              return (
                <label
                  key={scope}
                  className={cn(
                    "flex cursor-pointer items-start gap-3 px-3.5 py-3 transition-colors hover:bg-secondary/50",
                    i > 0 && "border-t border-border/60",
                  )}
                >
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={(e) => toggleScope(scope, e.target.checked)}
                    className="focus-ring mt-0.5 h-4 w-4 shrink-0 cursor-pointer accent-[hsl(var(--foreground))]"
                  />
                  <span className="min-w-0">
                    <span className="flex flex-wrap items-baseline gap-x-2">
                      <span className="text-sm font-medium">{scopeLabel(scope, t)}</span>
                      <Mono className="text-muted-foreground">{scope}</Mono>
                    </span>
                    {desc ? <span className="mt-0.5 block text-xs text-muted-foreground">{desc}</span> : null}
                  </span>
                </label>
              );
            })}
          </div>
        </fieldset>

        <div className="flex flex-col gap-1.5">
          <span className="text-sm font-medium">
            {t("settings.api_keys.create.expiry_label")}
          </span>
          <Select
            aria-label={t("settings.api_keys.create.expiry_label")}
            value={String(days)}
            onChange={(v) => setDays(Number(v))}
            options={options.map((d) => ({
              value: String(d),
              label:
                d === 1
                  ? t("settings.api_keys.create.expiry_one_day")
                  : t("settings.api_keys.create.expiry_days", { days: d }),
            }))}
          />
          <span className="text-xs text-muted-foreground">
            {t("settings.api_keys.create.expiry_hint", { max: policy.max_ttl_days })}
          </span>
        </div>

        {error ? <Note tone="error">{error}</Note> : null}

        <div className="flex justify-end gap-2 pt-1">
          <button type="button" onClick={close} disabled={submitting} className={ghostBtn}>
            {t("settings.api_keys.create.cancel")}
          </button>
          <button type="submit" disabled={!canSubmit} className={solidBtn}>
            {submitting ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <Plus className="h-3.5 w-3.5" aria-hidden />}
            {submitting ? t("settings.api_keys.create.creating") : t("settings.api_keys.create.submit")}
          </button>
        </div>
      </form>
    </Dialog>
  );
}

function RevokeApiKeyDialog({
  item,
  revoking,
  onClose,
  onConfirm,
}: {
  item: ApiKeyItem;
  revoking: boolean;
  onClose: () => void;
  onConfirm: () => Promise<void> | void;
}) {
  const t = useT();

  return (
    <Dialog
      title={t("settings.api_keys.revoke_dialog.title")}
      description={t("settings.api_keys.revoke_dialog.subtitle")}
      closeLabel={t("settings.api_keys.create.cancel")}
      onClose={onClose}
    >
      <div className="flex flex-col gap-4 pt-3">
        <p className="text-sm text-muted-foreground">
          {t("settings.api_keys.revoke_dialog.desc")}{" "}
          <strong className="mx-0.5 inline-block max-w-full break-all rounded-md bg-destructive/12 px-1.5 py-0.5 align-baseline font-mono text-[0.929rem] font-semibold text-destructive">
            {item.name}
          </strong>
          ?
        </p>

        <dl className="flex flex-col gap-2 rounded-xl bg-secondary/60 px-3.5 py-3 text-sm">
          <div className="flex items-center justify-between gap-3">
            <dt className="text-muted-foreground">{t("settings.api_keys.revoke_dialog.key")}</dt>
            <dd className="truncate">
              <Mono>aion_{item.prefix}_…</Mono>
            </dd>
          </div>
          <div className="flex items-center justify-between gap-3">
            <dt className="text-muted-foreground">{t("settings.api_keys.last_used")}</dt>
            <dd>{item.last_used_at ? formatDate(item.last_used_at, true) : t("settings.api_keys.never")}</dd>
          </div>
        </dl>

        <Note tone="warn">{t("settings.api_keys.revoke_dialog.warning")}</Note>

        <div className="flex justify-end gap-2 pt-1">
          <button type="button" onClick={onClose} disabled={revoking} className={ghostBtn} autoFocus>
            {t("settings.api_keys.create.cancel")}
          </button>
          <button type="button" onClick={() => void onConfirm()} disabled={revoking} className={dangerBtn}>
            {revoking ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <ShieldOff className="h-3.5 w-3.5" aria-hidden />}
            {revoking ? t("settings.api_keys.revoke_dialog.revoking") : t("settings.api_keys.revoke_dialog.confirm")}
          </button>
        </div>
      </div>
    </Dialog>
  );
}
