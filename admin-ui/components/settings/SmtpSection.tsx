"use client";

import { useCallback, useEffect, useState } from "react";
import { Loader2, Save } from "lucide-react";
import { apiFetch } from "@/lib/api/headers";
import { apiBase } from "@/lib/api";
import { inputCls, solidBtn } from "@/components/ui/classes";
import { ChoiceList, Field, FieldGrid, Group, Note, ProbeBar, SecretInput, SectionHead, Switch, TextInput } from "./ui";
import { K, type SectionCtx } from "./types";

type Security = "starttls" | "ssl" | "none";
type Lang = "it" | "en";

type SmtpState = {
  configured: boolean;
  enabled: boolean;
  host: string;
  port: number;
  security: Security;
  username: string;
  password_present: boolean;
  from_address: string;
  from_name: string;
  reply_to: string;
  email_language: Lang;
  last_test_at: string | null;
  last_test_ok: boolean | null;
  last_test_error: string | null;
};

type Draft = {
  enabled: boolean;
  host: string;
  port: string;
  security: Security;
  username: string;
  password: string;
  from_address: string;
  from_name: string;
  reply_to: string;
  email_language: Lang;
};

const m = `${K}.smtp`;
const DEFAULT_PORT: Record<Security, string> = { starttls: "587", ssl: "465", none: "25" };

const toDraft = (s: SmtpState): Draft => ({
  enabled: s.enabled,
  host: s.host,
  port: String(s.port || 587),
  security: s.security,
  username: s.username,
  password: "",
  from_address: s.from_address,
  from_name: s.from_name,
  reply_to: s.reply_to,
  email_language: s.email_language,
});

/** Error codes from /admin/smtp map to localized messages; unknown codes fall back. */
function errorText(t: SectionCtx["t"], code: string | undefined, fallback: string) {
  if (!code) return fallback;
  const key = `${m}.errors.${code}`;
  const msg = t(key);
  return msg === key ? fallback : msg;
}

