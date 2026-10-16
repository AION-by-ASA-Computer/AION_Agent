"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Check, Copy, KeyRound, Loader2, Plus, Trash2, X } from "lucide-react";
import { apiFetch } from "@/lib/api/headers";
import { apiBase } from "@/lib/api";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";
import { PageToast, type ToastState } from "@/components/PageToast";
import { Dialog } from "@/components/profiles/Dialog";
import { DeleteDialog } from "@/components/ui/ConfirmDialogs";
import { SearchField } from "@/components/ui/SearchField";
import { fullWhen, shortWhen, toMs } from "@/components/conversations/format";
import { ghostBtn, inputCls, outlineBtn, solidBtn } from "@/components/ui/classes";

type ApiKey = {
  id: string;
  name: string;
  prefix: string;
  tenant_id?: string | null;
  scopes: string[];
  last_used_at?: string | null;
};

const SCOPES = [
  "conversations:read",
  "conversations:write",
  "chat",
  "chat:scoped",
  "files:read",
  "files:write",
  "admin",
] as const;

const DEFAULT_SCOPES = ["chat:scoped"];
const GRID = "md:grid-cols-[minmax(0,1.4fr)_minmax(0,2fr)_7rem_2.25rem]";
const scopeKey = (s: string) => s.replace(":", "_");

