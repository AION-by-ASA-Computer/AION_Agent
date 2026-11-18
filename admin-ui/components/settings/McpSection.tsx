"use client";

/**
 * Settings -> MCPs: runtime settings of customer-built (custom) MCP servers.
 *
 * Edits the `AION_CUSTOM_MCP_*` variables through the page-level save bar
 * (`POST /admin/settings`, stored as runtime overrides in the data volume). The
 * backend applies them without a restart (src/api/settings_api.py, hot-reload
 * prefix) and restarts running custom servers so new limits and the kill switch
 * take effect. Read on every call by src/mcp_custom/settings.py and the jail
 * policy (src/security/container_policy.py).
 *
 * `AION_CUSTOM_MCP_ALLOW_UNSANDBOXED` (servers without the container jail) is
 * shown read-only: the backend refuses to change it from the web panel.
 */

import { Field, FieldGrid, Group, Mono, Note, SectionHead, TextInput, ToggleList, ToggleRow } from "./ui";
import { K, type SectionCtx } from "./types";

const m = `${K}.mcp`;

/** Numeric/text limits: env key, i18n suffix and the default the backend uses when empty. */
const LIMITS: { key: string; id: string; placeholder: string }[] = [
  { key: "AION_CUSTOM_MCP_MAX_UPLOAD_MB", id: "max_upload_mb", placeholder: "20" },
  { key: "AION_CUSTOM_MCP_MAX_FILES", id: "max_files", placeholder: "500" },
  { key: "AION_CUSTOM_MCP_KEEP_VERSIONS", id: "keep_versions", placeholder: "3" },
  { key: "AION_CUSTOM_MCP_BUILD_TIMEOUT", id: "build_timeout", placeholder: "300" },
  { key: "AION_CUSTOM_MCP_PROBE_TIMEOUT", id: "probe_timeout", placeholder: "90" },
];

const CONTAINER: { key: string; id: string; placeholder: string }[] = [
  { key: "AION_CUSTOM_MCP_MEMORY", id: "memory", placeholder: "512m" },
  { key: "AION_CUSTOM_MCP_CPUS", id: "cpus", placeholder: "1.0" },
  { key: "AION_CUSTOM_MCP_PIDS", id: "pids", placeholder: "128" },
];

/** Integer keys that must be positive, checked by the settings page before saving. */
export const MCP_INT_KEYS = [
  "AION_CUSTOM_MCP_MAX_UPLOAD_MB",
  "AION_CUSTOM_MCP_MAX_FILES",
  "AION_CUSTOM_MCP_BUILD_TIMEOUT",
  "AION_CUSTOM_MCP_PROBE_TIMEOUT",
  "AION_CUSTOM_MCP_PIDS",
];

export function McpSection({ t, settings, set }: SectionCtx) {
  const on = (key: string) => ["1", "true", "yes", "on"].includes((settings[key] || "").trim().toLowerCase());
  const tog = (key: string) => (v: boolean) => set(key, v ? "1" : "0");
  const txt = (key: string) => settings[key] ?? "";
  const unsandboxed = on("AION_CUSTOM_MCP_ALLOW_UNSANDBOXED");

  return (
    <div className="flex flex-col gap-5">
      <SectionHead title={t(`${m}.title`)} description={t(`${m}.description`)} />

      <Group title={t(`${m}.access`)} description={t(`${m}.access_hint`)}>
        <ToggleList>
          <ToggleRow
            label={t(`${m}.enabled`)}
            description={t(`${m}.enabled_hint`)}
            checked={on("AION_CUSTOM_MCP_ENABLED")}
            onChange={tog("AION_CUSTOM_MCP_ENABLED")}
          />
          <ToggleRow
            label={t(`${m}.force_disable`)}
            description={t(`${m}.force_disable_hint`)}
            checked={on("AION_CUSTOM_MCP_FORCE_DISABLE")}
            onChange={tog("AION_CUSTOM_MCP_FORCE_DISABLE")}
          />
          <ToggleRow
            label={t(`${m}.source_builds`)}
            description={t(`${m}.source_builds_hint`)}
            checked={on("AION_CUSTOM_MCP_ALLOW_SOURCE_BUILDS")}
            onChange={tog("AION_CUSTOM_MCP_ALLOW_SOURCE_BUILDS")}
          />
        </ToggleList>
        <div className="px-5 pb-4">
          <Note tone={unsandboxed ? "warn" : "info"}>
            {t(unsandboxed ? `${m}.unsandboxed_on` : `${m}.unsandboxed_off`)} <Mono>AION_CUSTOM_MCP_ALLOW_UNSANDBOXED</Mono>
          </Note>
        </div>
      </Group>

      <Group title={t(`${m}.limits`)} description={t(`${m}.limits_hint`)}>
        <FieldGrid>
          {LIMITS.map(({ key, id, placeholder }) => (
            <Field key={key} label={t(`${m}.${id}`)} env={key}>
              <TextInput value={txt(key)} onChange={(v) => set(key, v)} placeholder={placeholder} inputMode="numeric" mono />
            </Field>
          ))}
        </FieldGrid>
      </Group>

      <Group title={t(`${m}.container`)} description={t(`${m}.container_hint`)}>
        <FieldGrid>
          {CONTAINER.map(({ key, id, placeholder }) => (
            <Field key={key} label={t(`${m}.${id}`)} env={key}>
              <TextInput value={txt(key)} onChange={(v) => set(key, v)} placeholder={placeholder} mono />
            </Field>
          ))}
        </FieldGrid>
      </Group>
    </div>
  );
}
