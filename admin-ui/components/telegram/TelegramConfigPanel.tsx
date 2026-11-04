"use client";

/**
 * "Configuration" section of the admin Telegram page (formerly Settings → Telegram):
 * live gateway status, manager-bot token, channel policies and chat behaviour.
 *
 * The values are `AION_TELEGRAM_*` env keys stored through `/admin/settings`. That
 * endpoint rewrites the whole override set on every POST, so this panel loads the
 * full settings map and posts it back with only the Telegram keys edited: posting
 * the Telegram subset alone would wipe every other admin override.
 * Changing a Telegram key restarts the gateway in-process; a `restarting` reply
 * (container env) shows the shared restart overlay instead.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { Loader2, RefreshCw, RotateCcw, Save, Zap } from "lucide-react";
import { apiFetch } from "@/lib/api/headers";
import { apiBase } from "@/lib/api";
import { cn } from "@/lib/cn";
import { RestartOverlay } from "@/components/RestartOverlay";
import { Field, FieldGrid, Group, Mono, Note, SecretInput, TextInput, ToggleList, ToggleRow } from "@/components/settings/ui";
import { outlineBtn, solidBtn } from "@/components/ui/classes";
import { k, type Notify, type T } from "./shared";

const c = `${k}.config`;

type Settings = Record<string, string>;

/** Numeric fields that must be integers > 0 when set. */
const POSITIVE_KEYS = [
  "AION_TELEGRAM_MAX_BOTS_PER_USER",
  "AION_TELEGRAM_MAX_RUNNING_BOTS",
  "AION_TELEGRAM_MAX_CONCURRENT_JOBS",
  "AION_TELEGRAM_TURN_TIMEOUT_SEC",
  "AION_TELEGRAM_STREAM_EDIT_INTERVAL_MS",
  "AION_TELEGRAM_POLLING_TIMEOUT",
  "AION_TELEGRAM_PAIRING_CODE_TTL_MIN",
] as const;

/** Numeric fields where 0 is allowed (0 turns the feature off). */
const NON_NEGATIVE_KEYS = ["AION_TELEGRAM_RECONCILE_INTERVAL_MIN"] as const;

const isPositive = (v: string | undefined) => {
  if (!v) return true;
  const n = parseInt(v, 10);
  return !isNaN(n) && n > 0;
};
const isNonNegative = (v: string | undefined) => !v || /^\d+$/.test(v.trim());

/** `GET /admin/telegram/status`: runtime view of the gateway, independent of unsaved edits. */
type Status = {
  enabled: boolean;
  token_configured: boolean;
  running: boolean;
  connected: boolean;
  bot_username: string | null;
  can_manage_bots: boolean | null;
  running_bots: number;
  encryption_ok: boolean;
  encryption_error: string | null;
};

/** `POST /admin/telegram/test-token`: checks the token typed in the field, before saving. */
type TokenCheck =
  | { ok: true; id: number; username: string | null; can_manage_bots: boolean }
  | { ok: false; error: "missing" | "malformed" | "unauthorized" | "network"; detail?: string };

/**
 * @param onSaved called after a successful save so the page can reload the lists that
 *                depend on the config (default quota, running bots).
 */
