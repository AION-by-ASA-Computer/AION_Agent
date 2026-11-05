"use client";

/**
 * Settings → File server: admin configuration of the Windows file server (SMB)
 * used by the `smb_files` MCP connector.
 *
 * The admin sets host, allowed shares (each optionally read-only) and limits
 * once per tenant through `GET/PUT /admin/smb`; users then enter only their own
 * Windows credentials in chat-ui. "Test connection" calls `POST /admin/smb/test`
 * with optional credentials that are used for that test only (never saved) and
 * cleared from the form right after. Saves on its own (not via the page bar).
 */

import { useCallback, useEffect, useState } from "react";
import { CheckCircle2, Loader2, Plus, Save, Trash2, XCircle } from "lucide-react";
import { apiFetch } from "@/lib/api/headers";
import { apiBase } from "@/lib/api";
import { outlineBtn, solidBtn } from "@/components/ui/classes";
import { ChoiceList, Field, FieldGrid, Group, Note, ProbeBar, SecretInput, SectionHead, Switch, TextInput } from "./ui";
import { K, type SectionCtx } from "./types";

type AuthProtocol = "ntlm" | "negotiate";
type Share = { name: string; read_only: boolean; label: string };

type SmbState = {
  configured: boolean;
  enabled: boolean;
  host: string;
  port: number;
  default_domain: string;
  shares: Share[];
  auth_protocol: AuthProtocol;
  require_encryption: boolean;
  max_read_mb: number;
  max_write_mb: number;
  lockout_minutes: number;
  last_test_at: string | null;
  last_test_ok: boolean | null;
  last_test_error: string | null;
  connector_synced?: boolean;
};

/** Editable copy of the shares: `key` only keeps React rows stable while editing. */
type DraftShare = Share & { key: number };

type Draft = {
  enabled: boolean;
  host: string;
  port: string;
  default_domain: string;
  shares: DraftShare[];
  auth_protocol: AuthProtocol;
  require_encryption: boolean;
  max_read_mb: string;
  max_write_mb: string;
  lockout_minutes: string;
};

type TestResult = {
  ok: boolean;
  error: string | null;
  negotiated: boolean;
  dialect: string | null;
  authenticated: boolean | null;
  shares: { name: string; ok: boolean; error: string | null }[];
};

const m = `${K}.smb`;

let shareKey = 0;
const withKey = (s: Share): DraftShare => ({ ...s, key: ++shareKey });

const toDraft = (s: SmbState): Draft => ({
  enabled: s.enabled,
  host: s.host,
  port: String(s.port || 445),
  default_domain: s.default_domain,
  shares: s.shares.map(withKey),
  auth_protocol: s.auth_protocol,
  require_encryption: s.require_encryption,
  max_read_mb: String(s.max_read_mb),
  max_write_mb: String(s.max_write_mb),
  lockout_minutes: String(s.lockout_minutes),
});

/** Draft without the React keys, for the "unsaved changes" comparison. */
const comparable = (d: Draft) =>
  JSON.stringify({ ...d, shares: d.shares.map(({ name, label, read_only }) => ({ name, label, read_only })) });

/** Error codes from /admin/smb (and the probe) map to localized messages; unknown codes fall back. */
function errorText(t: SectionCtx["t"], code: string | undefined | null, fallback: string) {
  if (!code) return fallback;
  const key = `${m}.errors.${code}`;
  const msg = t(key);
  return msg === key ? fallback : msg;
}

/** Integer in [min, max], or null when the field is not a valid number in range. */
function intIn(v: string, min: number, max: number): number | null {
  const n = parseInt(v, 10);
  return isNaN(n) || n < min || n > max ? null : n;
}

