"use client";

import { useMemo } from "react";
import { Loader2, RefreshCw, SlidersHorizontal } from "lucide-react";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";
import { getLocale } from "@/lib/i18n/i18n-store";
import { Select } from "@/components/ui/Select";
import { outlineBtn } from "@/components/ui/classes";
import { makeFormat, formatStamp } from "@/components/metrics/format";
import { useMetrics } from "@/components/metrics/useMetrics";
import { useObservability } from "@/components/metrics/useObservability";
import { Summary } from "@/components/metrics/Summary";
import { Panel, ProfilesTable, ToolsTable, UsersTable } from "@/components/metrics/Tables";
import { ErrorsPanel, ModelsPanel } from "@/components/metrics/Panels";
import { ObservabilityDialog } from "@/components/metrics/ObservabilityDialog";
import { TIME_RANGES } from "@/components/metrics/types";

const k = "admin_metrics";

export default function MetricsPage() {
  const t = useT();
  const locale = getLocale();
  const fmt = useMemo(() => makeFormat(locale), [locale]);
  const d = useMetrics();
  const m = d.metrics;

  const obs = useObservability(d.reload, {
    restarted: t(`${k}.config.restarted`),
    timeout: t(`${k}.config.restart_timeout`),
    loadFailed: t(`${k}.config.load_failed`),
    saved: t(`${k}.config.saved`),
    probeOk: t(`${k}.config.probe_ok`),
    probeFail: t(`${k}.config.probe_fail`),
    network: t(`${k}.config.probe_network`),
  });

  const rangeName = (r: string) => t(`${k}.range_name.${r}`);
  const rangeLabel = rangeName(d.range);
  const stamp = (ts: string) => formatStamp(ts, d.range, locale);

  const userOptions = [
    { value: "", label: t(`${k}.filter.all_users`) },
    ...d.users.map((u) => {
      const value = u.identifier || u.id || "";
      return { value, label: u.identifier || u.display_name || u.id };
    }),
  ];
  const profileOptions = [
    { value: "", label: t(`${k}.filter.all_profiles`) },
    ...d.profiles.map((p) => ({ value: p.slug || p.name, label: p.name })),
  ];

  const time = d.updatedAt ? new Intl.DateTimeFormat(locale, { hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(d.updatedAt) : null;
  const firstLoad = d.loading && !m;

  return (
    <div className="mx-auto flex max-w-[84rem] flex-col gap-6">
      <header className="flex flex-col gap-4 pt-2 sm:flex-row sm:items-end">
        <div className="min-w-0 flex-1">
          <h1 className="text-balance text-2xl font-semibold tracking-[-0.02em] sm:text-[28px]">{t(`${k}.title`)}</h1>
          <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-muted-foreground">
            {m ? (
              <>
                <span className={cn("h-2 w-2 shrink-0 rounded-full", m.prometheus_connected ? "bg-success" : "bg-warning")} aria-hidden />
                <span title={m.prometheus_url}>{m.prometheus_connected ? t(`${k}.source.prometheus`) : t(`${k}.source.local`)}</span>
                {!m.prometheus_connected && <span className="hidden sm:inline">· {t(`${k}.source.local_detail`)}</span>}
              </>
            ) : (
              <span>{t(`${k}.subtitle`)}</span>
            )}
          </p>
        </div>
        <button type="button" className={outlineBtn} onClick={obs.show}>
          <SlidersHorizontal className="h-3.5 w-3.5" aria-hidden />
          {t(`${k}.configure`)}
        </button>
      </header>

      <div className="flex flex-wrap items-center gap-2">
        <Select size="sm" value={d.user} onChange={d.setUser} options={userOptions} aria-label={t(`${k}.filter.user`)} className="w-48 bg-card" />
        <Select size="sm" value={d.profile} onChange={d.setProfile} options={profileOptions} aria-label={t(`${k}.filter.profile`)} className="w-48 bg-card" />

        <div role="group" aria-label={t(`${k}.filter.range`)} className="inline-flex h-9 items-center rounded-xl border border-border bg-card p-0.5">
          {TIME_RANGES.map((r) => (
            <button
              key={r}
              type="button"
              aria-pressed={d.range === r}
              onClick={() => d.setRange(r)}
              className={cn(
                "focus-ring h-8 rounded-[10px] px-2.5 text-sm font-medium tabular-nums transition-colors",
                d.range === r ? "bg-secondary text-foreground" : "text-muted-foreground hover:text-foreground",
              )}
            >
              {r === "all" ? t(`${k}.range_all`) : r}
            </button>
          ))}
        </div>

        <div className="ml-auto flex items-center gap-2">
          {time && <span className="hidden text-xs tabular-nums text-muted-foreground md:inline">{t(`${k}.updated_at`, { time })}</span>}
          <button
            type="button"
            aria-pressed={d.live}
            onClick={() => d.setLive(!d.live)}
            title={t(`${k}.live_hint`)}
            className={cn(
              "focus-ring inline-flex h-9 items-center gap-2 rounded-xl border px-3 text-sm font-medium transition-colors",
              d.live ? "border-border bg-secondary" : "border-border bg-card text-muted-foreground hover:bg-secondary",
            )}
          >
            <span className={cn("h-2 w-2 rounded-full", d.live ? "bg-success" : "bg-muted-foreground/50")} aria-hidden />
            {d.live ? t(`${k}.live_on`) : t(`${k}.live_off`)}
          </button>
          <button type="button" className={outlineBtn} onClick={d.reload} disabled={d.loading}>
            <RefreshCw className={cn("h-3.5 w-3.5", d.loading && "animate-spin")} aria-hidden />
            {t(`${k}.refresh`)}
          </button>
        </div>
      </div>

      {d.failed && !m ? (
        <div className="flex flex-col items-start gap-3 rounded-3xl border border-dashed border-border px-6 py-14">
          <p className="text-sm text-destructive" role="alert">
            {t(`${k}.error`)}
          </p>
          <button type="button" className={outlineBtn} onClick={d.reload}>
            {t(`${k}.retry`)}
          </button>
        </div>
      ) : (
        <>
          {d.failed && (
            <p className="-mt-2 text-sm text-warning" role="status">
              {t(`${k}.stale`)}
            </p>
          )}
          {firstLoad && (
            <div className="flex items-center gap-2 px-1 text-sm text-muted-foreground" role="status">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
              {t(`${k}.loading`)}
            </div>
          )}

          <Summary m={m} fmt={fmt} rangeLabel={rangeLabel} stamp={stamp} t={t} />

          <ErrorsPanel errors={m?.mcp_call_errors ?? []} range={rangeLabel} locale={locale} t={t} />

          <Panel id="metrics-profiles-title" title={t(`${k}.profiles.title`)} meta={t(`${k}.profiles.count`, { n: m?.profile_metrics?.length ?? 0 })}>
            <ProfilesTable rows={m?.profile_metrics ?? []} fmt={fmt} range={rangeLabel} t={t} />
          </Panel>

          <Panel id="metrics-users-title" title={t(`${k}.users.title`)} meta={t(`${k}.users.count`, { n: m?.user_metrics?.length ?? 0 })}>
            <UsersTable rows={m?.user_metrics ?? []} fmt={fmt} range={rangeLabel} t={t} />
          </Panel>

          <div className="grid gap-6 xl:grid-cols-2 xl:items-start">
            <ToolsTable rows={m?.tool_metrics ?? []} fmt={fmt} range={rangeLabel} t={t} />
            <ModelsPanel usage={m?.token_usage_by_model ?? {}} fmt={fmt} range={rangeLabel} t={t} />
          </div>
        </>
      )}

      {obs.open && <ObservabilityDialog obs={obs} t={t} />}

      {obs.restarting && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/55 p-4" role="alertdialog" aria-modal="true" aria-labelledby="obs-restart-title" aria-describedby="obs-restart-body">
          <div className="w-full max-w-md rounded-3xl border border-border bg-card p-6 shadow-[0_24px_60px_-20px_rgba(0,0,0,0.45)]">
            <div className="flex items-center gap-3">
              <Loader2 className="h-5 w-5 shrink-0 animate-spin text-muted-foreground" aria-hidden />
              <h2 id="obs-restart-title" className="text-lg font-semibold tracking-[-0.015em]">
                {t(`${k}.restart.title`)}
              </h2>
            </div>
            <p id="obs-restart-body" className="mt-2 text-sm text-muted-foreground">
              {t(`${k}.restart.body`)}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
