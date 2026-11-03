"use client";

import { useCallback, useEffect, useState } from "react";
import { Loader2, RefreshCw, Zap } from "lucide-react";
import { apiFetch } from "@/lib/api/headers";
import { apiBase } from "@/lib/api";
import { cn } from "@/lib/cn";
import { outlineBtn } from "@/components/ui/classes";
import { Field, FieldGrid, Group, Mono, Note, SecretInput, SectionHead, TextInput, ToggleList, ToggleRow } from "./ui";
import { K, type SectionCtx } from "./types";

const m = `${K}.telegram`;

/** Numeric AION_TELEGRAM_* fields validated by the page before saving. */
export const TELEGRAM_POSITIVE_KEYS = [
  "AION_TELEGRAM_MAX_BOTS_PER_USER",
  "AION_TELEGRAM_MAX_RUNNING_BOTS",
  "AION_TELEGRAM_MAX_CONCURRENT_JOBS",
  "AION_TELEGRAM_TURN_TIMEOUT_SEC",
  "AION_TELEGRAM_STREAM_EDIT_INTERVAL_MS",
  "AION_TELEGRAM_POLLING_TIMEOUT",
  "AION_TELEGRAM_PAIRING_CODE_TTL_MIN",
] as const;

/** Numeric AION_TELEGRAM_* fields where 0 is allowed (feature off). */
export const TELEGRAM_NON_NEGATIVE_KEYS = ["AION_TELEGRAM_RECONCILE_INTERVAL_MIN"] as const;

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

type TokenCheck =
  | { ok: true; id: number; username: string | null; can_manage_bots: boolean }
  | { ok: false; error: "missing" | "malformed" | "unauthorized" | "network"; detail?: string };

