"use client";

/**
 * Settings → Audio: which engine the `stt` MCP server uses to turn audio into
 * text, saved through the page bar like the other sections.
 *
 * Two modes, mirroring the OCR section:
 * - remote: an OpenAI-compatible `POST {base}/audio/transcriptions` service
 *   (Whisper on vLLM, OpenAI, …). URL + key are tested with the shared model
 *   probe, which also lists the models to choose from.
 * - local: faster-whisper on this server. The admin picks the model (bigger =
 *   more accurate, slower, more memory), how many candidate sentences the
 *   decoder compares and the default language of the recordings. Model
 *   availability and the optional ahead-of-time download come from
 *   `/admin/stt/local-models`, so the first transcription after a model switch
 *   does not spend its time budget downloading hundreds of MB.
 *
 * The backend picks the remote engine when a base URL and a real API key are
 * set (`is_remote_stt_enabled` in `src/tools/audio_transcribe.py`), so saving in
 * local mode clears the remote keys (see `clearedStt`, used by the page).
 *
 * The underlying environment variable names are deliberately not shown: the
 * page explains effects in plain language instead.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { CheckCircle2, Download, Loader2 } from "lucide-react";
import {
  filterModelsForKind,
  modelIdsFromProbe,
  pickDefaultModel,
  probeBaseUrlFromSttServiceUrl,
  runModelProbe,
} from "@/lib/llm-probe";
import { apiFetch } from "@/lib/api/headers";
import { apiBase } from "@/lib/api";
import { outlineBtn } from "@/components/ui/classes";
import { Select } from "@/components/ui/Select";
import { ChoiceList, Field, FieldGrid, Group, ModelField, Mono, Note, ProbeBar, SecretInput, SectionHead, TextInput } from "./ui";
import { useProbe } from "./useProbe";
import { K, type SectionCtx } from "./types";

export type SttMode = "remote" | "local";
const m = `${K}.stt`;

const MODEL_KEY = "AION_STT_LOCAL_MODEL";
const BEAM_KEY = "AION_STT_LOCAL_BEAM_SIZE";
const LANGUAGE_KEY = "AION_STT_LANGUAGE";

// Remote-service settings. The local ones and the language are kept on a mode
// switch: they are harmless while the remote engine is active.
const STT_REMOTE_KEYS = ["AION_STT_BASE_URL", "AION_STT_MODEL", "AION_STT_API_KEY", "AION_STT_TIMEOUT", "AION_STT_CHUNK_SEC"] as const;
/** Blank remote settings, merged into the save payload in local mode so the backend falls back to faster-whisper. */
export const clearedStt = () => Object.fromEntries(STT_REMOTE_KEYS.map((k) => [k, ""]));

// Backend defaults, used when the setting is empty.
const DEFAULT_MODEL = "small";
const DEFAULT_BEAM = "5";
const DEFAULT_LANGUAGE = "it";

// Curated beam sizes: 1 = greedy, 5 = Whisper's own default; 3 sits between.
const BEAM_PRESETS = ["1", "3", "5"] as const;

// Languages offered in the list: the admin-ui locales plus automatic detection.
// Any other ISO code set by hand on the server stays selectable as "custom".
const LANGUAGE_PRESETS = ["it", "en", "fr", "de", "es", "auto"] as const;

// Poll interval while a model download runs in the backend.
const POLL_MS = 2500;

type ModelInfo = { name: string; installed: boolean; custom: boolean };
type DownloadState = { model: string | null; state: "idle" | "running" | "done" | "error"; error: string | null };
type Status = { mode: "local" | "remote"; current: string; models: ModelInfo[]; download: DownloadState };

