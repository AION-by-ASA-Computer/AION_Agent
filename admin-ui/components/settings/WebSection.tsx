"use client";

import { Select } from "@/components/ui/Select";
import { Field, FieldGrid, Group, SecretInput, SectionHead, TextInput, ToggleList, ToggleRow } from "./ui";
import { K, type SectionCtx } from "./types";

const m = `${K}.web`;

export function WebSection({ t, settings, set }: SectionCtx) {
  const tog = (key: string) => (v: boolean) => set(key, v ? "1" : "0");
  const on = (key: string) => settings[key] === "1";
  const txt = (key: string, fallback = "") => settings[key] ?? fallback;
  const secret = {
    showLabel: t(`${K}.show_secret`),
    hideLabel: t(`${K}.hide_secret`),
  };

  return (
    <div className="flex flex-col gap-5">
      <SectionHead title={t(`${m}.title`)} description={t(`${m}.description`)} />

      <Group title={t(`${m}.engines`)} description={t(`${m}.engines_hint`)}>
        <ToggleList>
          <ToggleRow label="Tavily" checked={on("AION_WEB_SEARCH_TAVILY_ENABLED")} onChange={tog("AION_WEB_SEARCH_TAVILY_ENABLED")} />
          <ToggleRow label="Brave Search" checked={on("AION_WEB_SEARCH_BRAVE_ENABLED")} onChange={tog("AION_WEB_SEARCH_BRAVE_ENABLED")} />
          <ToggleRow label="SearXNG" checked={on("AION_WEB_SEARCH_SEARXNG_ENABLED")} onChange={tog("AION_WEB_SEARCH_SEARXNG_ENABLED")} />
          <ToggleRow label={t(`${m}.scrapling`)} description={t(`${m}.scrapling_hint`)} checked={on("AION_SCRAPLING_STEALTH_ENABLED")} onChange={tog("AION_SCRAPLING_STEALTH_ENABLED")} />
        </ToggleList>
        <div className="border-t border-border/50">
          <FieldGrid>
            <Field label={t(`${m}.tavily_key`)} env="AION_TAVILY_API_KEY" hint={t(`${m}.key_masked`)}>
              <SecretInput value={txt("AION_TAVILY_API_KEY")} onChange={(v) => set("AION_TAVILY_API_KEY", v)} {...secret} />
            </Field>
            <Field label={t(`${m}.brave_key`)} env="AION_BRAVE_SEARCH_API_KEY">
              <SecretInput value={txt("AION_BRAVE_SEARCH_API_KEY")} onChange={(v) => set("AION_BRAVE_SEARCH_API_KEY", v)} {...secret} />
            </Field>
            <Field label={t(`${m}.searxng_url`)} env="AION_SEARXNG_BASE_URL" hint={t(`${m}.searxng_hint`)} wide>
              <TextInput value={txt("AION_SEARXNG_BASE_URL")} mono onChange={(v) => set("AION_SEARXNG_BASE_URL", v)} placeholder="https://search.example.org" />
            </Field>
          </FieldGrid>
        </div>
      </Group>

      <Group title={t(`${m}.routing`)} description={t(`${m}.routing_hint`)}>
        <FieldGrid>
          <Field label={t(`${m}.default_engine`)} env="AION_WEB_SEARCH_DEFAULT_PROVIDER">
            <Select
              value={txt("AION_WEB_SEARCH_DEFAULT_PROVIDER", "tavily")}
              onChange={(v) => set("AION_WEB_SEARCH_DEFAULT_PROVIDER", v)}
              aria-label={t(`${m}.default_engine`)}
              options={[
                { value: "tavily", label: "Tavily" },
                { value: "brave", label: "Brave Search" },
                { value: "searxng", label: "SearXNG" },
              ]}
            />
          </Field>
          <Field label={t(`${m}.fallback`)} env="AION_WEB_SEARCH_FALLBACK_ORDER" hint={t(`${m}.fallback_hint`)}>
            <TextInput value={txt("AION_WEB_SEARCH_FALLBACK_ORDER", "brave,searxng")} mono onChange={(v) => set("AION_WEB_SEARCH_FALLBACK_ORDER", v)} />
          </Field>
          <Field label={t(`${m}.max_results`)} env="AION_WEB_SEARCH_MAX_RESULTS">
            <TextInput type="number" inputMode="numeric" value={txt("AION_WEB_SEARCH_MAX_RESULTS", "8")} onChange={(v) => set("AION_WEB_SEARCH_MAX_RESULTS", v)} />
          </Field>
          <Field label={t(`${m}.timeout`)} env="AION_WEB_SEARCH_TIMEOUT_SEC">
            <TextInput type="number" inputMode="numeric" value={txt("AION_WEB_SEARCH_TIMEOUT_SEC", "30")} onChange={(v) => set("AION_WEB_SEARCH_TIMEOUT_SEC", v)} />
          </Field>
          <Field label={t(`${m}.fetch_chars`)} env="AION_WEB_FETCH_MAX_CHARS" hint={t(`${m}.fetch_chars_hint`)}>
            <TextInput type="number" inputMode="numeric" value={txt("AION_WEB_FETCH_MAX_CHARS", "120000")} onChange={(v) => set("AION_WEB_FETCH_MAX_CHARS", v)} />
          </Field>
          <Field label={t(`${m}.registry`)} env="AION_NATIVE_TOOL_REGISTRY_PATH">
            <TextInput value={txt("AION_NATIVE_TOOL_REGISTRY_PATH", "config/native_tool_registry.yaml")} mono onChange={(v) => set("AION_NATIVE_TOOL_REGISTRY_PATH", v)} />
          </Field>
        </FieldGrid>
      </Group>

      <Group title={t(`${m}.limits`)} description={t(`${m}.limits_hint`)}>
        <ToggleList>
          <ToggleRow label={t(`${m}.enforce`)} description={t(`${m}.enforce_hint`)} checked={on("AION_WEB_SEARCH_ENFORCE_GLOBAL_ALLOWLIST")} onChange={tog("AION_WEB_SEARCH_ENFORCE_GLOBAL_ALLOWLIST")} />
          <ToggleRow label={t(`${m}.opt_in`)} description={t(`${m}.opt_in_hint`)} checked={on("AION_WEB_SEARCH_REQUIRE_CLIENT_OPT_IN")} onChange={tog("AION_WEB_SEARCH_REQUIRE_CLIENT_OPT_IN")} />
        </ToggleList>
        <div className="border-t border-border/50">
          <FieldGrid>
            <Field label={t(`${m}.hosts`)} env="AION_WEB_SEARCH_ALLOWED_HOSTS" hint={t(`${m}.hosts_hint`)}>
              <TextInput value={txt("AION_WEB_SEARCH_ALLOWED_HOSTS")} mono onChange={(v) => set("AION_WEB_SEARCH_ALLOWED_HOSTS", v)} placeholder="docs.example.com, *.example.org" />
            </Field>
            <Field label={t(`${m}.regex`)} env="AION_WEB_FETCH_ALLOWLIST_REGEX" hint={t(`${m}.regex_hint`)}>
              <TextInput value={txt("AION_WEB_FETCH_ALLOWLIST_REGEX")} mono onChange={(v) => set("AION_WEB_FETCH_ALLOWLIST_REGEX", v)} />
            </Field>
          </FieldGrid>
        </div>
      </Group>
    </div>
  );
}