export function TelegramSection({ t, settings, set }: SectionCtx) {
  const on = (key: string, fallback = false) => (settings[key] === undefined ? fallback : settings[key] === "1");
  const tog = (key: string) => (v: boolean) => set(key, v ? "1" : "0");
  const txt = (key: string, fallback = "") => settings[key] ?? fallback;
  const secret = { showLabel: t(`${K}.show_secret`), hideLabel: t(`${K}.hide_secret`) };

  const [status, setStatus] = useState<Status | null>(null);
  const [statusFailed, setStatusFailed] = useState(false);
  const [checking, setChecking] = useState(false);
  const [check, setCheck] = useState<TokenCheck | null>(null);

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
    void loadStatus();
  }, [loadStatus]);

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

  const enabled = on("AION_TELEGRAM_ENABLED");

  return (
    <div className="flex flex-col gap-5">
      <SectionHead title={t(`${m}.title`)} description={t(`${m}.description`)} />

      <Group
        title={t(`${m}.status`)}
        action={
          <button type="button" className={outlineBtn} onClick={() => void loadStatus()}>
            <RefreshCw className="h-3.5 w-3.5" aria-hidden />
            {t(`${m}.refresh`)}
          </button>
        }
      >
        <div className="px-5 py-4 text-sm">
          {statusFailed ? (
            <p className="text-muted-foreground">{t(`${m}.status_failed`)}</p>
          ) : !status ? (
            <p className="flex items-center gap-2 text-muted-foreground" role="status">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
              {t(`${m}.status_loading`)}
            </p>
          ) : (
            <dl className="grid gap-x-6 gap-y-3 sm:grid-cols-2">
              <StatusItem
                label={t(`${m}.st_gateway`)}
                tone={!status.enabled ? "muted" : status.connected ? "ok" : "warn"}
                value={
                  !status.enabled
                    ? t(`${m}.st_off`)
                    : status.connected
                      ? t(`${m}.st_connected`, { bot: `@${status.bot_username}` })
                      : status.token_configured
                        ? t(`${m}.st_not_connected`)
                        : t(`${m}.st_no_token`)
                }
              />
              <StatusItem
                label={t(`${m}.st_manage`)}
                tone={status.can_manage_bots === null ? "muted" : status.can_manage_bots ? "ok" : "warn"}
                value={
                  status.can_manage_bots === null
                    ? "—"
                    : status.can_manage_bots
                      ? t(`${m}.st_manage_on`)
                      : t(`${m}.st_manage_off`)
                }
              />
              <StatusItem
                label={t(`${m}.st_bots`)}
                tone={status.running ? "ok" : "muted"}
                value={String(status.running_bots)}
              />
              <StatusItem
                label={t(`${m}.st_encryption`)}
                tone={!status.enabled ? "muted" : status.encryption_ok ? "ok" : "warn"}
                value={!status.enabled ? "—" : status.encryption_ok ? t(`${m}.st_encryption_ok`) : t(`${m}.st_encryption_missing`)}
              />
            </dl>
          )}
        </div>
      </Group>

      <Group title={t(`${m}.manager`)} description={t(`${m}.manager_hint`)}>
        <ToggleList>
          <ToggleRow
            label={t(`${m}.enabled`)}
            description={t(`${m}.enabled_hint`)}
            checked={enabled}
            onChange={tog("AION_TELEGRAM_ENABLED")}
          />
        </ToggleList>
        <div className="border-t border-border/50">
          <FieldGrid>
            <Field label={t(`${m}.token`)} env="AION_TELEGRAM_MANAGER_TOKEN" hint={t(`${m}.token_hint`)} wide>
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
                {t(`${m}.test`)}
              </button>
              {check ? (
                <span role="status" className={cn("text-sm", check.ok ? "text-success" : "text-destructive")}>
                  {check.ok
                    ? check.can_manage_bots
                      ? t(`${m}.test_ok`, { bot: `@${check.username}` })
                      : t(`${m}.test_ok_no_manage`, { bot: `@${check.username}` })
                    : t(`${m}.test_${check.error}`)}
                </span>
              ) : null}
            </div>
            <Field label={t(`${m}.proxy`)} env="AION_TELEGRAM_PROXY_URL" hint={t(`${m}.proxy_hint`)} wide>
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

      <Group title={t(`${m}.assistants`)} description={t(`${m}.assistants_hint`)}>
        <FieldGrid>
          <Field label={t(`${m}.default_profile`)} env="AION_TELEGRAM_DEFAULT_PROFILE" hint={t(`${m}.default_profile_hint`)}>
            <TextInput
              value={txt("AION_TELEGRAM_DEFAULT_PROFILE", "generic_assistant")}
              mono
              onChange={(v) => set("AION_TELEGRAM_DEFAULT_PROFILE", v.trim())}
            />
          </Field>
          <Field label={t(`${m}.max_bots`)} env="AION_TELEGRAM_MAX_BOTS_PER_USER">
            <TextInput type="number" inputMode="numeric" value={txt("AION_TELEGRAM_MAX_BOTS_PER_USER", "3")} onChange={(v) => set("AION_TELEGRAM_MAX_BOTS_PER_USER", v)} />
          </Field>
          <Field label={t(`${m}.blocked_profiles`)} env="AION_TELEGRAM_BLOCKED_PROFILES" hint={t(`${m}.blocked_profiles_hint`)}>
            <TextInput value={txt("AION_TELEGRAM_BLOCKED_PROFILES")} mono onChange={(v) => set("AION_TELEGRAM_BLOCKED_PROFILES", v)} placeholder="email_agent, admin_tools" />
          </Field>
          <Field label={t(`${m}.blocked_projects`)} env="AION_TELEGRAM_BLOCKED_PROJECTS" hint={t(`${m}.blocked_projects_hint`)}>
            <TextInput value={txt("AION_TELEGRAM_BLOCKED_PROJECTS")} mono onChange={(v) => set("AION_TELEGRAM_BLOCKED_PROJECTS", v)} placeholder="hr, finance" />
          </Field>
          <Field label={t(`${m}.max_running`)} env="AION_TELEGRAM_MAX_RUNNING_BOTS" hint={t(`${m}.max_running_hint`)}>
            <TextInput type="number" inputMode="numeric" value={txt("AION_TELEGRAM_MAX_RUNNING_BOTS", "200")} onChange={(v) => set("AION_TELEGRAM_MAX_RUNNING_BOTS", v)} />
          </Field>
        </FieldGrid>
        <div className="border-t border-border/50">
          <ToggleList>
            <ToggleRow
              label={t(`${m}.manager_chat`)}
              description={t(`${m}.manager_chat_hint`)}
              checked={on("AION_TELEGRAM_MANAGER_CHAT")}
              onChange={tog("AION_TELEGRAM_MANAGER_CHAT")}
            />
          </ToggleList>
        </div>
      </Group>

      <Group title={t(`${m}.chat`)} description={t(`${m}.chat_hint`)}>
        <FieldGrid>
          <Field label={t(`${m}.concurrency`)} env="AION_TELEGRAM_MAX_CONCURRENT_JOBS" hint={t(`${m}.concurrency_hint`)}>
            <TextInput type="number" inputMode="numeric" value={txt("AION_TELEGRAM_MAX_CONCURRENT_JOBS", "1")} onChange={(v) => set("AION_TELEGRAM_MAX_CONCURRENT_JOBS", v)} />
          </Field>
          <Field label={t(`${m}.turn_timeout`)} env="AION_TELEGRAM_TURN_TIMEOUT_SEC">
            <TextInput type="number" inputMode="numeric" value={txt("AION_TELEGRAM_TURN_TIMEOUT_SEC", "900")} onChange={(v) => set("AION_TELEGRAM_TURN_TIMEOUT_SEC", v)} />
          </Field>
          <Field label={t(`${m}.stream_interval`)} env="AION_TELEGRAM_STREAM_EDIT_INTERVAL_MS" hint={t(`${m}.stream_interval_hint`)}>
            <TextInput type="number" inputMode="numeric" value={txt("AION_TELEGRAM_STREAM_EDIT_INTERVAL_MS", "1000")} onChange={(v) => set("AION_TELEGRAM_STREAM_EDIT_INTERVAL_MS", v)} />
          </Field>
        </FieldGrid>
        <div className="border-t border-border/50">
          <ToggleList>
            <ToggleRow
              label={t(`${m}.show_tools`)}
              description={t(`${m}.show_tools_hint`)}
              checked={on("AION_TELEGRAM_SHOW_TOOLS", true)}
              onChange={tog("AION_TELEGRAM_SHOW_TOOLS")}
            />
            <ToggleRow
              label={t(`${m}.rich`)}
              description={t(`${m}.rich_hint`)}
              checked={on("AION_TELEGRAM_RICH_MESSAGES", true)}
              onChange={tog("AION_TELEGRAM_RICH_MESSAGES")}
            />
            <ToggleRow
              label={t(`${m}.reasoning`)}
              description={t(`${m}.reasoning_hint`)}
              checked={on("AION_TELEGRAM_SHOW_REASONING", true)}
              onChange={tog("AION_TELEGRAM_SHOW_REASONING")}
            />
          </ToggleList>
        </div>
      </Group>

      <Group title={t(`${m}.advanced`)} description={t(`${m}.advanced_hint`)}>
        <FieldGrid>
          <Field label={t(`${m}.polling_timeout`)} env="AION_TELEGRAM_POLLING_TIMEOUT">
            <TextInput type="number" inputMode="numeric" value={txt("AION_TELEGRAM_POLLING_TIMEOUT", "50")} onChange={(v) => set("AION_TELEGRAM_POLLING_TIMEOUT", v)} />
          </Field>
          <Field label={t(`${m}.pairing_ttl`)} env="AION_TELEGRAM_PAIRING_CODE_TTL_MIN">
            <TextInput type="number" inputMode="numeric" value={txt("AION_TELEGRAM_PAIRING_CODE_TTL_MIN", "15")} onChange={(v) => set("AION_TELEGRAM_PAIRING_CODE_TTL_MIN", v)} />
          </Field>
          <Field label={t(`${m}.reconcile`)} env="AION_TELEGRAM_RECONCILE_INTERVAL_MIN" hint={t(`${m}.reconcile_hint`)}>
            <TextInput type="number" inputMode="numeric" value={txt("AION_TELEGRAM_RECONCILE_INTERVAL_MIN", "30")} onChange={(v) => set("AION_TELEGRAM_RECONCILE_INTERVAL_MIN", v)} />
          </Field>
        </FieldGrid>
      </Group>

      <Note>
        {t(`${m}.apply_note`)} <Mono>AION_CREDENTIAL_ENCRYPTION_KEY</Mono>
      </Note>
    </div>
  );
}

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