export function SttSection({ t, settings, set, setMany, notify, mode, setMode }: SectionCtx & { mode: SttMode; setMode: (m: SttMode) => void }) {
  const savedRemoteModel = (settings.AION_STT_MODEL || "").trim();
  const probe = useProbe(mode === "remote" && savedRemoteModel ? savedRemoteModel : "");

  /** Forget the tested endpoint after URL/key edits: the model list may no longer apply. */
  const resetProbe = () => {
    probe.reset();
    set("AION_STT_MODEL", "");
  };

  const changeMode = (next: SttMode) => {
    setMode(next);
    probe.reset();
    setMany(next === "local" ? clearedStt() : { AION_STT_MODEL: "" });
  };

  /** Test URL + key against the service's `/models` and preselect a speech model. */
  const runProbe = async () => {
    const base = probeBaseUrlFromSttServiceUrl(settings.AION_STT_BASE_URL || "");
    if (!base) return notify(t(`${m}.err_url`), "error");
    if (!/^https?:\/\//.test(base)) return notify(t(`${m}.err_scheme`), "error");
    // The backend only uses the remote engine with a real key (not the EMPTY placeholder).
    const key = (settings.AION_STT_API_KEY || "").trim();
    if (!key || key === "EMPTY") return notify(t(`${m}.err_key`), "error");

    probe.setProbing(true);
    probe.setLatency(null);
    try {
      const result = await runModelProbe(apiFetch, apiBase(), { provider: "vllm", api_base_url: base, api_key: key });
      const all = modelIdsFromProbe(result);
      const ids = filterModelsForKind(all, "stt");
      probe.setResult(result);
      probe.setIds(ids);
      probe.setTested(true);
      probe.setLatency(result.latency_ms);
      // Store the base without /audio/transcriptions: the engine appends it.
      setMany({
        AION_STT_BASE_URL: result.base_url || base,
        AION_STT_MODEL: ids.length > 0 ? pickDefaultModel(all, "stt") : settings.AION_STT_MODEL || "",
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
        <ChoiceList<SttMode>
          value={mode}
          onChange={changeMode}
          label={t(`${m}.mode`)}
          options={[
            { value: "remote", title: t(`${m}.remote`), description: t(`${m}.remote_hint`) },
            { value: "local", title: t(`${m}.local`), description: t(`${m}.local_hint`) },
          ]}
        />
      </Group>

      {mode === "remote" ? (
        <>
          <Group title={t(`${m}.endpoint`)}>
            <FieldGrid>
              <Field label={t(`${m}.url`)} hint={t(`${m}.url_hint`)} wide>
                <TextInput
                  value={settings.AION_STT_BASE_URL || ""}
                  mono
                  onChange={(v) => {
                    set("AION_STT_BASE_URL", v);
                    resetProbe();
                  }}
                  placeholder="http://localhost:8004/v1"
                />
              </Field>
              <Field label={t(`${m}.token`)} wide>
                <SecretInput
                  value={settings.AION_STT_API_KEY || ""}
                  onChange={(v) => {
                    set("AION_STT_API_KEY", v);
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
                label={t(`${m}.remote_model`)}
                manualLabel={t(`${m}.remote_model_manual`)}
                tested={probe.tested}
                manual={probe.manual}
                ids={probe.ids}
                value={settings.AION_STT_MODEL || ""}
                onChange={(v) => set("AION_STT_MODEL", v)}
                hintBefore={t(`${m}.remote_model_before`)}
                manualPlaceholder="openai/whisper-large-v3"
              />
            </FieldGrid>
          </Group>

          {probe.tested && (settings.AION_STT_MODEL || "").trim() && (
            <Group title={t(`${m}.limits`)} description={t(`${m}.limits_hint`)}>
              <FieldGrid>
                <Field label={t(`${m}.timeout`)}>
                  <TextInput type="number" inputMode="numeric" value={settings.AION_STT_TIMEOUT || ""} onChange={(v) => set("AION_STT_TIMEOUT", v)} placeholder="120" />
                </Field>
                <Field label={t(`${m}.chunk_sec`)} hint={t(`${m}.chunk_sec_hint`)}>
                  <TextInput type="number" inputMode="numeric" value={settings.AION_STT_CHUNK_SEC || ""} onChange={(v) => set("AION_STT_CHUNK_SEC", v)} placeholder="30" />
                </Field>
              </FieldGrid>
            </Group>
          )}
        </>
      ) : (
        <LocalSettings t={t} settings={settings} set={set} notify={notify} />
      )}
    </div>
  );
}

/**
 * Local faster-whisper settings: model (with availability and pre-download),
 * decoder beam size and default language. Mounted only in local mode, so the
 * model status is fetched only when it is shown.
 */
function LocalSettings({ t, settings, set, notify }: Pick<SectionCtx, "t" | "settings" | "set" | "notify">) {
  const [status, setStatus] = useState<Status | null>(null);
  const [starting, setStarting] = useState(false);
  // Download state seen by the previous poll, to notice when it finishes.
  const prevStateRef = useRef<DownloadState["state"]>("idle");

  const model = (settings[MODEL_KEY] || "").trim() || DEFAULT_MODEL;
  const beam = (settings[BEAM_KEY] || "").trim() || DEFAULT_BEAM;
  const language = (settings[LANGUAGE_KEY] || "").trim().toLowerCase() || DEFAULT_LANGUAGE;

  /** Fetch model availability and the state of a background download. */
  const load = useCallback(async () => {
    try {
      const res = await apiFetch(`${apiBase()}/admin/stt/local-models`);
      if (!res.ok) return;
      const data: Status = await res.json();
      // Report the end of a download this page was watching.
      const was = prevStateRef.current;
      if (was === "running" && data.download.state === "done") {
        notify(t(`${m}.download_done`, { model: t(`${m}.models.${data.download.model}.title`) }), "success");
      } else if (was === "running" && data.download.state === "error") {
        notify(t(`${m}.download_failed`), "error");
      }
      prevStateRef.current = data.download.state;
      setStatus(data);
    } catch {
      /* status is optional: the choices still work without it */
    }
  }, [notify, t]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch on mount
    void load();
  }, [load]);

  // Poll only while the backend reports a download in progress.
  const running = status?.download.state === "running";
  useEffect(() => {
    if (!running) return;
    const id = setInterval(() => void load(), POLL_MS);
    return () => clearInterval(id);
  }, [running, load]);

  const startDownload = async () => {
    setStarting(true);
    try {
      const res = await apiFetch(`${apiBase()}/admin/stt/local-models/${encodeURIComponent(model)}/download`, { method: "POST" });
      if (!res.ok) {
        notify(t(res.status === 409 ? `${m}.download_busy` : `${m}.download_failed`), "error");
        return;
      }
      const data: Status = await res.json();
      prevStateRef.current = data.download.state;
      setStatus(data);
    } catch {
      notify(t(`${m}.download_failed`), "error");
    } finally {
      setStarting(false);
    }
  };

  const info = status?.models.find((x) => x.name === model);
  const downloading = running;
  const downloadingThis = downloading && status?.download.model === model;

  // Curated models first; a value set by hand on the server stays selectable.
  // Curated entries also show the faster-whisper model name next to their
  // plain-language title, so the admin knows which model is downloaded/run.
  const modelOptions = (status?.models ?? [{ name: model, installed: false, custom: false }]).map((x) => ({
    value: x.name,
    title: x.custom ? x.name : t(`${m}.models.${x.name}.title`),
    badge: x.name === DEFAULT_MODEL ? t(`${m}.recommended`) : undefined,
    description: x.custom ? t(`${m}.custom_model`) : t(`${m}.models.${x.name}.description`),
    extra: (
      <>
        {!x.custom && <Mono>whisper-{x.name}</Mono>}
        {status && <Availability installed={x.installed} downloading={downloading && status.download.model === x.name} t={t} />}
      </>
    ),
  }));
  if (!modelOptions.some((o) => o.value === model)) {
    modelOptions.push({ value: model, title: model, badge: undefined, description: t(`${m}.custom_model`), extra: <></> });
  }

  const beamOptions = BEAM_PRESETS.map((v) => ({
    value: v as string,
    title: t(`${m}.beam.${v}.title`),
    badge: v === DEFAULT_BEAM ? t(`${m}.recommended`) : undefined,
    description: t(`${m}.beam.${v}.description`),
  }));
  if (!(BEAM_PRESETS as readonly string[]).includes(beam)) {
    beamOptions.push({ value: beam, title: t(`${m}.beam.custom_title`, { n: beam }), badge: undefined, description: t(`${m}.beam.custom_description`) });
  }

  const languageOptions = LANGUAGE_PRESETS.map((v) => ({
    value: v as string,
    label: t(`${m}.language.${v}.title`),
    description: t(`${m}.language.${v}.description`),
  }));
  if (!(LANGUAGE_PRESETS as readonly string[]).includes(language)) {
    languageOptions.push({ value: language, label: t(`${m}.language.custom_title`, { code: language }), description: t(`${m}.language.custom_description`) });
  }

  return (
    <>
      <Group title={t(`${m}.model_title`)} description={t(`${m}.model_hint`)}>
        <ChoiceList<string> value={model} onChange={(v) => set(MODEL_KEY, v)} label={t(`${m}.model_title`)} options={modelOptions} />
        {/* Only the curated models can be fetched from here. */}
        {info && !info.installed && !info.custom && (
          <div className="flex flex-wrap items-center gap-3 border-t border-border px-5 py-4">
            <p className="min-w-0 flex-1 text-xs leading-relaxed text-muted-foreground">
              {downloadingThis ? t(`${m}.downloading_hint`) : t(`${m}.not_installed`)}
            </p>
            <button type="button" className={outlineBtn} onClick={() => void startDownload()} disabled={starting || downloading}>
              {starting || downloadingThis ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <Download className="h-3.5 w-3.5" aria-hidden />}
              {downloadingThis ? t(`${m}.downloading`) : t(`${m}.download`)}
            </button>
          </div>
        )}
        {status?.download.state === "error" && status.download.model === model && (
          <div className="border-t border-border px-5 py-3">
            <Note tone="warn">{t(`${m}.download_error`, { error: status.download.error || "" })}</Note>
          </div>
        )}
      </Group>

      <Group title={t(`${m}.language_title`)} description={t(`${m}.language_hint`)}>
        <FieldGrid>
          <Field label={t(`${m}.language_label`)} wide>
            <Select value={language} onChange={(v) => set(LANGUAGE_KEY, v)} options={languageOptions} aria-label={t(`${m}.language_label`)} />
          </Field>
        </FieldGrid>
      </Group>

      <Group title={t(`${m}.beam_title`)} description={t(`${m}.beam_hint`)}>
        <ChoiceList<string> value={beam} onChange={(v) => set(BEAM_KEY, v)} label={t(`${m}.beam_title`)} options={beamOptions} />
      </Group>

      <Note>{t(`${m}.apply_note`)}</Note>
    </>
  );
}

/** Small chip telling whether a model is already on the server. */
function Availability({ installed, downloading, t }: { installed: boolean; downloading: boolean; t: SectionCtx["t"] }) {
  if (downloading) {
    return (
      <span className="inline-flex items-center gap-1 text-[11px] font-medium text-muted-foreground">
        <Loader2 className="h-3 w-3 animate-spin" aria-hidden />
        {t(`${m}.downloading`)}
      </span>
    );
  }
  if (installed) {
    return (
      <span className="inline-flex items-center gap-1 text-[11px] font-medium text-success">
        <CheckCircle2 className="h-3 w-3" aria-hidden />
        {t(`${m}.installed`)}
      </span>
    );
  }
  return <span className="text-[11px] font-medium text-muted-foreground">{t(`${m}.to_download`)}</span>;
}
