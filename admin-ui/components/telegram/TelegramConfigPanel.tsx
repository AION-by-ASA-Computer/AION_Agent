"use client";

/**
 * "Configuration" section of the admin Telegram page (formerly Settings → Telegram):
 * live gateway status, manager-bot token, channel policies and chat behaviour.
 *
 * The configuration is stored encrypted in the DB through `GET/PUT
 * /admin/telegram/settings` (no `.env` variable is involved). The panel keeps the
 * values as strings keyed by field name for the inputs, and on save sends only the
 * fields that differ from the loaded baseline, converted back to their JSON type.
 * Saving restarts only the Telegram gateway inside the API process, so there is no
 * container restart to wait for: the status block is refreshed shortly after.
 *
 * The manager token is write-only: the API returns just whether it is set and its
 * last 4 characters, so the field starts empty and a blank field keeps the saved token.
 *
 * The page shows the form one tab at a time (`section`), but this component stays mounted
 * on every tab: the edits, the unsaved-changes bar and the Ctrl/Cmd+S shortcut belong to
 * the whole form, so switching tab (or opening the lists) never discards what was typed.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { Loader2, RefreshCw, RotateCcw, Save, Zap } from "lucide-react";
import { apiFetch } from "@/lib/api/headers";
import { apiBase } from "@/lib/api";
import { cn } from "@/lib/cn";
import { Field, FieldGrid, Group, Mono, Note, SecretInput, TextInput, ToggleList, ToggleRow } from "@/components/settings/ui";
import { outlineBtn, solidBtn } from "@/components/ui/classes";
import { Select } from "@/components/ui/Select";
import { k, type Notify, type T } from "./shared";

const c = `${k}.config`;

/** Input values keyed by field name (booleans as "1"/"0", numbers as text). */
type Settings = Record<string, string>;

/** `GET /admin/telegram/settings`: saved values, the token only as presence + hint. */
type SavedConfig = {
  settings: Record<string, string | number | boolean | null>;
  manager_token_present: boolean;
  manager_token_hint: string | null;
  configured: boolean;
  updated_at: string | null;
};

/** Tabs of the page that show a slice of this form. */
export type ConfigSection = "connection" | "policies" | "chat";

/** Which form fields live in which tab, to flag the tabs holding unsaved edits. */
const SECTION_KEYS: Record<ConfigSection, string[]> = {
  connection: ["enabled", "manager_token", "proxy_url", "delivery_mode"],
  policies: ["default_profile", "max_bots_per_user", "allowed_profiles", "allowed_projects", "max_running_bots", "manager_chat"],
  chat: [
    "max_concurrent_jobs",
    "turn_timeout_sec",
    "stream_edit_interval_ms",
    "show_tools",
    "rich_messages",
    "show_reasoning",
    "default_thinking_level",
    "max_outbound_files",
    "polling_timeout",
    "pairing_code_ttl_min",
    "reconcile_interval_min",
  ],
};

const BOOL_KEYS = ["enabled", "manager_chat", "show_tools", "rich_messages", "show_reasoning"];

/** Server values → input strings. */
function toInputs(values: SavedConfig["settings"]): Settings {
  const out: Settings = { manager_token: "" };
  for (const [key, v] of Object.entries(values)) {
    out[key] = typeof v === "boolean" ? (v ? "1" : "0") : v == null ? "" : String(v);
  }
  return out;
}

/**
 * Input string → JSON value for `PUT /admin/telegram/settings`. A blank number goes back
 * to the server default (`null`); a blank token is never sent (keeps the saved one).
 */
function toPayloadValue(key: string, v: string): string | number | boolean | null {
  if (BOOL_KEYS.includes(key)) return v === "1";
  if ((NUMBER_KEYS as readonly string[]).includes(key)) return v.trim() === "" ? null : Number(v);
  return v;
}

/** Numeric fields that must be integers > 0 when set. */
const POSITIVE_KEYS = [
  "max_bots_per_user",
  "max_running_bots",
  "max_concurrent_jobs",
  "turn_timeout_sec",
  "stream_edit_interval_ms",
  "polling_timeout",
  "pairing_code_ttl_min",
] as const;

/** Numeric fields where 0 is allowed (0 turns the feature off). */
const NON_NEGATIVE_KEYS = ["reconcile_interval_min", "max_outbound_files"] as const;

const NUMBER_KEYS = [...POSITIVE_KEYS, ...NON_NEGATIVE_KEYS] as const;