export function TelegramConfigPanel({ t, notify, onSaved }: { t: T; notify: Notify; onSaved: () => void }) {
  const [settings, setSettings] = useState<Settings>({});
  const [baseline, setBaseline] = useState<Settings | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [saving, setSaving] = useState(false);
  const [restarting, setRestarting] = useState(false);

  const [status, setStatus] = useState<Status | null>(null);
  const [statusFailed, setStatusFailed] = useState(false);
  const [checking, setChecking] = useState(false);
  const [check, setCheck] = useState<TokenCheck | null>(null);

  const loadSettings = useCallback(async () => {
    try {
      const res = await apiFetch(`${apiBase()}/admin/settings`);
      if (!res.ok) throw new Error(String(res.status));
      const s: Settings = (await res.json()).settings || {};
      setSettings(s);
      setBaseline(s);
      setLoadFailed(false);
    } catch {
      setLoadFailed(true);
    }
  }, []);

  const loadStatus = useCallback(async () => {
    try {
      const res = await apiFetch(`${apiBase()}/admin/telegram/status`);
      if (!res.ok) throw new Error(String(res.status));
      setStatus(await res.json());
      setStatusFailed(false);
    } catch {
      setStatusFailed(true);
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch on mount
    void loadSettings();
    void loadStatus();
  }, [loadSettings, loadStatus]);

  const set = useCallback((key: string, value: string) => setSettings((p) => ({ ...p, [key]: value })), []);
  const on = (key: string, fallback = false) => (settings[key] === undefined ? fallback : settings[key] === "1");
  const tog = (key: string) => (v: boolean) => set(key, v ? "1" : "0");
  const txt = (key: string, fallback = "") => settings[key] ?? fallback;
  const secret = { showLabel: t(`${c}.show_secret`), hideLabel: t(`${c}.hide_secret`) };

  // Only Telegram keys can differ from the baseline: this panel edits nothing else.
  const dirty = useMemo(() => {
    if (!baseline) return false;
    const keys = new Set([...Object.keys(baseline), ...Object.keys(settings)]);
    for (const key of keys) if ((baseline[key] ?? "") !== (settings[key] ?? "")) return true;
    return false;
  }, [baseline, settings]);
  const canSave = dirty && !saving && !restarting;

  /** Client-side checks mirroring the backend's expectations; returns the first problem. */
  const validate = (): string | null => {
    for (const key of POSITIVE_KEYS) if (!isPositive(settings[key])) return t(`${c}.v_number`, { key });
    for (const key of NON_NEGATIVE_KEYS) if (!isNonNegative(settings[key])) return t(`${c}.v_non_negative`, { key });
    const proxy = (settings.AION_TELEGRAM_PROXY_URL || "").trim();
    if (proxy && !/^(https?|socks[45]h?):\/\//.test(proxy)) return t(`${c}.v_proxy`);
    return null;
  };

  const save = useCallback(async () => {
    const problem = validate();
    if (problem) return notify(problem, "error");
    setSaving(true);
    try {
      // Full map on purpose: see the module header.
      const res = await apiFetch(`${apiBase()}/admin/settings`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ settings }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        notify(err.detail || t(`${c}.err_save`), "error");
        return;
      }
      const data = await res.json();
      if (data.restarting) {
        setRestarting(true);
        return;
      }
      notify(t(`${c}.saved`), "success");
      setCheck(null);
      await loadSettings();
      void loadStatus();
      onSaved();
    } catch {
      notify(t(`${c}.err_network`), "error");
    } finally {
      setSaving(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settings, loadSettings, loadStatus, notify, onSaved, t]);

  const discard = () => {
    if (!baseline) return;
    setSettings(baseline);
    setCheck(null);
  };

  // Ctrl/Cmd+S saves the config instead of the browser's "save page", as on Settings.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && !e.altKey && e.key.toLowerCase() === "s") {
        e.preventDefault();
        if (canSave) void save();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [canSave, save]);

  // Leaving with unsaved edits asks the browser to confirm.
  useEffect(() => {
    if (!dirty) return;
    const onLeave = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", onLeave);
    return () => window.removeEventListener("beforeunload", onLeave);
  }, [dirty]);

  /** Ask Telegram whether the token in the field is valid and may manage bots. */
  const testToken = async () => {
    setChecking(true);
    setCheck(null);
    try {
      const res = await apiFetch(`${apiBase()}/admin/telegram/test-token`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          token: txt("AION_TELEGRAM_MANAGER_TOKEN"),
          proxy_url: txt("AION_TELEGRAM_PROXY_URL"),
        }),
      });
      setCheck(res.ok ? await res.json() : { ok: false, error: "network" });
    } catch {
      setCheck({ ok: false, error: "network" });
    } finally {
      setChecking(false);
    }
  };

  if (loadFailed) {
    return (
      <div className="flex flex-col items-start gap-3">
        <Note tone="warn">
          <p className="font-medium text-foreground">{t(`${c}.load_failed`)}</p>
          <p className="mt-0.5">{t(`${c}.load_failed_hint`)}</p>
        </Note>
        <button type="button" className={outlineBtn} onClick={() => void loadSettings()}>
          <RotateCcw className="h-3.5 w-3.5" aria-hidden />
          {t(`${c}.retry`)}
        </button>
      </div>
    );
  }

  if (!baseline) {
    return (
      <div className="flex items-center gap-2 px-1 py-6 text-sm text-muted-foreground" role="status">
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
        {t(`${c}.loading`)}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-5">
      <Group
        title={t(`${c}.status`)}
        action={
          <button type="button" className={outlineBtn} onClick={() => void loadStatus()}>
            <RefreshCw className="h-3.5 w-3.5" aria-hidden />
            {t(`${c}.refresh`)}
          </button>
        }
      >
        <div className="px-5 py-4 text-sm">
          {statusFailed ? (
            <p className="text-muted-foreground">{t(`${c}.status_failed`)}</p>
          ) : !status ? (
            <p className="flex items-center gap-2 text-muted-foreground" role="status">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
              {t(`${c}.status_loading`)}
            </p>
          ) : (
            <dl className="grid gap-x-6 gap-y-3 sm:grid-cols-2">
              <StatusItem
                label={t(`${c}.st_gateway`)}
                tone={!status.enabled ? "muted" : status.connected ? "ok" : "warn"}
                value={
                  !status.enabled
                    ? t(`${c}.st_off`)
                    : status.connected
                      ? t(`${c}.st_connected`, { bot: `@${status.bot_username}` })
                      : status.token_configured
                        ? t(`${c}.st_not_connected`)
                        : t(`${c}.st_no_token`)
                }
              />
              <StatusItem
                label={t(`${c}.st_manage`)}
                tone={status.can_manage_bots === null ? "muted" : status.can_manage_bots ? "ok" : "warn"}
                value={
                  status.can_manage_bots === null
                    ? "—"
                    : status.can_manage_bots
                      ? t(`${c}.st_manage_on`)
                      : t(`${c}.st_manage_off`)
                }
              />
              <StatusItem label={t(`${c}.st_bots`)} tone={status.running ? "ok" : "muted"} value={String(status.running_bots)} />
              <StatusItem
                label={t(`${c}.st_encryption`)}
                tone={!status.enabled ? "muted" : status.encryption_ok ? "ok" : "warn"}
                value={!status.enabled ? "—" : status.encryption_ok ? t(`${c}.st_encryption_ok`) : t(`${c}.st_encryption_missing`)}
              />
            </dl>
          )}
        </div>
      </Group>

      <Group title={t(`${c}.manager`)} description={t(`${c}.manager_hint`)}>
        <ToggleList>
          <ToggleRow
            label={t(`${c}.enabled`)}
            description={t(`${c}.enabled_hint`)}
            checked={on("AION_TELEGRAM_ENABLED")}
            onChange={tog("AION_TELEGRAM_ENABLED")}
          />
        </ToggleList>
        <div className="border-t border-border/50">
          <FieldGrid>
            <Field label={t(`${c}.token`)} env="AION_TELEGRAM_MANAGER_TOKEN" hint={t(`${c}.token_hint`)} wide>
              <SecretInput
                value={txt("AION_TELEGRAM_MANAGER_TOKEN")}
                onChange={(v) => {
                  set("AION_TELEGRAM_MANAGER_TOKEN", v.trim());
                  setCheck(null);
                }}
                placeholder="123456789:AA..."
                {...secret}
              />
            </Field>
            <div className="flex flex-wrap items-center gap-x-4 gap-y-2 md:col-span-2">
              <button type="button" onClick={() => void testToken()} disabled={checking} className={outlineBtn}>
                {checking ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <Zap className="h-3.5 w-3.5" aria-hidden />}
                {t(`${c}.test`)}
              </button>
              {check ? (
                <span role="status" className={cn("text-sm", check.ok ? "text-success" : "text-destructive")}>
                  {check.ok
                    ? check.can_manage_bots
                      ? t(`${c}.test_ok`, { bot: `@${check.username}` })
                      : t(`${c}.test_ok_no_manage`, { bot: `@${check.username}` })
                    : t(`${c}.test_${check.error}`)}
                </span>
              ) : null}
            </div>
            <Field label={t(`${c}.proxy`)} env="AION_TELEGRAM_PROXY_URL" hint={t(`${c}.proxy_hint`)} wide>
              <TextInput
                value={txt("AION_TELEGRAM_PROXY_URL")}
                mono
                onChange={(v) => set("AION_TELEGRAM_PROXY_URL", v)}
                placeholder="http://proxy.example.com:3128"
              />
            </Field>
          </FieldGrid>
        </div>
      </Group>

      <Group title={t(`${c}.assistants`)} description={t(`${c}.assistants_hint`)}>
        <FieldGrid>
          <Field label={t(`${c}.default_profile`)} env="AION_TELEGRAM_DEFAULT_PROFILE" hint={t(`${c}.default_profile_hint`)}>
            <TextInput
              value={txt("AION_TELEGRAM_DEFAULT_PROFILE", "generic_assistant")}
              mono
              onChange={(v) => set("AION_TELEGRAM_DEFAULT_PROFILE", v.trim())}
            />
          </Field>
          <Field label={t(`${c}.max_bots`)} env="AION_TELEGRAM_MAX_BOTS_PER_USER">
            <TextInput type="number" inputMode="numeric" value={txt("AION_TELEGRAM_MAX_BOTS_PER_USER", "3")} onChange={(v) => set("AION_TELEGRAM_MAX_BOTS_PER_USER", v)} />
          </Field>
          <Field label={t(`${c}.blocked_profiles`)} env="AION_TELEGRAM_BLOCKED_PROFILES" hint={t(`${c}.blocked_profiles_hint`)}>
            <TextInput value={txt("AION_TELEGRAM_BLOCKED_PROFILES")} mono onChange={(v) => set("AION_TELEGRAM_BLOCKED_PROFILES", v)} placeholder="email_agent, admin_tools" />
          </Field>
          <Field label={t(`${c}.blocked_projects`)} env="AION_TELEGRAM_BLOCKED_PROJECTS" hint={t(`${c}.blocked_projects_hint`)}>
            <TextInput value={txt("AION_TELEGRAM_BLOCKED_PROJECTS")} mono onChange={(v) => set("AION_TELEGRAM_BLOCKED_PROJECTS", v)} placeholder="hr, finance" />
          </Field>
          <Field label={t(`${c}.max_running`)} env="AION_TELEGRAM_MAX_RUNNING_BOTS" hint={t(`${c}.max_running_hint`)}>
            <TextInput type="number" inputMode="numeric" value={txt("AION_TELEGRAM_MAX_RUNNING_BOTS", "200")} onChange={(v) => set("AION_TELEGRAM_MAX_RUNNING_BOTS", v)} />
          </Field>
        </FieldGrid>
        <div className="border-t border-border/50">
          <ToggleList>
            <ToggleRow
              label={t(`${c}.manager_chat`)}
              description={t(`${c}.manager_chat_hint`)}
              checked={on("AION_TELEGRAM_MANAGER_CHAT")}
              onChange={tog("AION_TELEGRAM_MANAGER_CHAT")}
            />
          </ToggleList>
        </div>
      </Group>

      <Group title={t(`${c}.chat`)} description={t(`${c}.chat_hint`)}>
        <FieldGrid>
          <Field label={t(`${c}.concurrency`)} env="AION_TELEGRAM_MAX_CONCURRENT_JOBS" hint={t(`${c}.concurrency_hint`)}>
            <TextInput type="number" inputMode="numeric" value={txt("AION_TELEGRAM_MAX_CONCURRENT_JOBS", "1")} onChange={(v) => set("AION_TELEGRAM_MAX_CONCURRENT_JOBS", v)} />
          </Field>
          <Field label={t(`${c}.turn_timeout`)} env="AION_TELEGRAM_TURN_TIMEOUT_SEC">
            <TextInput type="number" inputMode="numeric" value={txt("AION_TELEGRAM_TURN_TIMEOUT_SEC", "900")} onChange={(v) => set("AION_TELEGRAM_TURN_TIMEOUT_SEC", v)} />
          </Field>
          <Field label={t(`${c}.stream_interval`)} env="AION_TELEGRAM_STREAM_EDIT_INTERVAL_MS" hint={t(`${c}.stream_interval_hint`)}>
            <TextInput type="number" inputMode="numeric" value={txt("AION_TELEGRAM_STREAM_EDIT_INTERVAL_MS", "1000")} onChange={(v) => set("AION_TELEGRAM_STREAM_EDIT_INTERVAL_MS", v)} />
          </Field>
        </FieldGrid>
        <div className="border-t border-border/50">
          <ToggleList>
            <ToggleRow
              label={t(`${c}.show_tools`)}
              description={t(`${c}.show_tools_hint`)}
              checked={on("AION_TELEGRAM_SHOW_TOOLS", true)}
              onChange={tog("AION_TELEGRAM_SHOW_TOOLS")}
            />
            <ToggleRow
              label={t(`${c}.rich`)}
              description={t(`${c}.rich_hint`)}
              checked={on("AION_TELEGRAM_RICH_MESSAGES", true)}
              onChange={tog("AION_TELEGRAM_RICH_MESSAGES")}
            />
            <ToggleRow
              label={t(`${c}.reasoning`)}
              description={t(`${c}.reasoning_hint`)}
              checked={on("AION_TELEGRAM_SHOW_REASONING", true)}
              onChange={tog("AION_TELEGRAM_SHOW_REASONING")}
            />
          </ToggleList>
        </div>
      </Group>

      <Group title={t(`${c}.advanced`)} description={t(`${c}.advanced_hint`)}>
        <FieldGrid>
          <Field label={t(`${c}.polling_timeout`)} env="AION_TELEGRAM_POLLING_TIMEOUT">
            <TextInput type="number" inputMode="numeric" value={txt("AION_TELEGRAM_POLLING_TIMEOUT", "50")} onChange={(v) => set("AION_TELEGRAM_POLLING_TIMEOUT", v)} />
          </Field>
          <Field label={t(`${c}.pairing_ttl`)} env="AION_TELEGRAM_PAIRING_CODE_TTL_MIN">
            <TextInput type="number" inputMode="numeric" value={txt("AION_TELEGRAM_PAIRING_CODE_TTL_MIN", "15")} onChange={(v) => set("AION_TELEGRAM_PAIRING_CODE_TTL_MIN", v)} />
          </Field>
          <Field label={t(`${c}.reconcile`)} env="AION_TELEGRAM_RECONCILE_INTERVAL_MIN" hint={t(`${c}.reconcile_hint`)}>
            <TextInput type="number" inputMode="numeric" value={txt("AION_TELEGRAM_RECONCILE_INTERVAL_MIN", "30")} onChange={(v) => set("AION_TELEGRAM_RECONCILE_INTERVAL_MIN", v)} />
          </Field>
        </FieldGrid>
      </Group>

      <Note>
        {t(`${c}.apply_note`)} <Mono>AION_CREDENTIAL_ENCRYPTION_KEY</Mono>
      </Note>

      {/* Same unsaved-changes bar as Settings: it spans the content area, right of the sidebar. */}
      {dirty && (
        <div className="fixed inset-x-0 bottom-0 z-30 border-t border-border bg-background/95 px-4 py-3 lg:left-[var(--sidebar-width,0px)]">
          <div className="mx-auto flex max-w-4xl flex-wrap items-center justify-end gap-3">
            <span className="mr-auto text-sm text-muted-foreground" role="status">{t(`${c}.unsaved`)}</span>
            <button type="button" className={outlineBtn} onClick={discard} disabled={saving}>
              {t(`${c}.discard`)}
            </button>
            <button type="button" className={solidBtn} onClick={() => void save()} disabled={!canSave}>
              {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <Save className="h-3.5 w-3.5" aria-hidden />}
              {saving ? t(`${c}.saving`) : t(`${c}.save`)}
            </button>
          </div>
        </div>
      )}

      {restarting && (
        <RestartOverlay
          isOpen={restarting}
          onSuccess={() => {
            setRestarting(false);
            notify(t(`${c}.restarted`), "success");
            void loadSettings();
            void loadStatus();
            onSaved();
          }}
          onDismiss={() => setRestarting(false)}
        />
      )}
    </div>
  );
}

/** One label/value pair of the status block, with a state dot. */
function StatusItem({ label, value, tone }: { label: string; value: string; tone: "ok" | "warn" | "muted" }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="mt-0.5 flex items-center gap-2 font-medium">
        <span
          aria-hidden
          className={cn(
            "h-2 w-2 shrink-0 rounded-full",
            tone === "ok" && "bg-success",
            tone === "warn" && "bg-warning",
            tone === "muted" && "bg-muted-foreground/40",
          )}
        />
        <span className="truncate">{value}</span>
      </dd>
    </div>
  );
}