export function SmbSection({ t, notify }: Pick<SectionCtx, "t" | "notify">) {
  const [state, setState] = useState<SmbState | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testUser, setTestUser] = useState("");
  const [testPassword, setTestPassword] = useState("");
  const [result, setResult] = useState<TestResult | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);

  const apply = useCallback((data: SmbState) => {
    setState(data);
    setDraft(toDraft(data));
  }, []);

  const load = useCallback(async () => {
    try {
      const res = await apiFetch(`${apiBase()}/admin/smb`);
      if (!res.ok) throw new Error(String(res.status));
      apply((await res.json()) as SmbState);
      setLoadFailed(false);
    } catch {
      setLoadFailed(true);
    }
  }, [apply]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch on mount
    void load();
  }, [load]);

  const patch = (p: Partial<Draft>) => setDraft((d) => (d ? { ...d, ...p } : d));
  const patchShare = (key: number, p: Partial<Share>) =>
    setDraft((d) => (d ? { ...d, shares: d.shares.map((s) => (s.key === key ? { ...s, ...p } : s)) } : d));
  const addShare = () => setDraft((d) => (d ? { ...d, shares: [...d.shares, withKey({ name: "", read_only: false, label: "" })] } : d));
  const removeShare = (key: number) => setDraft((d) => (d ? { ...d, shares: d.shares.filter((s) => s.key !== key) } : d));

  const dirty = !!state && !!draft && comparable(draft) !== comparable(toDraft(state));

  const save = async () => {
    if (!draft) return;
    // Client-side checks mirror the API so the admin gets a precise message before the round trip.
    const port = intIn(draft.port, 1, 65535);
    const maxRead = intIn(draft.max_read_mb, 1, 500);
    const maxWrite = intIn(draft.max_write_mb, 1, 500);
    const lockout = intIn(draft.lockout_minutes, 5, 1440);
    const shares = draft.shares
      .map(({ name, label, read_only }) => ({ name: name.trim(), label: label.trim(), read_only }))
      .filter((s) => s.name || s.label);
    if (draft.enabled && !draft.host.trim()) return notify(t(`${m}.v_host`), "error");
    if (port === null) return notify(t(`${m}.v_port`), "error");
    if (shares.some((s) => !s.name)) return notify(t(`${m}.v_share_name`), "error");
    if (draft.enabled && shares.length === 0) return notify(t(`${m}.errors.shares_required`), "error");
    if (maxRead === null || maxWrite === null) return notify(t(`${m}.v_size`), "error");
    if (lockout === null) return notify(t(`${m}.v_lockout`), "error");
    setSaving(true);
    try {
      const res = await apiFetch(`${apiBase()}/admin/smb`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          enabled: draft.enabled,
          host: draft.host.trim(),
          port,
          default_domain: draft.default_domain.trim() || null,
          shares,
          auth_protocol: draft.auth_protocol,
          require_encryption: draft.require_encryption,
          max_read_mb: maxRead,
          max_write_mb: maxWrite,
          lockout_minutes: lockout,
        }),
      });
      if (res.ok) {
        const data = (await res.json()) as SmbState;
        apply(data);
        setResult(null);
        // Enabled here but the Hub row does not exist yet: the admin must add the connector there.
        if (data.enabled && data.connector_synced === false) notify(t(`${m}.hub_missing`), "warning");
        else notify(t(`${m}.saved`), "success");
      } else {
        const err = await res.json().catch(() => ({}));
        notify(errorText(t, err?.detail?.code, t(`${m}.err_save`)), "error");
      }
    } catch {
      notify(t(`${m}.err_network`), "error");
    } finally {
      setSaving(false);
    }
  };

  const runTest = async () => {
    setTesting(true);
    setResult(null);
    try {
      const res = await apiFetch(`${apiBase()}/admin/smb/test`, {
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
      void load();
    } catch {
      notify(t(`${m}.err_network`), "error");
    } finally {
      // Test credentials are single-use: never keep the password in the form.
      setTestPassword("");
      setTesting(false);
    }
  };

  if (loadFailed) {
    return (
      <div className="flex flex-col gap-5">
        <SectionHead title={t(`${m}.title`)} description={t(`${m}.description`)} />
        <Note tone="warn">{t(`${m}.load_failed`)}</Note>
      </div>
    );
  }

  if (!state || !draft) {
    return (
      <div className="flex items-center gap-2 px-1 text-sm text-muted-foreground" role="status">
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
        {t(`${m}.loading`)}
      </div>
    );
  }

  const credsIncomplete = !!testUser.trim() !== !!testPassword;
  const okText = result?.ok
    ? result.authenticated
      ? t(`${m}.test_ok_auth`, { dialect: result.dialect || "?" })
      : t(`${m}.test_ok_negotiate`, { dialect: result.dialect || "?" })
    : "";

  return (
    <div className="flex flex-col gap-5">
      <SectionHead
        title={t(`${m}.title`)}
        description={t(`${m}.description`)}
        action={
          <div className="flex items-center gap-3">
            <span className="text-sm text-muted-foreground" aria-hidden>{t(draft.enabled ? `${m}.on` : `${m}.off`)}</span>
            <Switch checked={draft.enabled} onChange={(v) => patch({ enabled: v })} label={t(`${m}.toggle`)} />
          </div>
        }
      />

      {!state.configured && <Note tone="warn">{t(`${m}.not_configured`)}</Note>}

      <Group title={t(`${m}.server`)}>
        <FieldGrid>
          <Field label={t(`${m}.host`)} hint={t(`${m}.host_hint`)}>
            <TextInput value={draft.host} onChange={(v) => patch({ host: v })} placeholder="fileserver.example.local" mono />
          </Field>
          <Field label={t(`${m}.port`)}>
            <TextInput value={draft.port} onChange={(v) => patch({ port: v })} type="number" inputMode="numeric" mono />
          </Field>
          <Field label={t(`${m}.domain`)} hint={t(`${m}.domain_hint`)} wide>
            <TextInput value={draft.default_domain} onChange={(v) => patch({ default_domain: v })} placeholder="CONTOSO" mono />
          </Field>
        </FieldGrid>
      </Group>

      <Group
        title={t(`${m}.shares`)}
        description={t(`${m}.shares_hint`)}
        action={
          <button type="button" onClick={addShare} className={outlineBtn}>
            <Plus className="h-3.5 w-3.5" aria-hidden />
            {t(`${m}.share_add`)}
          </button>
        }
      >
        {draft.shares.length === 0 ? (
          <p className="px-5 py-5 text-sm text-muted-foreground">{t(`${m}.shares_empty`)}</p>
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
      </Group>

      <Group title={t(`${m}.advanced`)}>
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
        <div className="border-t border-border/40">
          <FieldGrid>
            <Field label={t(`${m}.max_read`)} hint={t(`${m}.size_hint`)}>
              <TextInput value={draft.max_read_mb} onChange={(v) => patch({ max_read_mb: v })} type="number" inputMode="numeric" mono />
            </Field>
            <Field label={t(`${m}.max_write`)} hint={t(`${m}.size_hint`)}>
              <TextInput value={draft.max_write_mb} onChange={(v) => patch({ max_write_mb: v })} type="number" inputMode="numeric" mono />
            </Field>
            <Field label={t(`${m}.lockout`)} hint={t(`${m}.lockout_hint`)} wide>
              <TextInput value={draft.lockout_minutes} onChange={(v) => patch({ lockout_minutes: v })} type="number" inputMode="numeric" mono />
            </Field>
          </FieldGrid>
        </div>
      </Group>

      <div className="flex flex-wrap items-center justify-end gap-3">
        {dirty && <span className="text-sm text-muted-foreground" role="status">{t(`${m}.unsaved`)}</span>}
        <button type="button" onClick={() => void save()} disabled={saving || !dirty} className={solidBtn}>
          {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <Save className="h-3.5 w-3.5" aria-hidden />}
          {saving ? t(`${m}.saving`) : t(`${m}.save`)}
        </button>
      </div>

      <Group title={t(`${m}.test`)} description={t(`${m}.test_hint`)}>
        <FieldGrid>
          <Field label={t(`${m}.test_user`)} hint={t(`${m}.test_user_hint`)}>
            <TextInput value={testUser} onChange={setTestUser} placeholder="CONTOSO\mario.rossi" mono disabled={!state.configured} />
          </Field>
          <Field label={t(`${m}.test_password`)} hint={t(`${m}.test_password_hint`)}>
            <SecretInput value={testPassword} onChange={setTestPassword} showLabel={t(`${m}.show`)} hideLabel={t(`${m}.hide`)} />
          </Field>
          {state.configured && !dirty ? (
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
          {state.last_test_at && !result && (
            <p className="text-xs text-muted-foreground md:col-span-2">
              {state.last_test_ok
                ? t(`${m}.last_ok`, { at: new Date(state.last_test_at).toLocaleString() })
                : t(`${m}.last_failed`, {
                    at: new Date(state.last_test_at).toLocaleString(),
                    error: errorText(t, state.last_test_error, state.last_test_error || ""),
                  })}
            </p>
          )}
        </FieldGrid>
      </Group>
    </div>
  );
}
