"use client";

/**
 * Settings → File server: admin configuration of the Windows file servers (SMB)
 * used by the `smb_files` MCP connector.
 *
 * Two independent parts, each saving on its own (not via the page bar):
 * - "General": the connector switch, read/write limits and the lockout window,
 *   saved with `PUT /admin/smb`;
 * - one `SmbServerCard` per server (alias, host, shares, credential set…), each
 *   with its own draft, save, remove and connection test
 *   (`/admin/smb/servers[/{id}[/test]]`).
 * Users then enter only their own Windows credentials in chat-ui: one pair per
 * credential set, so servers of the same domain share one account.
 */

import { useCallback, useEffect, useState } from "react";
import { Loader2, Plus, Save } from "lucide-react";
import { apiFetch } from "@/lib/api/headers";
import { apiBase } from "@/lib/api";
import { outlineBtn, solidBtn } from "@/components/ui/classes";
import { Field, FieldGrid, Group, Note, SectionHead, Switch, TextInput } from "./ui";
import { type SectionCtx } from "./types";
import { DEFAULT_SET, SmbServerCard, errorText, intIn, m, type SmbState } from "./SmbServerCard";

/** Same cap as `MAX_SERVERS` in src/api/admin_smb.py. */
const MAX_SERVERS = 20;

type GlobalDraft = { enabled: boolean; max_read_mb: string; max_write_mb: string; lockout_minutes: string };

const toGlobal = (s: SmbState): GlobalDraft => ({
  enabled: s.enabled,
  max_read_mb: String(s.max_read_mb),
  max_write_mb: String(s.max_write_mb),
  lockout_minutes: String(s.lockout_minutes),
});

export function SmbSection({ t, notify }: Pick<SectionCtx, "t" | "notify">) {
  const [state, setState] = useState<SmbState | null>(null);
  const [draft, setDraft] = useState<GlobalDraft | null>(null);
  const [saving, setSaving] = useState(false);
  const [adding, setAdding] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);

  // Reloads (after a test, a server save…) refresh the servers but keep unsaved
  // edits of the General block: its draft is only (re)set on first load and on its own save.
  const load = useCallback(async () => {
    try {
      const res = await apiFetch(`${apiBase()}/admin/smb`);
      if (!res.ok) throw new Error(String(res.status));
      const data = (await res.json()) as SmbState;
      setState(data);
      setDraft((d) => d ?? toGlobal(data));
      setLoadFailed(false);
    } catch {
      setLoadFailed(true);
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch on mount
    void load();
  }, [load]);

  const patch = (p: Partial<GlobalDraft>) => setDraft((d) => (d ? { ...d, ...p } : d));
  const dirty = !!state && !!draft && JSON.stringify(draft) !== JSON.stringify(toGlobal(state));

  /** A server card saved or removed a server: the response is the full configuration. */
  const onServerSaved = (data: SmbState) => {
    setState(data);
    setAdding(false);
  };

  const save = async () => {
    if (!draft || !state) return;
    // Client-side checks mirror the API so the admin gets a precise message before the round trip.
    const maxRead = intIn(draft.max_read_mb, 1, 500);
    const maxWrite = intIn(draft.max_write_mb, 1, 500);
    const lockout = intIn(draft.lockout_minutes, 5, 1440);
    if (maxRead === null || maxWrite === null) return notify(t(`${m}.v_size`), "error");
    if (lockout === null) return notify(t(`${m}.v_lockout`), "error");
    if (draft.enabled) {
      // Same invariant as the API: users' DEFAULT pair is what makes the connector "configured".
      const usable = state.servers.filter((s) => s.enabled && s.shares.length > 0);
      if (usable.length === 0) return notify(t(`${m}.errors.servers_required`), "error");
      if (!usable.some((s) => s.credential_set === DEFAULT_SET)) {
        return notify(t(`${m}.errors.default_credential_set_required`), "error");
      }
    }
    setSaving(true);
    try {
      const res = await apiFetch(`${apiBase()}/admin/smb`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: draft.enabled, max_read_mb: maxRead, max_write_mb: maxWrite, lockout_minutes: lockout }),
      });
      if (res.ok) {
        const data = (await res.json()) as SmbState;
        setState(data);
        setDraft(toGlobal(data));
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

  const canAdd = !adding && state.servers.length < MAX_SERVERS;

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

      <Group title={t(`${m}.general`)} description={t(`${m}.general_hint`)}>
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
        <div className="flex flex-wrap items-center justify-end gap-3 border-t border-border/40 px-5 py-3.5">
          {dirty && <span className="text-sm text-muted-foreground" role="status">{t(`${m}.unsaved`)}</span>}
          <button type="button" onClick={() => void save()} disabled={saving || !dirty} className={solidBtn}>
            {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <Save className="h-3.5 w-3.5" aria-hidden />}
            {saving ? t(`${m}.saving`) : t(`${m}.save`)}
          </button>
        </div>
      </Group>

      <div className="flex flex-wrap items-end gap-x-4 gap-y-2 px-1">
        <div className="min-w-0 flex-1">
          <h3 className="text-[15px] font-semibold">{t(`${m}.servers`)}</h3>
          <p className="mt-0.5 text-sm text-muted-foreground">{t(`${m}.servers_hint`)}</p>
        </div>
        <button type="button" onClick={() => setAdding(true)} disabled={!canAdd} className={outlineBtn}>
          <Plus className="h-3.5 w-3.5" aria-hidden />
          {t(`${m}.server_add`)}
        </button>
      </div>

      {state.servers.length === 0 && !adding && <p className="px-1 text-sm text-muted-foreground">{t(`${m}.servers_empty`)}</p>}

      {/* Keyed by id: each card keeps its own draft across reloads of the list. */}
      {state.servers.map((s) => (
        <SmbServerCard
          key={s.id}
          server={s}
          defaultOpen={state.servers.length === 1}
          t={t}
          notify={notify}
          onSaved={onServerSaved}
          onTested={() => void load()}
        />
      ))}

      {adding && (
        <SmbServerCard
          server={null}
          defaultOpen
          t={t}
          notify={notify}
          onSaved={onServerSaved}
          onCancel={() => setAdding(false)}
          onTested={() => void load()}
        />
      )}
    </div>
  );
}
