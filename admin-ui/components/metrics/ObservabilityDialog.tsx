"use client";

import { useState } from "react";
import { CheckCircle2, Eye, EyeOff, Loader2, OctagonAlert, Play, Save } from "lucide-react";
import { cn } from "@/lib/cn";
import { Dialog } from "@/components/profiles/Dialog";
import { Select } from "@/components/ui/Select";
import { inputCls, outlineBtn, solidBtn } from "@/components/ui/classes";
import type { ProbeTarget, useObservability } from "./useObservability";
import type { T } from "./types";

const k = "admin_metrics.config";
type Obs = ReturnType<typeof useObservability>;
const TABS: ProbeTarget[] = ["prometheus", "otel", "opik"];

function Switch({ on, onChange, label }: { on: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      onClick={() => onChange(!on)}
      className={cn("focus-ring relative h-6 w-10 shrink-0 rounded-full transition-colors", on ? "bg-foreground" : "bg-border")}
    >
      <span className={cn("absolute left-0.5 top-0.5 h-5 w-5 rounded-full bg-background shadow-sm transition-transform", on && "translate-x-4")} />
    </button>
  );
}

function ToggleRow({ title, hint, on, onChange }: { title: string; hint: string; on: boolean; onChange: (v: boolean) => void }) {
  return (
    <div className="flex items-start justify-between gap-4 rounded-2xl border border-border/60 bg-secondary/30 px-4 py-3.5">
      <div className="min-w-0">
        <div className="text-sm font-medium">{title}</div>
        <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p>
      </div>
      <Switch on={on} onChange={onChange} label={title} />
    </div>
  );
}

function Field({ id, label, env, hint, children }: { id: string; label: string; env: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-baseline justify-between gap-3">
        <label htmlFor={id} className="text-sm font-medium">
          {label}
        </label>
        <span className="truncate font-mono text-[11px] text-muted-foreground">{env}</span>
      </div>
      {hint && <p className="-mt-0.5 text-xs text-muted-foreground">{hint}</p>}
      {children}
    </div>
  );
}

function ProbeRow({ obs, target, placeholder, valueKey, id, t }: { obs: Obs; target: ProbeTarget; placeholder: string; valueKey: string; id: string; t: T }) {
  const result = obs.probes[target];
  return (
    <>
      <div className="flex gap-2">
        <input id={id} type="text" inputMode="url" value={obs.settings[valueKey] ?? ""} onChange={(e) => obs.set(valueKey, e.target.value)} placeholder={placeholder} className={cn(inputCls, "font-mono")} />
        <button type="button" className={cn(outlineBtn, "h-auto shrink-0 px-3.5")} onClick={() => obs.probe(target)} disabled={obs.probing[target]}>
          {obs.probing[target] ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <Play className="h-3.5 w-3.5" aria-hidden />}
          {t(`${k}.test`)}
        </button>
      </div>
      {result && (
        <div role="status" className="flex items-center gap-2 text-sm">
          {result.success ? <CheckCircle2 className="h-4 w-4 shrink-0 text-success" aria-hidden /> : <OctagonAlert className="h-4 w-4 shrink-0 text-destructive" aria-hidden />}
          <span className="min-w-0 break-words">{result.message}</span>
          {result.latency_ms !== undefined && <span className="ml-auto shrink-0 text-xs tabular-nums text-muted-foreground">{result.latency_ms} ms</span>}
        </div>
      )}
    </>
  );
}

