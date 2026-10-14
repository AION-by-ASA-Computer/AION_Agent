"use client";

import {
  filterModelsForKind,
  modelIdsFromProbe,
  pickDefaultModel,
  probeBaseUrlFromOcrServiceUrl,
  runModelProbe,
} from "@/lib/llm-probe";
import { apiFetch } from "@/lib/api/headers";
import { apiBase } from "@/lib/api";
import { ChoiceList, Field, FieldGrid, Group, ModelField, Mono, Note, ProbeBar, SecretInput, SectionHead, TextInput } from "./ui";
import { useProbe } from "./useProbe";
import { K, type SectionCtx } from "./types";

export type OcrMode = "remote" | "local";
const m = `${K}.ocr`;

const OCR_KEYS = ["AION_OCR_BASE_URL", "AION_OCR_MODEL", "AION_OCR_API_KEY", "AION_OCR_MAX_TOKENS", "AION_OCR_TIMEOUT", "AION_OCR_MAX_IMAGE_BYTES"] as const;
export const clearedOcr = () => Object.fromEntries(OCR_KEYS.map((k) => [k, ""]));

export function OcrSection({ t, settings, set, setMany, notify, mode, setMode }: SectionCtx & { mode: OcrMode; setMode: (m: OcrMode) => void }) {
  const savedModel = (settings.AION_OCR_MODEL || "").trim();
  const probe = useProbe(mode === "remote" && savedModel ? savedModel : "");

  const resetProbe = () => {
    probe.reset();
    set("AION_OCR_MODEL", "");
  };

  const changeMode = (next: OcrMode) => {
    setMode(next);
    probe.reset();
    setMany(next === "local" ? clearedOcr() : { AION_OCR_MODEL: "" });
  };

  const runProbe = async () => {
    const base = probeBaseUrlFromOcrServiceUrl(settings.AION_OCR_BASE_URL || "");
    if (!base) return notify(t(`${m}.err_url`), "error");
    if (!/^https?:\/\//.test(base)) return notify(t(`${m}.err_scheme`), "error");
    const key = (settings.AION_OCR_API_KEY || "").trim();
    if (!key || key === "EMPTY") return notify(t(`${m}.err_key`), "error");

    probe.setProbing(true);
    probe.setLatency(null);
    try {
      const result = await runModelProbe(apiFetch, apiBase(), { provider: "vllm", api_base_url: base, api_key: key });
      const all = modelIdsFromProbe(result);
      const ids = filterModelsForKind(all, "ocr");
      probe.setResult(result);
      probe.setIds(ids);
      probe.setTested(true);
      probe.setLatency(result.latency_ms);
      setMany({
        AION_OCR_BASE_URL: result.base_url || base,
        AION_OCR_MODEL: ids.length > 0 ? pickDefaultModel(all, "ocr") : settings.AION_OCR_MODEL || "",
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

  return (
    <div className="flex flex-col gap-5">
      <SectionHead title={t(`${m}.title`)} description={t(`${m}.description`)} />

      <Group>
        <ChoiceList<OcrMode>
          value={mode}
          onChange={changeMode}
          label={t(`${m}.mode`)}
          options={[
            { value: "remote", title: t(`${m}.remote`), badge: t(`${m}.recommended`), description: <>{t(`${m}.remote_hint`)} <Mono>AION_OCR_*</Mono></> },
            { value: "local", title: t(`${m}.local`), description: <><Mono>pymupdf4llm</Mono> · <Mono>pytesseract</Mono>. {t(`${m}.local_hint`)}</> },
          ]}
        />
      </Group>

      {mode === "remote" ? (
        <>
          <Group title={t(`${m}.endpoint`)}>
            <FieldGrid>
              <Field label={t(`${m}.url`)} env="AION_OCR_BASE_URL" wide>
                <TextInput
                  value={settings.AION_OCR_BASE_URL || ""}
                  mono
                  onChange={(v) => {
                    set("AION_OCR_BASE_URL", v);
                    resetProbe();
                  }}
                  placeholder="http://localhost:8002/v1"
                />
              </Field>
              <Field label={t(`${m}.token`)} env="AION_OCR_API_KEY" wide>
                <SecretInput
                  value={settings.AION_OCR_API_KEY || ""}
                  onChange={(v) => {
                    set("AION_OCR_API_KEY", v);
                    resetProbe();
                  }}
                  showLabel={t(`${K}.show_secret`)}
                  hideLabel={t(`${K}.hide_secret`)}
                />
              </Field>
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
                value={settings.AION_OCR_MODEL || ""}
                onChange={(v) => set("AION_OCR_MODEL", v)}
                hintBefore={t(`${m}.model_before`)}
                manualPlaceholder="THUDM/glm-4v-9b"
              />
            </FieldGrid>
          </Group>

          {probe.tested && (settings.AION_OCR_MODEL || "").trim() && (
            <Group title={t(`${m}.limits`)} description={t(`${m}.limits_hint`)}>
              <FieldGrid>
                <Field label={t(`${m}.max_tokens`)} env="AION_OCR_MAX_TOKENS">
                  <TextInput type="number" inputMode="numeric" value={settings.AION_OCR_MAX_TOKENS || ""} onChange={(v) => set("AION_OCR_MAX_TOKENS", v)} />
                </Field>
                <Field label={t(`${m}.timeout`)} env="AION_OCR_TIMEOUT">
                  <TextInput type="number" inputMode="numeric" value={settings.AION_OCR_TIMEOUT || ""} onChange={(v) => set("AION_OCR_TIMEOUT", v)} />
                </Field>
                <Field label={t(`${m}.max_bytes`)} env="AION_OCR_MAX_IMAGE_BYTES" wide>
                  <TextInput type="number" inputMode="numeric" value={settings.AION_OCR_MAX_IMAGE_BYTES || ""} onChange={(v) => set("AION_OCR_MAX_IMAGE_BYTES", v)} />
                </Field>
              </FieldGrid>
            </Group>
          )}
        </>
      ) : (
        <Note>{t(`${m}.local_note`)}</Note>
      )}
    </div>
  );
}