const isPositive = (v: string | undefined) => {
  if (!v) return true;
  const n = parseInt(v, 10);
  return !isNaN(n) && n > 0;
};
const isNonNegative = (v: string | undefined) => !v || /^\d+$/.test(v.trim());

/** CSV of slugs (as stored by the backend) → normalised, de-duplicated list. */
const parseSlugs = (csv: string) => [...new Set(csv.split(",").map((x) => x.trim().toLowerCase()).filter(Boolean))];
/** Slug list → CSV, sorted so the same selection always yields the same value (stable dirty diff). */
const joinSlugs = (slugs: string[]) => [...new Set(slugs)].sort().join(",");

/** One selectable entry of a {@link SlugChecklist}. */
type SlugOption = { slug: string; label: string; description?: string };

/**
 * Checkbox list backing a CSV allowlist field (`allowed_profiles` / `allowed_projects`).
 * The backend applies it as a strict allowlist, so nothing checked means nothing usable on
 * Telegram. Saved slugs that no longer match an option stay listed (checked, by slug) so the
 * admin can still see and remove them. Not wrapped in `Field`: that renders a `<label>`, which
 * cannot contain the per-row labels of the checkboxes.
 *
 * @param value    the current CSV value of the field.
 * @param onChange receives the new CSV (sorted) on every toggle.
 * @param empty    text shown when there are no options at all.
 */
function SlugChecklist({
  t,
  label,
  hint,
  empty,
  options,
  value,
  onChange,
}: {
  t: T;
  label: string;
  hint: string;
  empty: string;
  options: SlugOption[];
  value: string;
  onChange: (csv: string) => void;
}) {
  const selected = parseSlugs(value);
  const known = new Set(options.map((o) => o.slug.toLowerCase()));
  const rows: SlugOption[] = [
    ...options,
    ...selected.filter((slug) => !known.has(slug)).map((slug) => ({ slug, label: slug })),
  ];
  const toggle = (slug: string) => {
    const s = slug.toLowerCase();
    onChange(joinSlugs(selected.includes(s) ? selected.filter((x) => x !== s) : [...selected, s]));
  };

  return (
    <div className="flex min-w-0 flex-col gap-1.5 md:col-span-2">
      <div className="flex items-center justify-between gap-3">
        <span className="text-sm font-medium">{label}</span>
        <span className="flex items-center gap-3 text-xs text-muted-foreground">
          <span>{t(`${c}.allowed_count`, { count: selected.length })}</span>
          {options.length > 0 && (
            <button
              type="button"
              onClick={() => onChange(joinSlugs([...selected, ...options.map((o) => o.slug.toLowerCase())]))}
              className="focus-ring rounded-md font-medium underline underline-offset-4 hover:text-foreground"
            >
              {t(`${c}.select_all`)}
            </button>
          )}
          {selected.length > 0 && (
            <button type="button" onClick={() => onChange("")} className="focus-ring rounded-md font-medium underline underline-offset-4 hover:text-foreground">
              {t(`${c}.select_none`)}
            </button>
          )}
        </span>
      </div>
      {rows.length === 0 ? (
        <p className="rounded-xl border border-border/60 px-3 py-4 text-center text-sm text-muted-foreground">{empty}</p>
      ) : (
        <ul className="flex max-h-[18rem] flex-col gap-0.5 overflow-y-auto rounded-xl border border-border/60 p-1">
          {rows.map((o) => {
            const on = selected.includes(o.slug.toLowerCase());
            return (
              <li key={o.slug}>
                <label className={cn("flex cursor-pointer items-start gap-3 rounded-lg px-3 py-2 transition-colors", on ? "bg-secondary" : "hover:bg-secondary/60")}>
                  <input type="checkbox" checked={on} onChange={() => toggle(o.slug)} className="focus-ring mt-1 h-4 w-4 shrink-0 accent-foreground" />
                  <span className="min-w-0">
                    <span className="block truncate text-sm font-medium">{o.label}</span>
                    {o.description && <span className="mt-0.5 block text-xs text-muted-foreground">{o.description}</span>}
                  </span>
                </label>
              </li>
            );
          })}
        </ul>
      )}
      <p className="text-xs text-muted-foreground">{hint}</p>
    </div>
  );
}

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
  delivery_mode: "polling" | "webhook";
  /** Webhook diagnostics; present only with the channel on in webhook mode. */
  webhook: {
    /** URL AION registers (public API base + /v1/channels/telegram/webhook/<bot id>). */
    url: string | null;
    /** Why the webhook cannot work (no public HTTPS URL, setWebhook error), or null. */
    problem: string | null;
    /** What Telegram reports (getWebhookInfo); null when unreachable. */
    telegram: {
      url: string | null;
      pending_update_count: number;
      last_error_message: string | null;
      last_error_date: string | null;
    } | null;
  } | null;
};

