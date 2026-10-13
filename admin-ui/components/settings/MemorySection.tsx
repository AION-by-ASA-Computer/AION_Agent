"use client";

import {
  embeddingProviderToProbeProvider,
  embeddingServiceUrlFromProbeBase,
  filterModelsForKind,
  modelIdsFromProbe,
  pickDefaultModel,
  probeBaseUrlFromServiceUrl,
  runModelProbe,
} from "@/lib/llm-probe";
import { apiFetch } from "@/lib/api/headers";
import { apiBase } from "@/lib/api";
import { Select } from "@/components/ui/Select";
import { Field, FieldGrid, Group, ModelField, Mono, ProbeBar, SecretInput, SectionHead, TextInput, ToggleList, ToggleRow } from "./ui";
import { useProbe } from "./useProbe";
import { K, type SectionCtx } from "./types";

const m = `${K}.memory`;
const LOCAL_HOSTS = ["localhost", "127.0.0.1", "host.docker.internal", "gateway.docker.internal"];

const URL_PLACEHOLDER: Record<string, string> = {
  google: "https://generativelanguage.googleapis.com/v1beta/models",
  ollama: "http://localhost:11434/v1/embeddings",
  vllm: "http://localhost:8000/v1/embeddings",
  openai: "https://api.openai.com/v1/embeddings",
};

export function MemorySection({ t, settings, set, setMany, notify }: SectionCtx) {
  const provider = settings.AION_EMBEDDINGS_PROVIDER || "openai";
  const savedModel = (settings.AION_EMBEDDING_MODEL || "").trim();
  const savedUrl = (settings.AION_EMBEDDING_URL || "").trim();
  const probe = useProbe(savedModel && savedUrl ? savedModel : "");

  const resetProbe = () => {
    probe.reset();
    set("AION_EMBEDDING_MODEL", "");
  };

  const changeProvider = (next: string) => {
    setMany({ AION_EMBEDDINGS_PROVIDER: next, AION_EMBEDDING_MODEL: "", AION_EMBEDDING_URL: "" });
    probe.reset();
  };

  const runProbe = async () => {
    const base = probeBaseUrlFromServiceUrl(settings.AION_EMBEDDING_URL || "");
    if (!base) return notify(t(`${m}.err_url`), "error");
    const selfHosted = provider === "vllm" || provider === "ollama";
    const key = (settings.AION_EMBEDDINGS_API_KEY || "").trim();
    if (provider !== "google" && !selfHosted && !key) {
      const host = base.replace(/^https?:\/\//i, "").split(/[/:]/)[0].toLowerCase();
      if (!LOCAL_HOSTS.includes(host) && !host.endsWith(".local") && !host.endsWith(".internal")) {
        return notify(t(`${m}.err_key`), "error");
      }
    }
    probe.setProbing(true);
    probe.setLatency(null);
    try {
      const result = await runModelProbe(apiFetch, apiBase(), {
        provider: embeddingProviderToProbeProvider(provider),
        api_base_url: base,
        api_key: key || null,
      });
      const all = modelIdsFromProbe(result);
      const ids = filterModelsForKind(all, "embedding");
      probe.setResult(result);
      probe.setIds(ids);
      probe.setTested(true);
      probe.setLatency(result.latency_ms);
      setMany({
        AION_EMBEDDING_URL: embeddingServiceUrlFromProbeBase(result.base_url || base),
        AION_EMBEDDING_MODEL: ids.length > 0 ? pickDefaultModel(all, "embedding") : settings.AION_EMBEDDING_MODEL || "",
      });
      probe.setManual(ids.length === 0);
      if (result.warning) notify(result.warning, "warning");
    } catch (err) {
      resetProbe();
      notify(err instanceof Error ? err.message : t(`${m}.err_test`), "error");
    } finally {
      probe.setProbing(false);
    }
  };

  const tog = (key: string) => (v: boolean) => set(key, v ? "1" : "0");

  return (
    <div className="flex flex-col gap-5">
      <SectionHead title={t(`${m}.title`)} description={t(`${m}.description`)} />

      <Group>
        <ToggleList>
          <ToggleRow label={t(`${m}.retrieval`)} description={t(`${m}.retrieval_hint`)} checked={settings.AION_LTM_RETRIEVAL === "1"} onChange={tog("AION_LTM_RETRIEVAL")} />
          <ToggleRow label={t(`${m}.extract`)} description={t(`${m}.extract_hint`)} checked={settings.AION_LTM_EXTRACT === "1"} onChange={tog("AION_LTM_EXTRACT")} />
        </ToggleList>
      </Group>

      <Group title={t(`${m}.emb_title`)} description={t(`${m}.emb_description`)}>
        <FieldGrid>
          <Field label={t(`${m}.provider`)} env="AION_EMBEDDINGS_PROVIDER">
            <Select
              value={provider}
              onChange={changeProvider}
              aria-label={t(`${m}.provider`)}
              options={[
                { value: "openai", label: t(`${m}.p_openai`) },
                { value: "vllm", label: t(`${m}.p_vllm`) },
                { value: "ollama", label: "Ollama" },
                { value: "google", label: "Google" },
              ]}
            />
          </Field>

          <Field label={t(`${m}.url`)} env="AION_EMBEDDING_URL" hint={<>{t(`${m}.url_hint_a`)} <Mono>/v1/embeddings</Mono> {t(`${m}.url_hint_b`)}</>}>
            <TextInput
              value={settings.AION_EMBEDDING_URL || ""}
              mono
              onChange={(v) => {
                set("AION_EMBEDDING_URL", v);
                resetProbe();
              }}
              placeholder={URL_PLACEHOLDER[provider] ?? URL_PLACEHOLDER.openai}
            />
          </Field>

          {provider !== "google" && (
            <Field label={t(`${m}.api_key`)} env="AION_EMBEDDINGS_API_KEY" wide>
              <SecretInput
                value={settings.AION_EMBEDDINGS_API_KEY || ""}
                onChange={(v) => {
                  set("AION_EMBEDDINGS_API_KEY", v);
                  resetProbe();
                }}
                placeholder={provider === "vllm" || provider === "ollama" ? t(`${m}.api_key_optional`) : t(`${m}.api_key_ph`)}
                showLabel={t(`${K}.show_secret`)}
                hideLabel={t(`${K}.hide_secret`)}
              />
            </Field>
          )}

          <ProbeBar
            probing={probe.probing}
            onProbe={() => void runProbe()}
            label={t(`${m}.test`)}
            ok={probe.tested && probe.latency != null}
            okText={t(probe.ids.length > 0 ? `${m}.test_ok` : `${m}.test_ok_manual`, { ms: probe.latency ?? 0, count: probe.ids.length })}
          />

          <ModelField
            label={t(`${m}.model`)}
            manualLabel={t(`${m}.model_manual`)}
            tested={probe.tested}
            manual={probe.manual}
            ids={probe.ids}
            value={settings.AION_EMBEDDING_MODEL || ""}
            onChange={(v) => set("AION_EMBEDDING_MODEL", v)}
            hintBefore={t(`${m}.model_before`)}
            manualPlaceholder="text-embedding-3-small"
          />
        </FieldGrid>
      </Group>
    </div>
  );
}
