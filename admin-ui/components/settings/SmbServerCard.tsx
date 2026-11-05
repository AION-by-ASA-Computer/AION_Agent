"use client";

/**
 * One Windows file server in Settings → File server (`SmbSection`).
 *
 * Holds its own draft so editing one server never discards unsaved edits of
 * another. Saves through `POST /admin/smb/servers` (new) or
 * `PUT /admin/smb/servers/{id}`, removes through `DELETE` (configuration only,
 * no file is touched) and tests through `POST /admin/smb/servers/{id}/test`
 * with optional credentials used for that test only (never saved) and cleared
 * from the form right after.
 */

import { useState } from "react";
import { CheckCircle2, ChevronDown, Loader2, Plus, Save, Trash2, XCircle } from "lucide-react";
import { apiFetch } from "@/lib/api/headers";
import { apiBase } from "@/lib/api";
import { DeleteDialog } from "@/components/ui/ConfirmDialogs";
import { ghostBtn, outlineBtn, solidBtn } from "@/components/ui/classes";
import { cn } from "@/lib/cn";
import { ChoiceList, Field, FieldGrid, ProbeBar, SecretInput, Switch, TextInput } from "./ui";
import { K, type SectionCtx } from "./types";

export type AuthProtocol = "ntlm" | "negotiate";
export type Share = { name: string; read_only: boolean; label: string };

/** A saved server as returned by `GET /admin/smb` (`servers[]`). */
export type SmbServer = {
  id: string;
  configured: boolean;
  enabled: boolean;
  alias: string;
  label: string;
  host: string;
  port: number;
  default_domain: string;
  credential_set: string;
  shares: Share[];
  auth_protocol: AuthProtocol;
  require_encryption: boolean;
  last_test_at: string | null;
  last_test_ok: boolean | null;
  last_test_error: string | null;
};

/** Full payload of `/admin/smb` endpoints; server creation adds `server_id`. */
export type SmbState = {
  configured: boolean;
  enabled: boolean;
  max_read_mb: number;
  max_write_mb: number;
  lockout_minutes: number;
  servers: SmbServer[];
  connector_synced?: boolean;
  server_id?: string;
};

/** Editable copy of the shares: `key` only keeps React rows stable while editing. */
type DraftShare = Share & { key: number };

type Draft = {
  alias: string;
  label: string;
  host: string;
  port: string;
  default_domain: string;
  credential_set: string;
  shares: DraftShare[];
  auth_protocol: AuthProtocol;
  require_encryption: boolean;
  enabled: boolean;
};

type TestResult = {
  ok: boolean;
  error: string | null;
  negotiated: boolean;
  dialect: string | null;
  authenticated: boolean | null;
  shares: { name: string; ok: boolean; error: string | null }[];
};

export const m = `${K}.smb`;
export const DEFAULT_SET = "DEFAULT";

let shareKey = 0;
const withKey = (s: Share): DraftShare => ({ ...s, key: ++shareKey });

const EMPTY: Draft = {
  alias: "",
  label: "",
  host: "",
  port: "445",
  default_domain: "",
  credential_set: DEFAULT_SET,
  shares: [],
  auth_protocol: "ntlm",
  require_encryption: false,
  enabled: true,
};

const toDraft = (s: SmbServer | null): Draft =>
  s
    ? {
        alias: s.alias,
        label: s.label,
        host: s.host,
        port: String(s.port || 445),
        default_domain: s.default_domain,
        credential_set: s.credential_set || DEFAULT_SET,
        shares: s.shares.map(withKey),
        auth_protocol: s.auth_protocol,
        require_encryption: s.require_encryption,
        enabled: s.enabled,
      }
    : { ...EMPTY, shares: [withKey({ name: "", read_only: false, label: "" })] };

/** Draft without the React keys, for the "unsaved changes" comparison. */
const comparable = (d: Draft) =>
  JSON.stringify({ ...d, shares: d.shares.map(({ name, label, read_only }) => ({ name, label, read_only })) });