export function ObservabilityDialog({ obs, t }: { obs: Obs; t: T }) {
  const [tab, setTab] = useState<ProbeTarget>("prometheus");
  const [reveal, setReveal] = useState(false);
  const s = obs.settings;
  const flag = (key: string) => s[key] === "1";

  return (
    <Dialog title={t(`${k}.title`)} closeLabel={t(`${k}.close`)} onClose={obs.close} className="max-w-2xl">
      <p className="-mt-1 mb-4 text-sm text-muted-foreground">{t(`${k}.subtitle`)}</p>

      <div role="tablist" aria-label={t(`${k}.title`)} className="mb-5 inline-flex max-w-full overflow-x-auto rounded-xl border border-border bg-card p-1">
        {TABS.map((id) => (
          <button
            key={id}
            type="button"
            role="tab"
            id={`obs-tab-${id}`}
            aria-selected={tab === id}
            aria-controls="obs-panel"
            onClick={() => setTab(id)}
            className={cn("focus-ring h-8 shrink-0 rounded-lg px-3 text-sm font-medium transition-colors", tab === id ? "bg-secondary text-foreground" : "text-muted-foreground hover:text-foreground")}
          >
            {t(`${k}.tab_${id}`)}
          </button>
        ))}
      </div>

      {obs.notice && (
        <div role={obs.notice.type === "error" ? "alert" : "status"} className="mb-4 flex items-start gap-2.5 rounded-2xl border border-border/70 bg-secondary/40 px-4 py-3 text-sm">
          {obs.notice.type === "success" ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" aria-hidden /> : <OctagonAlert className="mt-0.5 h-4 w-4 shrink-0 text-destructive" aria-hidden />}
          <span className="min-w-0 break-words">{obs.notice.text}</span>
        </div>
      )}

      <div id="obs-panel" role="tabpanel" aria-labelledby={`obs-tab-${tab}`} className="flex min-h-[18rem] flex-col gap-4">
        {obs.loading ? (
          <div className="flex items-center gap-2 py-10 text-sm text-muted-foreground" role="status">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
            {t(`${k}.loading`)}
          </div>
        ) : tab === "prometheus" ? (
          <>
            <Field id="obs-prom-url" label={t(`${k}.prom_url`)} env="AION_PROMETHEUS_URL" hint={t(`${k}.prom_url_hint`)}>
              <ProbeRow obs={obs} target="prometheus" valueKey="AION_PROMETHEUS_URL" placeholder="http://localhost:9090" id="obs-prom-url" t={t} />
            </Field>
            <ToggleRow title={t(`${k}.expose`)} hint={t(`${k}.expose_hint`)} on={flag("AION_METRICS_ENABLED")} onChange={(v) => obs.set("AION_METRICS_ENABLED", v ? "1" : "0")} />
            {flag("AION_METRICS_ENABLED") && (
              <Field id="obs-metrics-path" label={t(`${k}.metrics_path`)} env="AION_METRICS_PATH">
                <input id="obs-metrics-path" type="text" value={s.AION_METRICS_PATH ?? ""} onChange={(e) => obs.set("AION_METRICS_PATH", e.target.value)} placeholder="/metrics" className={cn(inputCls, "font-mono")} />
              </Field>
            )}
          </>
        ) : tab === "otel" ? (
          <>
            <ToggleRow title={t(`${k}.otel_enable`)} hint={t(`${k}.otel_enable_hint`)} on={flag("AION_OTEL_ENABLED")} onChange={(v) => obs.set("AION_OTEL_ENABLED", v ? "1" : "0")} />
            <Field id="obs-otel-endpoint" label={t(`${k}.otel_endpoint`)} env="AION_OTEL_ENDPOINT">
              <ProbeRow obs={obs} target="otel" valueKey="AION_OTEL_ENDPOINT" placeholder="http://localhost:4317" id="obs-otel-endpoint" t={t} />
            </Field>
            <div className="grid gap-3 sm:grid-cols-3">
              <Field id="obs-otel-protocol" label={t(`${k}.otel_protocol`)} env="AION_OTEL_PROTOCOL">
                <Select
                  id="obs-otel-protocol"
                  value={s.AION_OTEL_PROTOCOL || "grpc"}
                  onChange={(v) => obs.set("AION_OTEL_PROTOCOL", v)}
                  options={[
                    { value: "grpc", label: "gRPC (4317)" },
                    { value: "http", label: "HTTP (4318)" },
                  ]}
                />
              </Field>
              <Field id="obs-otel-service" label={t(`${k}.otel_service`)} env="AION_OTEL_SERVICE_NAME">
                <input id="obs-otel-service" type="text" value={s.AION_OTEL_SERVICE_NAME ?? ""} onChange={(e) => obs.set("AION_OTEL_SERVICE_NAME", e.target.value)} className={cn(inputCls, "font-mono")} />
              </Field>
              <Field id="obs-otel-interval" label={t(`${k}.otel_interval`)} env="AION_OTEL_METRIC_EXPORT_INTERVAL">
                <input id="obs-otel-interval" type="number" min={0} value={s.AION_OTEL_METRIC_EXPORT_INTERVAL ?? ""} onChange={(e) => obs.set("AION_OTEL_METRIC_EXPORT_INTERVAL", e.target.value)} className={cn(inputCls, "font-mono tabular-nums")} />
              </Field>
            </div>
            <ToggleRow title={t(`${k}.otel_content`)} hint={t(`${k}.otel_content_hint`)} on={flag("AION_OTEL_TRACE_CONTENT")} onChange={(v) => obs.set("AION_OTEL_TRACE_CONTENT", v ? "1" : "0")} />
          </>
        ) : (
          <>
            <ToggleRow title={t(`${k}.opik_enable`)} hint={t(`${k}.opik_enable_hint`)} on={flag("AION_OPIK_ENABLED")} onChange={(v) => obs.set("AION_OPIK_ENABLED", v ? "1" : "0")} />
            <Field id="obs-opik-url" label={t(`${k}.opik_url`)} env="OPIK_URL_OVERRIDE">
              <ProbeRow obs={obs} target="opik" valueKey="OPIK_URL_OVERRIDE" placeholder="http://localhost:5173/api" id="obs-opik-url" t={t} />
            </Field>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field id="obs-opik-project" label={t(`${k}.opik_project`)} env="OPIK_PROJECT_NAME">
                <input id="obs-opik-project" type="text" value={s.OPIK_PROJECT_NAME ?? ""} onChange={(e) => obs.set("OPIK_PROJECT_NAME", e.target.value)} className={cn(inputCls, "font-mono")} />
              </Field>
              <Field id="obs-opik-key" label={t(`${k}.opik_key`)} env="OPIK_API_KEY">
                <div className="relative">
                  <input id="obs-opik-key" type={reveal ? "text" : "password"} autoComplete="off" value={s.OPIK_API_KEY ?? ""} onChange={(e) => obs.set("OPIK_API_KEY", e.target.value)} className={cn(inputCls, "pr-11 font-mono")} />
                  <button
                    type="button"
                    onClick={() => setReveal((v) => !v)}
                    aria-label={reveal ? t(`${k}.hide_key`) : t(`${k}.show_key`)}
                    aria-pressed={reveal}
                    className="focus-ring absolute right-1.5 top-1/2 inline-flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:text-foreground"
                  >
                    {reveal ? <EyeOff className="h-4 w-4" aria-hidden /> : <Eye className="h-4 w-4" aria-hidden />}
                  </button>
                </div>
              </Field>
            </div>
          </>
        )}
      </div>

      <div className="mt-6 flex flex-col gap-3 border-t border-border/60 pt-4 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-xs text-muted-foreground">
          {t(`${k}.saved_to`)} <span className="font-mono">data/runtime.env</span>
        </p>
        <div className="flex items-center gap-2">
          <button type="button" className={outlineBtn} onClick={obs.close}>
            {t(`${k}.close`)}
          </button>
          <button type="button" className={solidBtn} onClick={obs.save} disabled={obs.saving || obs.loading}>
            {obs.saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <Save className="h-3.5 w-3.5" aria-hidden />}
            {t(`${k}.save`)}
          </button>
        </div>
      </div>
    </Dialog>
  );
}