/** `POST /admin/telegram/test-token`: checks the token typed in the field, before saving. */
type TokenCheck =
  | { ok: true; id: number; username: string | null; can_manage_bots: boolean }
  | { ok: false; error: "missing" | "malformed" | "unauthorized" | "network"; detail?: string };

/**
 * @param section        the tab currently shown, or `null` when a list tab is open (the form
 *                       stays mounted but hidden).
 * @param onSaved        called after a successful save so the page can reload the lists that
 *                       depend on the config (default quota, running bots).
 * @param onDirtySections called whenever the set of tabs with unsaved edits changes.
 */
export function TelegramConfigPanel({
  t,
  notify,
  section,
  onSaved,
  onDirtySections,
}: {
  t: T;
  notify: Notify;
  section: ConfigSection | null;
  onSaved: () => void;
  onDirtySections: (sections: ConfigSection[]) => void;
}) {
  const [settings, setSettings] = useState<Settings>({});
  const [baseline, setBaseline] = useState<Settings | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [saving, setSaving] = useState(false);
  const [tokenHint, setTokenHint] = useState<string | null>(null);

  const [status, setStatus] = useState<Status | null>(null);
  const [statusFailed, setStatusFailed] = useState(false);
  const [checking, setChecking] = useState(false);
  const [check, setCheck] = useState<TokenCheck | null>(null);

  const loadSettings = useCallback(async () => {
    try {
      const res = await apiFetch(`${apiBase()}/admin/telegram/settings`);
      if (!res.ok) throw new Error(String(res.status));
      const saved: SavedConfig = await res.json();
      const s = toInputs(saved.settings || {});
      setTokenHint(saved.manager_token_present ? saved.manager_token_hint || "••••" : null);
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

  // Profiles available as the suggested/default one, for the select in Policies.
  // A failed fetch leaves the list empty: the select then still shows the saved value.
  const [profiles, setProfiles] = useState<{ slug: string; name: string; description?: string }[]>([]);
  useEffect(() => {
    apiFetch(`${apiBase()}/admin/profiles`)
      .then((r) => (r.ok ? r.json() : Promise.reject(r)))
      .then((d) => Array.isArray(d) && setProfiles(d.filter((p) => p?.slug)))
      .catch(() => {});
  }, []);

  // SQL QueryMemory projects of the tenant, for the projects allowlist (empty when the
  // feature is disabled or the fetch fails: saved slugs are still shown by the checklist).
  const [projects, setProjects] = useState<{ slug: string; display_name?: string; profile_slug?: string | null }[]>([]);
  useEffect(() => {
    apiFetch(`${apiBase()}/admin/query-memory/projects`)
      .then((r) => (r.ok ? r.json() : Promise.reject(r)))
      .then((d) => Array.isArray(d) && setProjects(d.filter((p) => p?.slug)))
      .catch(() => {});
  }, []);

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
  const canSave = dirty && !saving;

  // Tell the page which tabs hold edits, so their labels can carry an "unsaved" dot.
  const dirtySections = useMemo(() => {
    if (!baseline) return [] as ConfigSection[];
    return (Object.keys(SECTION_KEYS) as ConfigSection[]).filter((sec) =>
      SECTION_KEYS[sec].some((key) => (baseline[key] ?? "") !== (settings[key] ?? "")),
    );
  }, [baseline, settings]);
  const dirtySectionsKey = dirtySections.join(",");
  useEffect(() => {
    onDirtySections(dirtySectionsKey ? (dirtySectionsKey.split(",") as ConfigSection[]) : []);
  }, [dirtySectionsKey, onDirtySections]);

  /** Client-side checks mirroring the backend's expectations; returns the first problem. */
  const validate = (): string | null => {
    for (const key of POSITIVE_KEYS) if (!isPositive(settings[key])) return t(`${c}.v_number`, { key });
    for (const key of NON_NEGATIVE_KEYS) if (!isNonNegative(settings[key])) return t(`${c}.v_non_negative`, { key });
    const proxy = (settings.proxy_url || "").trim();
    if (proxy && !/^(https?|socks[45]h?):\/\//.test(proxy)) return t(`${c}.v_proxy`);
    return null;
  };

  const save = useCallback(async () => {
    const problem = validate();
    if (problem) return notify(problem, "error");
    setSaving(true);
    try {
      // Only the edited fields: see the module header.
      const payload: Record<string, string | number | boolean | null> = {};
      for (const [key, v] of Object.entries(settings)) {
        if ((baseline?.[key] ?? "") === v) continue;
        if (key === "manager_token" && !v.trim()) continue;
        payload[key] = toPayloadValue(key, v);
      }
      const res = await apiFetch(`${apiBase()}/admin/telegram/settings`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        const detail = err.detail;
        notify(
          detail?.code === "invalid_setting"
            ? t(`${c}.v_invalid`, { key: detail.field ?? "?" })
            : detail?.code === "encryption_unavailable"
              ? t(`${c}.st_encryption_missing`)
              : t(`${c}.err_save`),
          "error",
        );
        return;
      }
      const data: { changed: string[]; restarting_gateway: boolean } = await res.json();
      notify(t(`${c}.saved`), "success");
      setCheck(null);
      await loadSettings();
      void loadStatus();
      // The gateway restarts in background (stop + getMe): look again once it is up.
      if (data.restarting_gateway) window.setTimeout(() => void loadStatus(), 4000);
      onSaved();
    } catch {
      notify(t(`${c}.err_network`), "error");
    } finally {
      setSaving(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settings, baseline, loadSettings, loadStatus, notify, onSaved, t]);

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
          token: txt("manager_token"),
          proxy_url: txt("proxy_url"),
        }),
      });
      setCheck(res.ok ? await res.json() : { ok: false, error: "network" });
    } catch {
      setCheck({ ok: false, error: "network" });
    } finally {
      setChecking(false);
    }
  };

  // Nothing to render while a list tab is open and the form is not ready.
  if (loadFailed && section === null) return null;
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

  if (!baseline && section === null) return null;
  if (!baseline) {
    return (
      <div className="flex items-center gap-2 px-1 py-6 text-sm text-muted-foreground" role="status">
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
        {t(`${c}.loading`)}
      </div>
    );
  }

  return (
    <>
      {/* Connection: is the gateway up, and the manager bot it runs on. */}
      <div hidden={section !== "connection"} className="flex flex-col gap-5">
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
                <StatusItem
                  label={t(`${c}.st_delivery`)}
                  tone={!status.enabled ? "muted" : status.webhook?.problem ? "warn" : "ok"}
                  value={t(`${c}.delivery_${status.delivery_mode}`)}
                />
              </dl>
            )}
            {/* Webhook mode: the registered URL and Telegram's own delivery report,
                the quickest way to see why updates do not arrive (tunnel down, DNS). */}
            {status?.webhook ? (
              <div className="mt-4 space-y-1 border-t border-border/50 pt-3 text-xs">
                <p className="text-muted-foreground">
                  {t(`${c}.wh_url`)} <Mono>{status.webhook.url || "—"}</Mono>
                </p>
                {status.webhook.problem ? <p className="text-destructive">{status.webhook.problem}</p> : null}
                {status.webhook.telegram ? (
                  <>
                    {status.webhook.telegram.url !== status.webhook.url ? (
                      <p className="text-warning">
                        {t(`${c}.wh_telegram_url`)} <Mono>{status.webhook.telegram.url || "—"}</Mono>
                      </p>
                    ) : null}
                    <p className="text-muted-foreground">
                      {t(`${c}.wh_pending`, { count: String(status.webhook.telegram.pending_update_count) })}
                    </p>
                    {status.webhook.telegram.last_error_message ? (
                      <p className="text-warning">
                        {t(`${c}.wh_last_error`, {
                          error: status.webhook.telegram.last_error_message,
                          date: status.webhook.telegram.last_error_date
                            ? new Date(status.webhook.telegram.last_error_date).toLocaleString()
                            : "—",
                        })}
                      </p>
                    ) : null}
                  </>
                ) : null}
              </div>
            ) : null}
          </div>
        </Group>

        <Group title={t(`${c}.manager`)} description={t(`${c}.manager_hint`)}>
          <ToggleList>
            <ToggleRow
              label={t(`${c}.enabled`)}
              description={t(`${c}.enabled_hint`)}
              checked={on("enabled")}
              onChange={tog("enabled")}
            />
          </ToggleList>
          <div className="border-t border-border/50">
            <FieldGrid>
              <Field label={t(`${c}.token`)} hint={t(`${c}.token_hint`)} wide>
                <SecretInput
                  value={txt("manager_token")}
                  onChange={(v) => {
                    set("manager_token", v.trim());
                    setCheck(null);
                  }}
                  placeholder={tokenHint ? t(`${c}.token_saved`, { hint: tokenHint }) : "123456789:AA..."}
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
              <Field label={t(`${c}.proxy`)} hint={t(`${c}.proxy_hint`)} wide>
                <TextInput
                  value={txt("proxy_url")}
                  mono
                  onChange={(v) => set("proxy_url", v)}
                  placeholder="http://proxy.example.com:3128"
                />
              </Field>
              {/* Polling works everywhere; webhook needs a public HTTPS URL for the API
                  (domain, or the tunnel of scripts/whatsapp-tunnel.sh). */}
              <Field label={t(`${c}.delivery`)} hint={t(`${c}.delivery_hint`)} wide>
                <Select
                  value={txt("delivery_mode", "polling")}
                  onChange={(v) => set("delivery_mode", v)}
                  options={[
                    { value: "polling", label: t(`${c}.delivery_polling`) },
                    { value: "webhook", label: t(`${c}.delivery_webhook`) },
                  ]}
                />
              </Field>
            </FieldGrid>
          </div>
        </Group>

        <Note>
          {t(`${c}.apply_note`)} <Mono>AION_CREDENTIAL_ENCRYPTION_KEY</Mono>
        </Note>
      </div>

      {/* Policies: what personal assistants may be created and by how many. */}
      <div hidden={section !== "policies"} className="flex flex-col gap-5">
        <Group title={t(`${c}.assistants`)} description={t(`${c}.assistants_hint`)}>
          <FieldGrid>
            <Field label={t(`${c}.default_profile`)} hint={t(`${c}.default_profile_hint`)}>
              <Select
                value={txt("default_profile", "generic_assistant")}
                onChange={(v) => set("default_profile", v)}
                placeholder={t(`${c}.default_profile`)}
                options={(() => {
                  const cur = txt("default_profile", "generic_assistant");
                  const opts = profiles.map((p) => ({
                    value: p.slug,
                    label: p.name || p.slug,
                    description: p.description || undefined,
                  }));
                  // Keep a saved value that no longer matches an existing profile selectable.
                  if (cur && !opts.some((o) => o.value === cur)) opts.unshift({ value: cur, label: cur, description: undefined });
                  return opts;
                })()}
              />
            </Field>
            <Field label={t(`${c}.max_bots`)}>
              <TextInput type="number" inputMode="numeric" value={txt("max_bots_per_user", "3")} onChange={(v) => set("max_bots_per_user", v)} />
            </Field>
            <Field label={t(`${c}.max_running`)} hint={t(`${c}.max_running_hint`)}>
              <TextInput type="number" inputMode="numeric" value={txt("max_running_bots", "200")} onChange={(v) => set("max_running_bots", v)} />
            </Field>
            {/* Strict allowlists: the backend refuses anything not checked here. Warn when no
                profile is allowed (no assistant can be created) or when the suggested profile
                is not allowed (it would never be offered in /newbot). */}
            {(() => {
              const allowed = parseSlugs(txt("allowed_profiles"));
              const def = txt("default_profile", "generic_assistant").toLowerCase();
              const msg = allowed.length === 0 ? "none_allowed" : def && !allowed.includes(def) ? "default_not_allowed" : null;
              return msg ? (
                <div className="md:col-span-2">
                  <Note tone="warn">{t(`${c}.${msg}`)}</Note>
                </div>
              ) : null;
            })()}
            <SlugChecklist
              t={t}
              label={t(`${c}.allowed_profiles`)}
              hint={t(`${c}.allowed_profiles_hint`)}
              empty={t(`${c}.no_profiles`)}
              options={profiles.map((p) => ({ slug: p.slug, label: p.name || p.slug, description: p.description || undefined }))}
              value={txt("allowed_profiles")}
              onChange={(v) => set("allowed_profiles", v)}
            />
            <SlugChecklist
              t={t}
              label={t(`${c}.allowed_projects`)}
              hint={t(`${c}.allowed_projects_hint`)}
              empty={t(`${c}.no_projects`)}
              options={projects.map((p) => ({
                slug: p.slug,
                label: p.display_name || p.slug,
                description: p.profile_slug ? `${p.slug} · ${p.profile_slug}` : p.slug,
              }))}
              value={txt("allowed_projects")}
              onChange={(v) => set("allowed_projects", v)}
            />
          </FieldGrid>
          <div className="border-t border-border/50">
            <ToggleList>
              <ToggleRow
                label={t(`${c}.manager_chat`)}
                description={t(`${c}.manager_chat_hint`)}
                checked={on("manager_chat")}
                onChange={tog("manager_chat")}
              />
            </ToggleList>
          </div>
        </Group>
      </div>

      {/* Chat: how replies look in Telegram, plus the low-level timings. */}
      <div hidden={section !== "chat"} className="flex flex-col gap-5">
        <Group title={t(`${c}.chat`)} description={t(`${c}.chat_hint`)}>
          <FieldGrid>
            <Field label={t(`${c}.concurrency`)} hint={t(`${c}.concurrency_hint`)}>
              <TextInput type="number" inputMode="numeric" value={txt("max_concurrent_jobs", "1")} onChange={(v) => set("max_concurrent_jobs", v)} />
            </Field>
            <Field label={t(`${c}.turn_timeout`)}>
              <TextInput type="number" inputMode="numeric" value={txt("turn_timeout_sec", "900")} onChange={(v) => set("turn_timeout_sec", v)} />
            </Field>
            <Field label={t(`${c}.stream_interval`)} hint={t(`${c}.stream_interval_hint`)}>
              <TextInput type="number" inputMode="numeric" value={txt("stream_edit_interval_ms", "1000")} onChange={(v) => set("stream_edit_interval_ms", v)} />
            </Field>
            <Field label={t(`${c}.outbound_files`)} hint={t(`${c}.outbound_files_hint`)}>
              <TextInput type="number" inputMode="numeric" value={txt("max_outbound_files", "5")} onChange={(v) => set("max_outbound_files", v)} />
            </Field>
            {/* Same levels as WhatsApp; blank = system default. Mirrored into the
                conversation so the chat-ui composer shows what the turn used. */}
            <Field label={t(`${c}.thinking`)} hint={t(`${c}.thinking_hint`)} wide>
              <Select
                value={txt("default_thinking_level", "")}
                onChange={(v) => set("default_thinking_level", v)}
                options={[
                  { value: "", label: t(`${c}.thinking_default`) },
                  { value: "off", label: t(`${c}.thinking_off`) },
                  { value: "min", label: t(`${c}.thinking_min`) },
                  { value: "medium", label: t(`${c}.thinking_medium`) },
                  { value: "max", label: t(`${c}.thinking_max`) },
                ]}
              />
            </Field>
          </FieldGrid>
          <div className="border-t border-border/50">
            <ToggleList>
              <ToggleRow
                label={t(`${c}.show_tools`)}
                description={t(`${c}.show_tools_hint`)}
                checked={on("show_tools", true)}
                onChange={tog("show_tools")}
              />
              <ToggleRow
                label={t(`${c}.rich`)}
                description={t(`${c}.rich_hint`)}
                checked={on("rich_messages", true)}
                onChange={tog("rich_messages")}
              />
              <ToggleRow
                label={t(`${c}.reasoning`)}
                description={t(`${c}.reasoning_hint`)}
                checked={on("show_reasoning", true)}
                onChange={tog("show_reasoning")}
              />
            </ToggleList>
          </div>
        </Group>

        <Group title={t(`${c}.advanced`)} description={t(`${c}.advanced_hint`)}>
          <FieldGrid>
            <Field label={t(`${c}.polling_timeout`)}>
              <TextInput type="number" inputMode="numeric" value={txt("polling_timeout", "50")} onChange={(v) => set("polling_timeout", v)} />
            </Field>
            <Field label={t(`${c}.pairing_ttl`)}>
              <TextInput type="number" inputMode="numeric" value={txt("pairing_code_ttl_min", "15")} onChange={(v) => set("pairing_code_ttl_min", v)} />
            </Field>
            <Field label={t(`${c}.reconcile`)} hint={t(`${c}.reconcile_hint`)}>
              <TextInput type="number" inputMode="numeric" value={txt("reconcile_interval_min", "30")} onChange={(v) => set("reconcile_interval_min", v)} />
            </Field>
          </FieldGrid>
        </Group>
      </div>

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
    </>
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