/** Error codes from /admin/smb (and the probe) map to localized messages; unknown codes fall back. */
export function errorText(t: SectionCtx["t"], code: string | undefined | null, fallback: string) {
  if (!code) return fallback;
  const key = `${m}.errors.${code}`;
  const msg = t(key);
  return msg === key ? fallback : msg;
}

/** Integer in [min, max], or null when the field is not a valid number in range. */
export function intIn(v: string, min: number, max: number): number | null {
  const n = parseInt(v, 10);
  return isNaN(n) || n < min || n > max ? null : n;
}

// Same formats the API enforces (admin_smb.py): checked here for a precise message.
const ALIAS_RE = /^[a-z0-9][a-z0-9-]{0,30}$/;
const SET_RE = /^[A-Z0-9]{1,24}$/;

/**
 * @param server   saved server, or `null` for the "add server" draft
 * @param onSaved  receives the full `/admin/smb` payload after a save/remove/test
 * @param onCancel discards the "add server" draft (new servers only)
 */
export function SmbServerCard({
  server,
  defaultOpen,
  t,
  notify,
  onSaved,
  onCancel,
  onTested,
}: Pick<SectionCtx, "t" | "notify"> & {
  server: SmbServer | null;
  defaultOpen: boolean;
  onSaved: (data: SmbState) => void;
  onCancel?: () => void;
  onTested: () => void;
}) {
  const [draft, setDraft] = useState<Draft>(() => toDraft(server));
  const [open, setOpen] = useState(defaultOpen);
  const [saving, setSaving] = useState(false);
  const [removing, setRemoving] = useState(false);
  const [confirmRemove, setConfirmRemove] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testUser, setTestUser] = useState("");
  const [testPassword, setTestPassword] = useState("");
  const [result, setResult] = useState<TestResult | null>(null);

  const isNew = server === null;
  const dirty = isNew || comparable(draft) !== comparable(toDraft(server));
  const patch = (p: Partial<Draft>) => setDraft((d) => ({ ...d, ...p }));
  const patchShare = (key: number, p: Partial<Share>) =>
    setDraft((d) => ({ ...d, shares: d.shares.map((s) => (s.key === key ? { ...s, ...p } : s)) }));
  const addShare = () => setDraft((d) => ({ ...d, shares: [...d.shares, withKey({ name: "", read_only: false, label: "" })] }));
  const removeShare = (key: number) => setDraft((d) => ({ ...d, shares: d.shares.filter((s) => s.key !== key) }));

  /** Reads the error code of a failed call and shows it. */
  const fail = async (res: Response, fallbackKey: string) => {
    const err = await res.json().catch(() => ({}));
    notify(errorText(t, err?.detail?.code, t(fallbackKey)), "error");
  };

  const save = async () => {
    const alias = draft.alias.trim().toLowerCase();
    const credentialSet = draft.credential_set.trim().toUpperCase() || DEFAULT_SET;
    const port = intIn(draft.port, 1, 65535);
    const shares = draft.shares
      .map(({ name, label, read_only }) => ({ name: name.trim(), label: label.trim(), read_only }))
      .filter((s) => s.name || s.label);
    if (!ALIAS_RE.test(alias)) return notify(t(`${m}.errors.invalid_alias`), "error");
    if (!draft.host.trim()) return notify(t(`${m}.v_host`), "error");
    if (port === null) return notify(t(`${m}.v_port`), "error");
    if (!SET_RE.test(credentialSet)) return notify(t(`${m}.errors.invalid_credential_set`), "error");
    if (shares.some((s) => !s.name)) return notify(t(`${m}.v_share_name`), "error");
    if (draft.enabled && shares.length === 0) return notify(t(`${m}.errors.shares_required`), "error");
    setSaving(true);
    try {
      const res = await apiFetch(`${apiBase()}/admin/smb/servers${isNew ? "" : `/${server.id}`}`, {
        method: isNew ? "POST" : "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          alias,
          label: draft.label.trim() || null,
          host: draft.host.trim(),
          port,
          default_domain: draft.default_domain.trim() || null,
          credential_set: credentialSet,
          shares,
          auth_protocol: draft.auth_protocol,
          require_encryption: draft.require_encryption,
          enabled: draft.enabled,
        }),
      });
      if (!res.ok) return void (await fail(res, `${m}.err_save`));
      const data = (await res.json()) as SmbState;
      const saved = data.servers.find((s) => s.id === (isNew ? data.server_id : server.id)) ?? null;
      // The API normalises alias/host/set: show what was actually stored.
      if (saved) setDraft(toDraft(saved));
      setResult(null);
      onSaved(data);
      notify(t(`${m}.server_saved`, { alias }), "success");
    } catch {
      notify(t(`${m}.err_network`), "error");
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!server) return;
    setRemoving(true);
    try {
      const res = await apiFetch(`${apiBase()}/admin/smb/servers/${server.id}`, { method: "DELETE" });
      if (!res.ok) return void (await fail(res, `${m}.err_remove`));
      setConfirmRemove(false);
      onSaved((await res.json()) as SmbState);
      notify(t(`${m}.server_removed`, { alias: server.alias }), "success");
    } catch {
      notify(t(`${m}.err_network`), "error");
    } finally {
      setRemoving(false);
    }
  };

  const runTest = async () => {
    if (!server) return;
    setTesting(true);
    setResult(null);
    try {
      const res = await apiFetch(`${apiBase()}/admin/smb/servers/${server.id}/test`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: testUser.trim() || null, password: testPassword || null }),
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok) {
        setResult(data as TestResult);
        if (!data.ok) notify(errorText(t, data.error, t(`${m}.test_failed`)), "error");
      } else {
        notify(errorText(t, data?.detail?.code, t(`${m}.test_failed`)), "error");
      }
      onTested();
    } catch {
      notify(t(`${m}.err_network`), "error");
    } finally {
      // Test credentials are single-use: never keep the password in the form.
      setTestPassword("");
      setTesting(false);
    }
  };

  const credsIncomplete = !!testUser.trim() !== !!testPassword;
  const okText = result?.ok
    ? result.authenticated
      ? t(`${m}.test_ok_auth`, { dialect: result.dialect || "?" })
      : t(`${m}.test_ok_negotiate`, { dialect: result.dialect || "?" })
    : "";
  const title = isNew ? t(`${m}.server_new`) : server.label ? `${server.alias} · ${server.label}` : server.alias;
  const bodyId = `smb-server-${server?.id ?? "new"}`;

  return (
    <section className="overflow-hidden rounded-2xl border border-border bg-card/60">
      <header className="flex flex-wrap items-center gap-x-4 gap-y-2 bg-secondary/60 px-5 py-3.5">
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          aria-controls={bodyId}
          className="focus-ring -mx-1 flex min-w-0 flex-1 items-center gap-2.5 rounded-lg px-1 text-left"
        >
          <ChevronDown className={cn("h-4 w-4 shrink-0 text-muted-foreground transition-transform", !open && "-rotate-90")} aria-hidden />
          <span className="min-w-0">
            <span className="block truncate font-mono text-[14px] font-semibold">{title}</span>
            {!isNew && (
              <span className="block truncate text-xs text-muted-foreground">
                {server.host} · {t(`${m}.credential_set_short`, { set: server.credential_set })} ·{" "}
                {t(`${m}.shares_count`, { count: server.shares.length })}
                {!server.enabled && ` · ${t(`${m}.server_disabled`)}`}
              </span>
            )}
          </span>
        </button>
        {!isNew && server.last_test_at && (
          <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
            {server.last_test_ok ? (
              <CheckCircle2 className="h-3.5 w-3.5 text-success" aria-hidden />
            ) : (
              <XCircle className="h-3.5 w-3.5 text-destructive" aria-hidden />
            )}
            {t(server.last_test_ok ? `${m}.badge_ok` : `${m}.badge_failed`)}
          </span>
        )}
        <div className="flex items-center gap-2.5">
          <span className="text-sm text-muted-foreground" aria-hidden>{t(draft.enabled ? `${m}.on` : `${m}.off`)}</span>
          <Switch checked={draft.enabled} onChange={(v) => patch({ enabled: v })} label={t(`${m}.server_toggle`, { alias: draft.alias || "—" })} />
        </div>
      </header>

      {open && (
        <div id={bodyId} className="border-t border-border">
          <FieldGrid>
            <Field label={t(`${m}.alias`)} hint={t(`${m}.alias_hint`)}>
              <TextInput value={draft.alias} onChange={(v) => patch({ alias: v })} placeholder="fs01" mono />
            </Field>
            <Field label={t(`${m}.label`)} hint={t(`${m}.label_hint`)}>
              <TextInput value={draft.label} onChange={(v) => patch({ label: v })} placeholder={t(`${m}.label_ph`)} />
            </Field>
            <Field label={t(`${m}.host`)} hint={t(`${m}.host_hint`)}>
              <TextInput value={draft.host} onChange={(v) => patch({ host: v })} placeholder="fileserver.example.local" mono />
            </Field>
            <Field label={t(`${m}.port`)}>
              <TextInput value={draft.port} onChange={(v) => patch({ port: v })} type="number" inputMode="numeric" mono />
            </Field>
            <Field label={t(`${m}.domain`)} hint={t(`${m}.domain_hint`)}>
              <TextInput value={draft.default_domain} onChange={(v) => patch({ default_domain: v })} placeholder="CONTOSO" mono />
            </Field>
            <Field label={t(`${m}.credential_set`)} hint={t(`${m}.credential_set_hint`)}>
              <TextInput value={draft.credential_set} onChange={(v) => patch({ credential_set: v.toUpperCase() })} placeholder={DEFAULT_SET} mono />
            </Field>
          </FieldGrid>

          <div className="border-t border-border/40">
            <div className="flex flex-wrap items-start gap-x-4 gap-y-2 px-5 pt-4">
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium">{t(`${m}.shares`)}</p>
                <p className="mt-0.5 text-xs text-muted-foreground">{t(`${m}.shares_hint`)}</p>
              </div>
              <button type="button" onClick={addShare} className={outlineBtn}>
                <Plus className="h-3.5 w-3.5" aria-hidden />
                {t(`${m}.share_add`)}
              </button>
            </div>
            {draft.shares.length === 0 ? (
              <p className="px-5 py-4 text-sm text-muted-foreground">{t(`${m}.shares_empty`)}</p>
            ) : (
              <ul className="divide-y divide-border/40">
                {draft.shares.map((s) => (
                  <li key={s.key} className="grid items-end gap-x-4 gap-y-3 px-5 py-4 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto_auto]">
                    <Field label={t(`${m}.share_name`)}>
                      <TextInput value={s.name} onChange={(v) => patchShare(s.key, { name: v })} placeholder="Documenti" mono />
                    </Field>
                    <Field label={t(`${m}.share_label`)}>
                      <TextInput value={s.label} onChange={(v) => patchShare(s.key, { label: v })} placeholder={t(`${m}.share_label_ph`)} />
                    </Field>
                    <div className="flex h-10 items-center gap-2.5">
                      <Switch checked={s.read_only} onChange={(v) => patchShare(s.key, { read_only: v })} label={t(`${m}.share_read_only`)} />
                      <span className="text-sm text-muted-foreground" aria-hidden>{t(`${m}.share_read_only`)}</span>
                    </div>
                    <button
                      type="button"
                      onClick={() => removeShare(s.key)}
                      aria-label={t(`${m}.share_remove`, { name: s.name || "—" })}
                      className="focus-ring inline-flex h-10 w-10 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
                    >
                      <Trash2 className="h-4 w-4" aria-hidden />
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="border-t border-border/40">
            <ChoiceList<AuthProtocol>
              value={draft.auth_protocol}
              onChange={(v) => patch({ auth_protocol: v })}
              label={t(`${m}.auth_protocol`)}
              options={[
                { value: "ntlm", title: "NTLM", description: t(`${m}.ntlm_hint`) },
                { value: "negotiate", title: "Negotiate", description: t(`${m}.negotiate_hint`) },
              ]}
            />
            <div className="flex items-center gap-4 border-t border-border/40 px-5 py-3.5">
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium">{t(`${m}.encryption`)}</p>
                <p className="mt-0.5 text-xs text-muted-foreground">{t(`${m}.encryption_hint`)}</p>
              </div>
              <Switch checked={draft.require_encryption} onChange={(v) => patch({ require_encryption: v })} label={t(`${m}.encryption`)} />
            </div>
          </div>

          <div className="flex flex-wrap items-center justify-end gap-3 border-t border-border/40 px-5 py-3.5">
            {isNew ? (
              <button type="button" onClick={onCancel} className={ghostBtn}>
                {t(`${m}.cancel`)}
              </button>
            ) : (
              <button type="button" onClick={() => setConfirmRemove(true)} className={cn(ghostBtn, "mr-auto")}>
                <Trash2 className="h-3.5 w-3.5" aria-hidden />
                {t(`${m}.server_remove`)}
              </button>
            )}
            {dirty && !isNew && <span className="text-sm text-muted-foreground" role="status">{t(`${m}.unsaved`)}</span>}
            <button type="button" onClick={() => void save()} disabled={saving || !dirty} className={solidBtn}>
              {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <Save className="h-3.5 w-3.5" aria-hidden />}
              {saving ? t(`${m}.saving`) : t(isNew ? `${m}.server_add_save` : `${m}.server_save`)}
            </button>
          </div>

          {!isNew && (
            <div className="border-t border-border/40">
              <div className="px-5 pt-4">
                <p className="text-sm font-medium">{t(`${m}.test`)}</p>
                <p className="mt-0.5 text-xs text-muted-foreground">{t(`${m}.test_hint`)}</p>
              </div>
              <FieldGrid>
                <Field label={t(`${m}.test_user`)} hint={t(`${m}.test_user_hint`)}>
                  <TextInput value={testUser} onChange={setTestUser} placeholder="CONTOSO\mario.rossi" mono disabled={!server.configured} />
                </Field>
                <Field label={t(`${m}.test_password`)} hint={t(`${m}.test_password_hint`)}>
                  <SecretInput value={testPassword} onChange={setTestPassword} showLabel={t(`${m}.show`)} hideLabel={t(`${m}.hide`)} />
                </Field>
                {server.configured && !dirty ? (
                  credsIncomplete ? (
                    <p className="text-xs text-muted-foreground md:col-span-2">{t(`${m}.test_creds_incomplete`)}</p>
                  ) : (
                    <ProbeBar probing={testing} onProbe={() => void runTest()} label={t(`${m}.test_run`)} ok={!!result?.ok} okText={okText} />
                  )
                ) : (
                  <p className="text-xs text-muted-foreground md:col-span-2">{t(dirty ? `${m}.test_save_first` : `${m}.test_needs_config`)}</p>
                )}
                {result && result.shares.length > 0 && (
                  <ul className="flex flex-col gap-1.5 text-sm md:col-span-2" aria-label={t(`${m}.test_shares`)}>
                    {result.shares.map((s) => (
                      <li key={s.name} className="flex items-center gap-2">
                        {s.ok ? (
                          <CheckCircle2 className="h-4 w-4 shrink-0 text-success" aria-hidden />
                        ) : (
                          <XCircle className="h-4 w-4 shrink-0 text-destructive" aria-hidden />
                        )}
                        <span className="font-mono text-[13px]">{s.name}</span>
                        <span className="text-muted-foreground">
                          {s.ok ? t(`${m}.share_ok`) : errorText(t, s.error, s.error || t(`${m}.test_failed`))}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
                {server.last_test_at && !result && (
                  <p className="text-xs text-muted-foreground md:col-span-2">
                    {server.last_test_ok
                      ? t(`${m}.last_ok`, { at: new Date(server.last_test_at).toLocaleString() })
                      : t(`${m}.last_failed`, {
                          at: new Date(server.last_test_at).toLocaleString(),
                          error: errorText(t, server.last_test_error, server.last_test_error || ""),
                        })}
                  </p>
                )}
              </FieldGrid>
            </div>
          )}
        </div>
      )}

      {confirmRemove && server && (
        <DeleteDialog
          name={server.alias}
          busy={removing}
          ns={`${m}.delete_dialog`}
          t={t}
          onConfirm={() => void remove()}
          onClose={() => setConfirmRemove(false)}
        />
      )}
    </section>
  );
}
