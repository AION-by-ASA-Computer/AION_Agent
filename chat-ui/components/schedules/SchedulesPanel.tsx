"use client";

import { useCallback, useEffect, useLayoutEffect, useState } from "react";
import { CalendarClock, Plus } from "lucide-react";

import { ShellSectionHeader } from "@/components/layout/ShellSectionHeader";
import { ScheduleJobCard } from "@/components/schedules/ScheduleJobCard";
import {
  ScheduleJobDialog,
  ScheduleJobRuns,
} from "@/components/schedules/ScheduleJobDialog";
import { ScheduleStatsBar } from "@/components/schedules/ScheduleStatsBar";
import { SchedulesEmptyState } from "@/components/schedules/SchedulesEmptyState";
import {
  deleteCronJob,
  fetchCronJobsStatus,
  listCronJobs,
  patchCronJob,
  runCronJobNow,
  type ScheduledJobRow,
} from "@/lib/api/aion";
import { useStoredToken, useStoredUserId } from "@/lib/auth/use-stored-auth";
import { useShellActions } from "@/lib/shell/shell-context";
import { useT } from "@/lib/i18n/use-t";

export function SchedulesPanel() {
  const t = useT();
  const { setHeader, setDock, setDockOpen, clearChrome } = useShellActions();
  const userId = useStoredUserId();
  const token = useStoredToken();
  const [jobs, setJobs] = useState<ScheduledJobRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [cronEnabled, setCronEnabled] = useState(true);
  const [cronHint, setCronHint] = useState<string | null>(null);
  const [dialogMode, setDialogMode] = useState<"create" | "edit" | null>(null);
  const [editingJob, setEditingJob] = useState<ScheduledJobRow | null>(null);
  const [dialogSeed, setDialogSeed] = useState<{ name?: string; prompt?: string }>({});

  const load = useCallback(async () => {
    if (!userId) return;
    setLoading(true);
    setFetchError(null);
    try {
      const st = await fetchCronJobsStatus();
      setCronEnabled(Boolean(st.cron_enabled));
      setCronHint(st.hint || null);
      if (!st.cron_enabled) {
        setJobs([]);
        return;
      }
      const j = await listCronJobs(userId, token);
      setJobs(j);
    } catch (e: unknown) {
      setFetchError(e instanceof Error ? e.message : t("schedulesPage.load_error"));
    } finally {
      setLoading(false);
    }
  }, [userId, token, t]);

  useEffect(() => {
    void load();
  }, [load]);

  function openCreate(seed?: { name?: string; prompt?: string }) {
    setEditingJob(null);
    setDialogSeed(seed ?? {});
    setDialogMode("create");
  }

  function closeDialog() {
    setDialogMode(null);
    setEditingJob(null);
    setDialogSeed({});
    void load();
  }

  const headerAction = cronEnabled ? (
    <button
      type="button"
      onClick={() => openCreate()}
      className="focus-ring flex items-center gap-1.5 rounded-xl bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground shadow-sm hover:bg-primary/90"
    >
      <Plus className="h-4 w-4" aria-hidden />
      {t("schedulesPage.new")}
    </button>
  ) : null;

  useLayoutEffect(() => {
    setHeader(
      <ShellSectionHeader
        title={t("schedulesPage.title")}
        subtitle={t("schedulesPage.subtitle")}
        icon={<CalendarClock className="h-5 w-5" aria-hidden />}
        action={headerAction}
      />,
    );
    setDock(null);
    setDockOpen(false);
  }, [setHeader, setDock, setDockOpen, t, headerAction]);

  useLayoutEffect(() => {
    return () => clearChrome();
  }, [clearChrome]);

  const active = jobs.filter((j) => j.enabled);
  const paused = jobs.filter((j) => !j.enabled);

  if (loading) {
    return (
      <div className="flex flex-1 items-center justify-center p-8 text-muted-foreground">
        {t("schedulesPage.loading")}
      </div>
    );
  }

  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto max-w-3xl px-4 py-6 sm:px-6">
        {!cronEnabled ? (
          <div className="mb-4 rounded-2xl border border-amber-500/35 bg-amber-500/10 px-4 py-3 text-sm text-amber-900 dark:text-amber-200">
            {cronHint || t("schedulesPage.feature_disabled")}
          </div>
        ) : null}

        {fetchError ? (
          <div className="mb-4 rounded-2xl border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm text-destructive">
            {fetchError}
          </div>
        ) : null}

        <ScheduleStatsBar total={jobs.length} active={active.length} paused={paused.length} />

        {active.length > 0 ? (
          <section className="mb-8">
            <h2 className="mb-3 text-[0.786em] font-bold uppercase tracking-wider text-muted-foreground">
              {t("schedulesPage.section_active")}
            </h2>
            <div className="space-y-3">
              {active.map((job) => (
                <ScheduleJobCard
                  key={job.job_id}
                  job={job}
                  onEdit={() => {
                    setEditingJob(job);
                    setDialogMode("edit");
                  }}
                  onToggle={() => void toggleJob(job)}
                  onRunNow={() => void runNow(job.job_id)}
                  onDelete={() => void removeJob(job.job_id)}
                  runsSlot={
                    userId ? (
                      <ScheduleJobRuns jobId={job.job_id} userId={userId} token={token} />
                    ) : null
                  }
                />
              ))}
            </div>
          </section>
        ) : null}

        {paused.length > 0 ? (
          <section className="mb-8">
            <h2 className="mb-3 text-[0.786em] font-bold uppercase tracking-wider text-muted-foreground">
              {t("schedulesPage.section_paused")}
            </h2>
            <div className="space-y-3">
              {paused.map((job) => (
                <ScheduleJobCard
                  key={job.job_id}
                  job={job}
                  onEdit={() => {
                    setEditingJob(job);
                    setDialogMode("edit");
                  }}
                  onToggle={() => void toggleJob(job)}
                  onRunNow={() => void runNow(job.job_id)}
                  onDelete={() => void removeJob(job.job_id)}
                  runsSlot={
                    userId ? (
                      <ScheduleJobRuns jobId={job.job_id} userId={userId} token={token} />
                    ) : null
                  }
                />
              ))}
            </div>
          </section>
        ) : null}

        {jobs.length === 0 && !fetchError && cronEnabled ? (
          <SchedulesEmptyState
            onCreate={() => openCreate()}
            onUseTemplate={(prompt, name) => openCreate({ prompt, name })}
          />
        ) : null}

        {dialogMode && userId ? (
          <ScheduleJobDialog
            mode={dialogMode}
            job={editingJob}
            userId={userId}
            token={token}
            initialName={dialogSeed.name}
            initialPrompt={dialogSeed.prompt}
            onClose={closeDialog}
          />
        ) : null}
      </div>
    </div>
  );

  async function toggleJob(job: ScheduledJobRow) {
    if (!userId) return;
    await patchCronJob(userId, job.job_id, { enabled: !job.enabled }, token);
    await load();
  }

  async function removeJob(jobId: string) {
    if (!userId || !confirm(t("schedulesPage.delete_confirm"))) return;
    await deleteCronJob(userId, jobId, token);
    await load();
  }

  async function runNow(jobId: string) {
    if (!userId) return;
    await runCronJobNow(userId, jobId, token);
    await load();
  }
}
