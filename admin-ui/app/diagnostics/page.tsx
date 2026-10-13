"use client";

import { useMemo, useState } from "react";
import { ArrowDownToLine, Play, Square } from "lucide-react";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";
import { Select } from "@/components/ui/Select";
import { dangerBtn, outlineBtn, solidBtn } from "@/components/ui/classes";
import { useDiagnostics } from "@/components/diagnostics/useDiagnostics";
import { SCENARIOS } from "@/components/diagnostics/scenarioList";
import { Scenarios } from "@/components/diagnostics/Scenarios";
import { Stream } from "@/components/diagnostics/Stream";
import { ReportReader } from "@/components/diagnostics/ReportReader";
import { History } from "@/components/diagnostics/History";
import { ResultDialog } from "@/components/diagnostics/ResultDialog";

const k = "admin_diagnostics";
type Tab = "stream" | "report" | "history";

export default function DiagnosticsPage() {
  const t = useT();
  const d = useDiagnostics(t);
  const [tab, setTab] = useState<Tab>("stream");
  const [filter, setFilter] = useState("all");
  const [autoScroll, setAutoScroll] = useState(true);
  const [openId, setOpenId] = useState<string | null>(null);

  const profileOptions = useMemo(
    () =>
      d.profiles.length > 0
        ? d.profiles.map((p) => ({ value: p.slug, label: p.name, description: p.description || p.slug }))
        : [{ value: d.profile, label: d.profile }],
    [d.profiles, d.profile],
  );
  const filterOptions = useMemo(
    () => [{ value: "all", label: t(`${k}.stream.filter_all`) }, ...SCENARIOS.map((s) => ({ value: s.id, label: t(`${k}.scenarios.item.${s.key}.name`) }))],
    [t],
  );
  const logs = useMemo(() => (filter === "all" ? d.logs : d.logs.filter((l) => l.test === filter)), [d.logs, filter]);

  const tabs: { id: Tab; label: string; count?: number; dot?: boolean }[] = [
    { id: "stream", label: t(`${k}.tabs.stream`) },
    { id: "report", label: t(`${k}.tabs.report`), dot: !!d.report.content },
    { id: "history", label: t(`${k}.tabs.history`), count: d.history.length },
  ];

  const opened = openId ? SCENARIOS.find((s) => s.id === openId) : null;

  return (
    // On desktop the page is exactly one viewport tall (shell header + padding = 6.5rem): the stream fills what the
    // scenarios leave, so nothing but the stream scrolls. Shorter screens fall back to normal page scroll.
    <div className="mx-auto flex max-w-[84rem] flex-col gap-6 lg:h-[calc(100dvh-6.5rem)] lg:min-h-[40rem]">
      <header className="flex flex-col gap-4 pt-2 lg:flex-row lg:items-end">
        <div className="min-w-0 flex-1">
          <h1 className="text-balance text-2xl font-semibold tracking-[-0.02em] sm:text-[28px]">{t(`${k}.title`)}</h1>
          <p className="mt-1 max-w-[60ch] text-sm text-muted-foreground">{t(`${k}.subtitle`)}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="w-full sm:w-64">
            <Select
              size="sm"
              value={d.profile}
              onChange={d.setProfile}
              options={profileOptions}
              disabled={d.running || d.profilesLoading}
              placeholder={d.profilesLoading ? t(`${k}.profile_loading`) : t(`${k}.profile_label`)}
              aria-label={t(`${k}.profile_label`)}
            />
          </div>
          {d.running ? (
            <button type="button" className={dangerBtn} onClick={d.stop}>
              <Square className="h-3.5 w-3.5 fill-current" aria-hidden />
              {t(`${k}.stop`)}
            </button>
          ) : (
            <button type="button" className={solidBtn} onClick={d.run} disabled={d.profilesLoading}>
              <Play className="h-3.5 w-3.5 fill-current" aria-hidden />
              {t(`${k}.run`)}
            </button>
          )}
        </div>
      </header>

      <Scenarios tests={d.tests} onOpen={setOpenId} t={t} />

      <div className="flex flex-col gap-4 lg:min-h-0 lg:flex-1">
        <div className="flex flex-wrap items-end gap-x-4 gap-y-2 border-b border-border">
          <div role="tablist" aria-label={t(`${k}.tabs.aria`)} className="flex gap-1">
            {tabs.map((tb) => (
              <button
                key={tb.id}
                type="button"
                role="tab"
                id={`diag-tab-${tb.id}`}
                aria-selected={tab === tb.id}
                aria-controls="diag-panel"
                onClick={() => setTab(tb.id)}
                className={cn(
                  "focus-ring -mb-px flex items-center gap-2 border-b-2 px-3.5 pb-3 pt-1 text-sm font-medium transition-colors",
                  tab === tb.id ? "border-foreground text-foreground" : "border-transparent text-muted-foreground hover:text-foreground",
                )}
              >
                {tb.label}
                {tb.count !== undefined && <span className="text-xs tabular-nums text-muted-foreground">{tb.count}</span>}
                {tb.dot && <span className="h-1.5 w-1.5 rounded-full bg-success" aria-hidden />}
              </button>
            ))}
          </div>

          {tab === "stream" && (
            <div className="mb-2 ml-auto flex items-center gap-2">
              <div className="w-48">
                <Select size="sm" value={filter} onChange={setFilter} options={filterOptions} aria-label={t(`${k}.stream.filter_aria`)} />
              </div>
              <button
                type="button"
                aria-pressed={autoScroll}
                onClick={() => setAutoScroll((a) => !a)}
                className={cn(outlineBtn, autoScroll && "border-foreground/30 bg-secondary")}
              >
                <ArrowDownToLine className="h-3.5 w-3.5" aria-hidden />
                {t(`${k}.stream.autoscroll`)}
              </button>
            </div>
          )}
        </div>

        <div id="diag-panel" role="tabpanel" aria-labelledby={`diag-tab-${tab}`} className="lg:min-h-0 lg:flex-1 lg:overflow-y-auto">
          {tab === "stream" && <Stream logs={logs} running={d.running} autoScroll={autoScroll} t={t} />}
          {tab === "report" && <ReportReader content={d.report.content} name={d.report.name} t={t} />}
          {tab === "history" && (
            <History
              items={d.history}
              state={d.historyState}
              onRefresh={d.loadHistory}
              onOpen={async (filename) => {
                if (await d.openReport(filename)) setTab("report");
              }}
              t={t}
            />
          )}
        </div>
      </div>

      {opened && d.tests[opened.id] && (
        <ResultDialog
          key={opened.id}
          test={d.tests[opened.id]}
          scenarioName={t(`${k}.scenarios.item.${opened.key}.name`)}
          profile={d.profile}
          onClose={() => setOpenId(null)}
          t={t}
        />
      )}
    </div>
  );
}
