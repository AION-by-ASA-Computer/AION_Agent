"use client";

import { useCallback, useEffect, useState } from "react";
import { Check, Info, KeyRound, Loader2, RotateCcw, Save, ShieldCheck, X } from "lucide-react";
import { apiBase } from "@/lib/api";
import { apiFetch } from "@/lib/api/headers";
import { readApiErrorMessage } from "@/lib/apiErrors";
import { cn } from "@/lib/cn";
import { fullWhen, toMs } from "@/lib/datetime";
import { useT } from "@/lib/i18n/use-t";
import type { ToastState } from "@/components/PageToast";
import { Field, FieldGrid, Group, Mono, Note, SecretInput, Switch, TextInput } from "@/components/settings/ui";
import { Select } from "@/components/ui/Select";
import { outlineBtn, solidBtn } from "@/components/ui/classes";
import { profileSlug } from "@/components/profiles/useProfiles";
import { rich } from "@/components/sso/MicrosoftSsoGuide";
import { CopyField, MetaLink, WhatsAppGuideDialog } from "./WhatsAppGuideDialog";

const k = "admin_whatsapp";

export type WhatsAppChannel = {
  configured: boolean;
  enabled: boolean;
  force_disabled: boolean;
  waba_id: string | null;
  phone_number_id: string | null;
  display_phone_number: string | null;
  verified_name: string | null;
  access_token_hint: string | null;
  app_secret_hint: string | null;
  verify_token: string | null;
  default_profile_slug: string | null;
  webhook_url: string | null;
  graph_api_version: string | null;
  validated_at: string | null;
  webhook_verified_at: string | null;
  last_webhook_at: string | null;
  last_error: string | null;
};

type CheckId = "token_phone" | "cloud_api_registered" | "app_subscribed" | "webhook_verified";
type CheckResult = { id: CheckId; ok: boolean; detail?: string | null };

export type Notify = (message: string, variant?: NonNullable<ToastState>["variant"]) => void;

/** Backend timestamps may be UTC without an offset: read them as UTC, not local time. */
function when(v: string | null): string {
  if (!v) return "";
  return fullWhen(toMs(/(Z|[+-]\d\d:?\d\d)$/.test(v) ? v : `${v}Z`));
}

const JSON_HEADERS = { "Content-Type": "application/json" };