export default function ApiKeysPage() {
  const t = useT();
  const k = "admin_api_keys";

  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [query, setQuery] = useState("");
  const [toast, setToast] = useState<ToastState>(null);
  const [now] = useState(() => Date.now());

  const [createOpen, setCreateOpen] = useState(false);
  const [name, setName] = useState("");
  const [scopes, setScopes] = useState<string[]>(DEFAULT_SCOPES);
  const [creating, setCreating] = useState(false);

  const [secret, setSecret] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const [toRevoke, setToRevoke] = useState<ApiKey | null>(null);
  const [revoking, setRevoking] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await apiFetch(`${apiBase()}/admin/api-keys`);
      if (!res.ok) throw new Error(String(res.status));
      const data = await res.json();
      setKeys(data.keys || []);
    } catch (err) {
      console.error("API keys fetch failed", err);
      setKeys([]);
      setToast({ message: t(`${k}.toast.load_error`), variant: "error" });
    } finally {
      setLoaded(true);
    }
  }, [t]);

  useEffect(() => {
    void load();
  }, [load]);

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return keys;
    return keys.filter(
      (key) =>
        key.name.toLowerCase().includes(q) ||
        key.prefix.toLowerCase().includes(q) ||
        key.scopes.some((s) => s.toLowerCase().includes(q)),
    );
  }, [keys, query]);

  const openCreate = () => {
    setName("");
    setScopes(DEFAULT_SCOPES);
    setCreateOpen(true);
  };

  const toggleScope = (scope: string) =>
    setScopes((cur) => (cur.includes(scope) ? cur.filter((s) => s !== scope) : [...cur, scope]));

  const create = async () => {
    if (!name.trim() || scopes.length === 0) return;
    setCreating(true);
    try {
      const res = await apiFetch(`${apiBase()}/admin/api-keys`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name.trim(), scopes }),
      });
      if (!res.ok) throw new Error(String(res.status));
      const data = await res.json();
      setSecret(data.key);
      setCopied(false);
      setCreateOpen(false);
      await load();
    } catch (err) {
      console.error("API key creation failed", err);
      setToast({ message: t(`${k}.toast.create_error`), variant: "error" });
    } finally {
      setCreating(false);
    }
  };

  const revoke = async () => {
    if (!toRevoke) return;
    setRevoking(true);
    try {
      const res = await apiFetch(`${apiBase()}/admin/api-keys/${toRevoke.id}`, { method: "DELETE" });
      if (!res.ok) throw new Error(String(res.status));
      setToast({ message: t(`${k}.toast.revoked`), variant: "success" });
      setToRevoke(null);
      await load();
    } catch (err) {
      console.error("API key revoke failed", err);
      setToast({ message: t(`${k}.toast.revoke_error`), variant: "error" });
    } finally {
      setRevoking(false);
    }
  };

  const copySecret = async () => {
    if (!secret) return;
    try {
      await navigator.clipboard.writeText(secret);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      /* clipboard blocked: the key stays selectable */
    }
  };

  const showEmpty = loaded && keys.length === 0;

  return (
    <div className="mx-auto flex max-w-[84rem] flex-col gap-6">
      <header className="flex flex-col gap-4 pt-2 sm:flex-row sm:items-end">
        <div className="min-w-0 flex-1">
          <h1 className="text-balance text-2xl font-semibold tracking-[-0.02em] sm:text-[28px]">{t(`${k}.title`)}</h1>
          <p className="mt-1 max-w-[60ch] text-sm text-muted-foreground">{t(`${k}.subtitle`)}</p>
        </div>
        <button type="button" className={solidBtn} onClick={openCreate}>
          <Plus className="h-4 w-4" aria-hidden />
          {t(`${k}.new`)}
        </button>
      </header>

      {secret && (
        <section
          aria-labelledby="api-key-secret-title"
          className="flex flex-col gap-4 rounded-3xl border border-warning/50 bg-warning/10 p-5 sm:p-6"
        >
          <div className="flex items-start gap-4">
            <div className="min-w-0 flex-1">
              <h2 id="api-key-secret-title" className="text-base font-semibold tracking-[-0.01em]">
                {t(`${k}.secret.title`)}
              </h2>
              <p className="mt-1 text-sm text-muted-foreground">{t(`${k}.secret.body`)}</p>
            </div>
            <button
              type="button"
              onClick={() => setSecret(null)}
              aria-label={t(`${k}.secret.done`)}
              className={cn(ghostBtn, "-mr-2 -mt-1 w-9 justify-center px-0")}
            >
              <X className="h-4 w-4" aria-hidden />
            </button>
          </div>
          <div className="flex flex-col gap-2 sm:flex-row sm:items-stretch">
            <code className="min-w-0 flex-1 select-all break-all rounded-xl border border-border bg-background px-3.5 py-2.5 font-mono text-[13px]">
              {secret}
            </code>
            <button type="button" className={outlineBtn} onClick={copySecret}>
              {copied ? <Check className="h-3.5 w-3.5 text-success" aria-hidden /> : <Copy className="h-3.5 w-3.5" aria-hidden />}
              {copied ? t(`${k}.secret.copied`) : t(`${k}.secret.copy`)}
            </button>
          </div>
        </section>
      )}

      {showEmpty ? (
        <div className="flex flex-col items-center rounded-3xl border border-dashed border-border px-6 py-20 text-center">
          <h2 className="text-lg font-semibold tracking-[-0.015em]">{t(`${k}.empty.title`)}</h2>
          <p className="mt-1.5 max-w-[46ch] text-sm text-muted-foreground">{t(`${k}.empty.body`)}</p>
          <button type="button" className={cn(solidBtn, "mt-6")} onClick={openCreate}>
            <Plus className="h-4 w-4" aria-hidden />
            {t(`${k}.new`)}
          </button>
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          <div className="max-w-sm">
            <SearchField value={query} onChange={setQuery} placeholder={t(`${k}.search`)} />
          </div>

          {!loaded ? (
            <div className="flex items-center gap-2 px-1 py-6 text-sm text-muted-foreground" role="status">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
              {t(`${k}.loading`)}
            </div>
          ) : (
            <div className="rounded-3xl border border-border/70 bg-card">
              <div
                className={cn(
                  "hidden items-center gap-4 border-b border-border/60 px-5 py-3 text-xs font-medium text-muted-foreground md:grid",
                  GRID,
                )}
              >
                <span>{t(`${k}.col_key`)}</span>
                <span>{t(`${k}.col_scopes`)}</span>
                <span className="text-right">{t(`${k}.col_used`)}</span>
                <span className="sr-only">{t(`${k}.col_actions`)}</span>
              </div>

              <ul className="overflow-hidden rounded-3xl">
                {visible.map((key) => {
                  const ms = toMs(key.last_used_at);
                  return (
                    <li
                      key={key.id}
                      className={cn(
                        "grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 gap-y-2 border-b border-border/40 px-5 py-3.5 last:border-b-0",
                        GRID,
                      )}
                    >
                      <div className="flex min-w-0 items-center gap-3">
                        <KeyRound className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
                        <div className="min-w-0">
                          <div className="truncate text-sm font-medium">{key.name}</div>
                          <div className="truncate font-mono text-xs text-muted-foreground">
                            {key.prefix}…{key.tenant_id ? ` · ${key.tenant_id}` : ""}
                          </div>
                        </div>
                      </div>

                      <button
                        type="button"
                        onClick={() => setToRevoke(key)}
                        aria-label={t(`${k}.revoke_aria`, { name: key.name })}
                        title={t(`${k}.revoke`)}
                        className={cn(ghostBtn, "w-9 justify-center px-0 hover:text-destructive md:order-last")}
                      >
                        <Trash2 className="h-4 w-4" aria-hidden />
                      </button>

                      <div className="col-span-2 flex min-w-0 flex-wrap gap-1.5 md:col-span-1">
                        {key.scopes.map((s) => (
                          <span
                            key={s}
                            className={cn(
                              "rounded-md px-2 py-0.5 font-mono text-xs",
                              s === "admin" ? "bg-warning/15 font-medium text-warning" : "bg-secondary text-muted-foreground",
                            )}
                          >
                            {s}
                          </span>
                        ))}
                      </div>

                      <div
                        className="col-span-2 text-xs tabular-nums text-muted-foreground md:col-span-1 md:text-right md:text-sm"
                        title={ms ? fullWhen(ms) : undefined}
                      >
                        {ms ? t(`${k}.used_at`, { when: shortWhen(ms, now) }) : t(`${k}.never`)}
                      </div>
                    </li>
                  );
                })}
              </ul>

              {visible.length === 0 && (
                <p className="px-5 py-8 text-center text-sm text-muted-foreground">{t(`${k}.empty_search`)}</p>
              )}
            </div>
          )}
        </div>
      )}

      {createOpen && (
        <Dialog title={t(`${k}.create.title`)} closeLabel={t(`${k}.create.cancel`)} onClose={() => setCreateOpen(false)} className="max-w-xl">
          <form
            className="flex flex-col gap-5"
            onSubmit={(e) => {
              e.preventDefault();
              void create();
            }}
          >
            <label className="flex flex-col gap-1.5">
              <span className="text-sm font-medium">{t(`${k}.create.name`)}</span>
              <input
                autoFocus
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder={t(`${k}.create.name_placeholder`)}
                className={inputCls}
              />
            </label>

            <fieldset className="flex flex-col gap-2">
              <legend className="text-sm font-medium">{t(`${k}.create.scopes`)}</legend>
              <p className="text-xs text-muted-foreground">{t(`${k}.create.scopes_hint`)}</p>
              <div className="mt-1 flex flex-col gap-0.5">
                {SCOPES.map((scope) => {
                  const on = scopes.includes(scope);
                  return (
                    <label
                      key={scope}
                      className={cn(
                        "flex cursor-pointer items-start gap-3 rounded-xl px-3 py-2.5 transition-colors has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ring",
                        on ? "bg-secondary" : "hover:bg-secondary/60",
                      )}
                    >
                      <input
                        type="checkbox"
                        checked={on}
                        onChange={() => toggleScope(scope)}
                        className="mt-0.5 h-4 w-4 shrink-0 accent-foreground"
                      />
                      <span className="min-w-0">
                        <span className="block font-mono text-[13px] font-medium">{scope}</span>
                        <span className="block text-xs text-muted-foreground">{t(`${k}.scope_desc.${scopeKey(scope)}`)}</span>
                      </span>
                    </label>
                  );
                })}
              </div>
              {scopes.includes("admin") && (
                <p role="status" className="px-3 text-xs font-medium text-warning">
                  {t(`${k}.create.admin_warning`)}
                </p>
              )}
            </fieldset>

            <div className="flex justify-end gap-2">
              <button type="button" className={ghostBtn} onClick={() => setCreateOpen(false)}>
                {t(`${k}.create.cancel`)}
              </button>
              <button type="submit" className={solidBtn} disabled={creating || !name.trim() || scopes.length === 0}>
                {creating && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />}
                {creating ? t(`${k}.create.submitting`) : t(`${k}.create.submit`)}
              </button>
            </div>
          </form>
        </Dialog>
      )}

      {toRevoke && (
        <DeleteDialog
          name={toRevoke.name}
          busy={revoking}
          ns={`${k}.revoke_dialog`}
          t={t}
          onConfirm={revoke}
          onClose={() => setToRevoke(null)}
        />
      )}

      <PageToast toast={toast} onDismiss={() => setToast(null)} />
    </div>
  );
}