export function SmtpSection({ t, notify }: Pick<SectionCtx, "t" | "notify">) {
  const [state, setState] = useState<SmtpState | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [clearPassword, setClearPassword] = useState(false);
  const [testTo, setTestTo] = useState("");
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testedTo, setTestedTo] = useState<string | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await apiFetch(`${apiBase()}/admin/smtp`);
      if (!res.ok) throw new Error(String(res.status));
      const data = (await res.json()) as SmtpState;
      setState(data);
      setDraft(toDraft(data));
      setClearPassword(false);
      setLoadFailed(false);
    } catch {
      setLoadFailed(true);
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch on mount
    void load();
  }, [load]);

  const patch = (p: Partial<Draft>) => setDraft((d) => (d ? { ...d, ...p } : d));

  const dirty =
    !!state &&
    !!draft &&
    (JSON.stringify({ ...draft, password: "" }) !== JSON.stringify(toDraft(state)) || draft.password !== "" || clearPassword);

  const save = async () => {
    if (!draft) return;
    const port = parseInt(draft.port, 10);
    if (!draft.host.trim()) return notify(t(`${m}.v_host`), "error");
    if (isNaN(port) || port < 1 || port > 65535) return notify(t(`${m}.v_port`), "error");
    if (!draft.from_address.trim()) return notify(t(`${m}.v_from`), "error");
    setSaving(true);
    try {
      const res = await apiFetch(`${apiBase()}/admin/smtp`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          enabled: draft.enabled,
          host: draft.host.trim(),
          port,
          security: draft.security,
          username: draft.username.trim() || null,
          password: draft.password || null,
          clear_password: clearPassword && !draft.password,
          from_address: draft.from_address.trim(),
          from_name: draft.from_name.trim() || null,
          reply_to: draft.reply_to.trim() || null,
          email_language: draft.email_language,
        }),
      });
      if (res.ok) {
        const data = (await res.json()) as SmtpState;
        setState(data);
        setDraft(toDraft(data));
        setClearPassword(false);
        notify(t(`${m}.saved`), "success");
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

  const sendTest = async () => {
    setTesting(true);
    setTestedTo(null);
    try {
      const res = await apiFetch(`${apiBase()}/admin/smtp/test`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ to: testTo.trim() || null }),
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok && data.ok) {
        setTestedTo(data.to);
      } else {
        const code = res.ok ? data.error : data?.detail?.code;
        notify(errorText(t, code, t(`${m}.test_failed`)), "error");
      }
      void load();
    } catch {
      notify(t(`${m}.err_network`), "error");
    } finally {
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
          <Field label={t(`${m}.host`)}>
            <TextInput value={draft.host} onChange={(v) => patch({ host: v })} placeholder="smtp.example.com" mono />
          </Field>
          <Field label={t(`${m}.port`)}>
            <TextInput value={draft.port} onChange={(v) => patch({ port: v })} type="number" inputMode="numeric" mono />
          </Field>
        </FieldGrid>
        <ChoiceList<Security>
          value={draft.security}
          onChange={(v) => patch({ security: v, port: draft.port === DEFAULT_PORT[draft.security] ? DEFAULT_PORT[v] : draft.port })}
          label={t(`${m}.security`)}
          options={[
            { value: "starttls", title: t(`${m}.starttls`), description: t(`${m}.starttls_hint`) },
            { value: "ssl", title: t(`${m}.ssl`), description: t(`${m}.ssl_hint`) },
            { value: "none", title: t(`${m}.none`), description: t(`${m}.none_hint`) },
          ]}
        />
      </Group>

      <Group title={t(`${m}.auth`)} description={t(`${m}.auth_hint`)}>
        <FieldGrid>
          <Field label={t(`${m}.username`)}>
            <TextInput value={draft.username} onChange={(v) => patch({ username: v })} mono />
          </Field>
          <Field
            label={t(`${m}.password`)}
            hint={state.password_present && !clearPassword ? t(`${m}.password_saved`) : t(`${m}.password_hint`)}
          >
            <SecretInput
              value={draft.password}
              onChange={(v) => patch({ password: v })}
              placeholder={state.password_present && !clearPassword ? t(`${m}.password_keep`) : ""}
              showLabel={t(`${m}.show`)}
              hideLabel={t(`${m}.hide`)}
            />
          </Field>
          {state.password_present && (
            <label className="flex items-center gap-2 text-sm text-muted-foreground md:col-span-2">
              <input type="checkbox" checked={clearPassword} onChange={(e) => setClearPassword(e.target.checked)} />
              {t(`${m}.password_clear`)}
            </label>
          )}
        </FieldGrid>
      </Group>

      <Group title={t(`${m}.sender`)}>
        <FieldGrid>
          <Field label={t(`${m}.from_address`)}>
            <TextInput value={draft.from_address} onChange={(v) => patch({ from_address: v })} placeholder="noreply@example.com" mono />
          </Field>
          <Field label={t(`${m}.from_name`)}>
            <TextInput value={draft.from_name} onChange={(v) => patch({ from_name: v })} placeholder="AION" />
          </Field>
          <Field label={t(`${m}.reply_to`)} hint={t(`${m}.optional`)}>
            <TextInput value={draft.reply_to} onChange={(v) => patch({ reply_to: v })} mono />
          </Field>
          <Field label={t(`${m}.language`)} hint={t(`${m}.language_hint`)}>
            <select
              value={draft.email_language}
              onChange={(e) => patch({ email_language: e.target.value as Lang })}
              className={inputCls}
            >
              <option value="it">Italiano</option>
              <option value="en">English</option>
            </select>
          </Field>
        </FieldGrid>
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
          <Field label={t(`${m}.test_to`)} hint={t(`${m}.test_to_hint`)} wide>
            <TextInput value={testTo} onChange={setTestTo} placeholder="admin@example.com" mono disabled={!state.configured} />
          </Field>
          {state.configured && !dirty ? (
            <ProbeBar
              probing={testing}
              onProbe={() => void sendTest()}
              label={t(`${m}.test_send`)}
              ok={!!testedTo}
              okText={t(`${m}.test_ok`, { to: testedTo || "" })}
            />
          ) : (
            <p className="text-xs text-muted-foreground md:col-span-2">{t(dirty ? `${m}.test_save_first` : `${m}.test_needs_config`)}</p>
          )}
          {state.last_test_at && !testedTo && (
            <p className="text-xs text-muted-foreground md:col-span-2">
              {state.last_test_ok
                ? t(`${m}.last_ok`, { at: new Date(state.last_test_at).toLocaleString() })
                : t(`${m}.last_failed`, {
                    at: new Date(state.last_test_at).toLocaleString(),
                    error: errorText(t, state.last_test_error || undefined, state.last_test_error || ""),
                  })}
            </p>
          )}
        </FieldGrid>
      </Group>
    </div>
  );
}