export function WhatsAppConfigPanel({ notify }: { notify: Notify }) {
  const t = useT();
  const [cfg, setCfg] = useState<WhatsAppChannel | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const [wabaId, setWabaId] = useState("");
  const [phoneId, setPhoneId] = useState("");
  const [accessToken, setAccessToken] = useState("");
  const [appSecret, setAppSecret] = useState("");
  const [profile, setProfile] = useState("");
  const [profiles, setProfiles] = useState<{ value: string; label: string }[]>([]);

  const [saving, setSaving] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [validating, setValidating] = useState(false);
  const [toggling, setToggling] = useState(false);
  const [checks, setChecks] = useState<CheckResult[] | null>(null);
  const [guideOpen, setGuideOpen] = useState(false);

  const sync = useCallback((c: WhatsAppChannel) => {
    setCfg(c);
    setWabaId(c.waba_id || "");
    setPhoneId(c.phone_number_id || "");
    setProfile(c.default_profile_slug || "");
    setAccessToken("");
    setAppSecret("");
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await apiFetch(`${apiBase()}/admin/whatsapp`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      sync(await res.json());
      setLoadError(null);
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [sync]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch on mount
    void load();
    apiFetch(`${apiBase()}/admin/profiles`)
      .then((r) => (r.ok ? r.json() : Promise.reject(r)))
      .then((d) => {
        const list: { name?: string; slug?: string }[] = Array.isArray(d) ? d : [];
        setProfiles(list.map((p) => ({ value: profileSlug(p), label: p.name || profileSlug(p) })));
      })
      .catch(() => {});
  }, [load]);

  if (loading && !cfg) {
    return (
      <div className="flex items-center gap-2 px-1 py-6 text-sm text-muted-foreground" role="status">
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
        {t(`${k}.load.loading`)}
      </div>
    );
  }

  if (!cfg) {
    return (
      <div className="flex flex-col items-start gap-3">
        <Note tone="warn">
          <p className="font-medium text-foreground">{t(`${k}.load.failed`, { error: loadError || "" })}</p>
          <p className="mt-0.5">{t(`${k}.load.hint`)}</p>
        </Note>
        <button type="button" className={outlineBtn} onClick={() => void load()} disabled={loading}>
          {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <RotateCcw className="h-3.5 w-3.5" aria-hidden />}
          {t(`${k}.load.retry`)}
        </button>
      </div>
    );
  }

  const dirty =
    wabaId.trim() !== (cfg.waba_id || "") ||
    phoneId.trim() !== (cfg.phone_number_id || "") ||
    profile !== (cfg.default_profile_slug || "") ||
    !!accessToken.trim() ||
    !!appSecret.trim();
  const canSave = !saving && !!wabaId.trim() && !!phoneId.trim() && dirty;

  const save = async () => {
    if (!wabaId.trim() || !phoneId.trim()) return notify(t(`${k}.fields.required`), "error");
    setSaving(true);
    try {
      const res = await apiFetch(`${apiBase()}/admin/whatsapp`, {
        method: "PUT",
        headers: JSON_HEADERS,
        body: JSON.stringify({
          waba_id: wabaId.trim(),
          phone_number_id: phoneId.trim(),
          access_token: accessToken.trim() || undefined,
          app_secret: appSecret.trim() || undefined,
          default_profile_slug: profile || null,
        }),
      });
      if (!res.ok) throw new Error(await readApiErrorMessage(res));
      sync(await res.json());
      setChecks(null);
      notify(t(`${k}.fields.saved`), "success");
    } catch (e) {
      notify(t(`${k}.fields.save_failed`, { error: e instanceof Error ? e.message : "" }), "error");
    } finally {
      setSaving(false);
    }
  };

  const generate = async () => {
    setGenerating(true);
    try {
      const res = await apiFetch(`${apiBase()}/admin/whatsapp/verify-token`, { method: "POST" });
      if (!res.ok) throw new Error(await readApiErrorMessage(res));
      const { verify_token } = await res.json();
      setCfg((c) => (c ? { ...c, verify_token } : c));
      notify(t(`${k}.webhook.generated`), "success");
    } catch (e) {
      notify(t(`${k}.webhook.generate_failed`, { error: e instanceof Error ? e.message : "" }), "error");
    } finally {
      setGenerating(false);
    }
  };

  const validate = async () => {
    setValidating(true);
    try {
      const res = await apiFetch(`${apiBase()}/admin/whatsapp/validate`, { method: "POST" });
      if (!res.ok) throw new Error(await readApiErrorMessage(res));
      const data: { ok: boolean; checks: CheckResult[]; channel?: WhatsAppChannel } = await res.json();
      setChecks(data.checks || []);
      if (data.channel) setCfg(data.channel);
      notify(t(`${k}.verify.${data.ok ? "ok" : "failed"}`), data.ok ? "success" : "warning");
    } catch (e) {
      notify(t(`${k}.verify.error`, { error: e instanceof Error ? e.message : "" }), "error");
    } finally {
      setValidating(false);
    }
  };

  const toggle = async (enabled: boolean) => {
    setToggling(true);
    try {
      const res = await apiFetch(`${apiBase()}/admin/whatsapp/enable`, {
        method: "POST",
        headers: JSON_HEADERS,
        body: JSON.stringify({ enabled }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        const code = body?.detail?.code;
        if (res.status === 409 && (code === "not_validated" || code === "force_disabled")) {
          notify(t(`${k}.enable.${code}`), "warning");
          return;
        }
        const detail = typeof body?.detail === "string" ? body.detail : `HTTP ${res.status}`;
        throw new Error(detail);
      }
      const data: { enabled: boolean } = await res.json();
      setCfg((c) => (c ? { ...c, enabled: data.enabled } : c));
      notify(t(`${k}.enable.${data.enabled ? "on" : "off"}`), "success");
    } catch (e) {
      notify(t(`${k}.enable.failed`, { error: e instanceof Error ? e.message : "" }), "error");
    } finally {
      setToggling(false);
    }
  };

  const secretHint = (hint: string | null) => (hint ? t(`${k}.fields.stored`, { hint }) : t(`${k}.fields.not_stored`));
  const verifyToken = cfg.verify_token || "";
  const webhookUrl = cfg.webhook_url || "";
  const canEnable = !!cfg.validated_at && !cfg.force_disabled;
  const verifyBlocked = !cfg.configured ? t(`${k}.verify.not_configured`) : dirty ? t(`${k}.verify.save_first`) : null;

  const status: { key: string; value: string; tone?: "error" }[] = [
    ...(cfg.display_phone_number
      ? [{ key: "number", value: [cfg.display_phone_number, cfg.verified_name].filter(Boolean).join(" · ") }]
      : []),
    { key: "validated", value: when(cfg.validated_at) || t(`${k}.status.never`) },
    { key: "webhook_verified", value: when(cfg.webhook_verified_at) || t(`${k}.status.never`) },
    { key: "last_webhook", value: when(cfg.last_webhook_at) || t(`${k}.status.never`) },
    ...(cfg.last_error ? [{ key: "last_error", value: cfg.last_error, tone: "error" as const }] : []),
  ];

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-col gap-3 rounded-2xl bg-secondary/60 px-5 py-4 text-[15px]">
        <h3 className="flex items-center gap-2 text-base font-semibold">
          <Info className="h-4 w-4 text-muted-foreground" aria-hidden /> {t(`${k}.summary.title`)}
        </h3>
        <ol className="list-decimal space-y-1.5 pl-5 leading-relaxed text-muted-foreground marker:font-medium marker:text-foreground">
          {[1, 2, 3, 4, 5].map((n) => (
            <li key={n}>{rich(t(`${k}.summary.s${n}`))}</li>
          ))}
        </ol>
        <div className="flex flex-wrap gap-2 pt-1">
          <button type="button" onClick={() => setGuideOpen(true)} className={solidBtn}>
            {t(`${k}.summary.open`)}
          </button>
          <MetaLink />
        </div>
      </div>

      {cfg.force_disabled && <Note tone="warn">{t(`${k}.force_disabled`)}</Note>}

      <Group title={t(`${k}.fields.title`)} description={t(`${k}.fields.desc`)}>
        <FieldGrid>
          <Field label={t(`${k}.fields.waba_id`)}>
            <TextInput value={wabaId} onChange={setWabaId} mono inputMode="numeric" placeholder={t(`${k}.fields.waba_ph`)} />
          </Field>
          <Field label={t(`${k}.fields.phone_id`)}>
            <TextInput value={phoneId} onChange={setPhoneId} mono inputMode="numeric" placeholder={t(`${k}.fields.phone_ph`)} />
          </Field>
          <Field label={t(`${k}.fields.access_token`)} hint={secretHint(cfg.access_token_hint)}>
            <SecretInput
              value={accessToken}
              onChange={setAccessToken}
              placeholder={cfg.access_token_hint ? t(`${k}.fields.keep_ph`) : t(`${k}.fields.access_token_ph`)}
              showLabel={t(`${k}.fields.show`)}
              hideLabel={t(`${k}.fields.hide`)}
            />
          </Field>
          <Field label={t(`${k}.fields.app_secret`)} hint={secretHint(cfg.app_secret_hint)}>
            <SecretInput
              value={appSecret}
              onChange={setAppSecret}
              placeholder={cfg.app_secret_hint ? t(`${k}.fields.keep_ph`) : t(`${k}.fields.app_secret_ph`)}
              showLabel={t(`${k}.fields.show`)}
              hideLabel={t(`${k}.fields.hide`)}
            />
          </Field>
          <Field label={t(`${k}.fields.profile`)} hint={t(`${k}.fields.profile_hint`)} wide>
            <Select
              value={profile}
              onChange={setProfile}
              options={[
                { value: "", label: t(`${k}.fields.profile_none`) },
                ...profiles,
                // Keep a saved slug selectable even if the profile list did not load.
                ...(profile && !profiles.some((p) => p.value === profile) ? [{ value: profile, label: profile }] : []),
              ]}
            />
          </Field>
        </FieldGrid>
        <div className="flex justify-end border-t border-border/60 px-5 py-3.5">
          <button type="button" className={solidBtn} onClick={() => void save()} disabled={!canSave}>
            {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <Save className="h-3.5 w-3.5" aria-hidden />}
            {saving ? t(`${k}.fields.saving`) : t(`${k}.fields.save`)}
          </button>
        </div>
      </Group>

      <Group title={t(`${k}.webhook.title`)} description={t(`${k}.webhook.desc`)}>
        <div className="flex flex-col gap-4 px-5 py-5">
          <CopyField
            label={t(`${k}.webhook.url`)}
            value={webhookUrl}
            copyLabel={t(`${k}.webhook.copy`, { what: t(`${k}.webhook.url`) })}
            copiedLabel={t(`${k}.webhook.copied`)}
          />
          <div className="flex flex-col gap-1.5">
            <CopyField
              label={t(`${k}.webhook.verify_token`)}
              value={verifyToken}
              empty={t(`${k}.webhook.empty`)}
              copyLabel={t(`${k}.webhook.copy`, { what: t(`${k}.webhook.verify_token`) })}
              copiedLabel={t(`${k}.webhook.copied`)}
              action={
                <button type="button" className={cn(outlineBtn, "shrink-0")} onClick={() => void generate()} disabled={generating}>
                  {generating ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <KeyRound className="h-3.5 w-3.5" aria-hidden />}
                  {t(`${k}.webhook.${verifyToken ? "regenerate" : "generate"}`)}
                </button>
              }
            />
            <p className="text-xs text-muted-foreground">{t(`${k}.webhook.verify_token_hint`)}</p>
          </div>
        </div>
      </Group>

      <Group title={t(`${k}.verify.title`)} description={t(`${k}.verify.desc`)}>
        <div className="flex flex-col gap-4 px-5 py-5">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            <button type="button" className={outlineBtn} onClick={() => void validate()} disabled={validating || !!verifyBlocked}>
              {validating ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <ShieldCheck className="h-3.5 w-3.5" aria-hidden />}
              {validating ? t(`${k}.verify.running`) : t(`${k}.verify.run`)}
            </button>
            {verifyBlocked && <span className="text-sm text-muted-foreground">{verifyBlocked}</span>}
          </div>

          {checks && checks.length > 0 && (
            <ul className="flex flex-col divide-y divide-border/40 rounded-xl border border-border/70" aria-live="polite">
              {checks.map((c) => {
                const label = t(`${k}.verify.checks.${c.id}`);
                return (
                  <li key={c.id} className="flex items-start gap-3 px-4 py-3">
                    {c.ok ? (
                      <Check className="mt-0.5 h-4 w-4 shrink-0 text-success" aria-label="OK" />
                    ) : (
                      <X className="mt-0.5 h-4 w-4 shrink-0 text-destructive" aria-label="KO" />
                    )}
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium">{label.startsWith(`${k}.`) ? c.id : label}</p>
                      {c.detail && <p className="mt-0.5 break-words text-xs text-muted-foreground">{c.detail}</p>}
                    </div>
                  </li>
                );
              })}
            </ul>
          )}

          <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-[max-content_minmax(0,1fr)]">
            {status.map((s) => (
              <div key={s.key} className="contents">
                <dt className="text-muted-foreground">{t(`${k}.status.${s.key}`)}</dt>
                <dd className={cn("min-w-0 break-words", s.tone === "error" && "text-destructive")}>
                  {s.key === "number" ? <Mono>{s.value}</Mono> : s.value}
                </dd>
              </div>
            ))}
          </dl>
        </div>
        <div className="flex items-center gap-4 border-t border-border/60 px-5 py-3.5">
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium">{t(`${k}.enable.label`)}</p>
            <p className="mt-0.5 text-xs text-muted-foreground">
              {canEnable || cfg.enabled ? t(`${k}.enable.desc`) : t(`${k}.enable.needs_validation`)}
            </p>
          </div>
          {toggling && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" aria-hidden />}
          <Switch
            checked={cfg.enabled}
            onChange={(v) => void toggle(v)}
            label={t(`${k}.enable.label`)}
            disabled={toggling || (!cfg.enabled && !canEnable)}
          />
        </div>
      </Group>

      {guideOpen && <WhatsAppGuideDialog webhookUrl={webhookUrl} verifyToken={verifyToken} onClose={() => setGuideOpen(false)} />}
    </div>
  );
}
