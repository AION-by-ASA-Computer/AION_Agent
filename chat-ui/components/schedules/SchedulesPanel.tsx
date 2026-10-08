"use client";

import { useCallback, useEffect, useLayoutEffect, useMemo, useState } from "react";
import { CalendarClock, CheckCircle2, PauseCircle, Plus, Search, X } from "lucide-react";

import { ShellSectionHeader } from "@/components/layout/ShellSectionHeader";
import { ScheduleJobCard } from "@/components/schedules/ScheduleJobCard";
import { DeleteScheduleDialog } from "@/components/schedules/DeleteScheduleDialog";
import {
  ScheduleJobDialog,
  ScheduleJobRuns,
} from "@/components/schedules/ScheduleJobDialog";
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
import { cn } from "@/lib/cn";

type FilterTab = "all" | "active" | "paused";

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

  const [searchQuery, setSearchQuery] = useState("");
  const [selectedTab, setSelectedTab] = useState<FilterTab>("all");
  const [expandedJobId, setExpandedJobId] = useState<string | null>(null);
  const [deletingJob, setDeletingJob] = useState<ScheduledJobRow | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);

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
      className="focus-ring flex items-center gap-1.5 rounded-xl bg-primary px-4 py-2 text-xs sm:text-sm font-semibold text-primary-foreground shadow-sm hover:bg-primary/90 transition cursor-pointer"
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

  const activeJobs = useMemo(() => jobs.filter((j) => j.enabled), [jobs]);
  const pausedJobs = useMemo(() => jobs.filter((j) => !j.enabled), [jobs]);

  const filterBySearch = useCallback(
    (list: ScheduledJobRow[]) => {
      const q = searchQuery.trim().toLowerCase();
      if (!q) return list;
      return list.filter(
        (j) =>
          j.name.toLowerCase().includes(q) ||
          j.profile_slug.toLowerCase().includes(q) ||
          j.cron_expression.toLowerCase().includes(q),
      );
    },
    [searchQuery],
  );

  const filteredActive = useMemo(() => filterBySearch(activeJobs), [activeJobs, filterBySearch]);
  const filteredPaused = useMemo(() => filterBySearch(pausedJobs), [pausedJobs, filterBySearch]);

  const totalFilteredCount =
    (selectedTab === "all" || selectedTab === "active" ? filteredActive.length : 0) +
    (selectedTab === "all" || selectedTab === "paused" ? filteredPaused.length : 0);

  async function toggleJob(job: ScheduledJobRow) {
    if (!userId) return;
    await patchCronJob(userId, job.job_id, { enabled: !job.enabled }, token);
    await load();
  }

  async function handleConfirmDelete() {
    if (!userId || !deletingJob) return;
    setIsDeleting(true);
    try {
      await deleteCronJob(userId, deletingJob.job_id, token);
      setDeletingJob(null);
      await load();
    } catch (e: unknown) {
      setFetchError(e instanceof Error ? e.message : "Errore durante l'eliminazione");
    } finally {
      setIsDeleting(false);
    }
  }

  async function runNow(jobId: string) {
    if (!userId) return;
    await runCronJobNow(userId, jobId, token);
    await load();
  }

  if (loading) {
    return (
      <div className="flex flex-1 items-center justify-center p-8 text-sm text-muted-foreground">
        {t("schedulesPage.loading")}
      </div>
    );
  }

  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto max-w-5xl px-4 py-8 sm:px-6 lg:px-8 space-y-8">
        {/* Avvisi Stato Cron / Feature Disabled */}
        {!cronEnabled ? (
          <div className="rounded-2xl border border-amber-500/35 bg-amber-500/10 px-4 py-3 text-xs sm:text-sm text-amber-900 dark:text-amber-200">
            {cronHint || t("schedulesPage.feature_disabled")}
          </div>
        ) : null}

        {fetchError ? (
          <div className="rounded-2xl border border-destructive/40 bg-destructive/10 px-4 py-3 text-xs sm:text-sm text-destructive">
            {fetchError}
          </div>
        ) : null}

        {/* Toolbar: Ricerca & Tab Categorie (stile Integrazioni) */}
        {jobs.length > 0 && cronEnabled ? (
          <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3 pb-2 border-b border-border/60">
            {/* Tab Categorie */}
            <div className="flex flex-wrap items-center gap-1.5 p-1 rounded-2xl bg-muted/40 border border-border/60">
              <button
                type="button"
                onClick={() => setSelectedTab("all")}
                className={cn(
                  "focus-ring inline-flex items-center gap-1.5 rounded-xl px-3 py-1.5 text-xs font-semibold transition cursor-pointer",
                  selectedTab === "all"
                    ? "bg-background text-foreground shadow-sm"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                <span>Tutte</span>
                <span className="rounded-full bg-muted px-1.5 py-0.2 text-[10px] font-bold">
                  {jobs.length}
                </span>
              </button>

              <button
                type="button"
                onClick={() => setSelectedTab("active")}
                className={cn(
                  "focus-ring inline-flex items-center gap-1.5 rounded-xl px-3 py-1.5 text-xs font-semibold transition cursor-pointer",
                  selectedTab === "active"
                    ? "bg-background text-emerald-600 dark:text-emerald-400 shadow-sm"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />
                <span>Attive</span>
                <span className="rounded-full bg-emerald-500/15 px-1.5 py-0.2 text-[10px] font-bold text-emerald-700 dark:text-emerald-300">
                  {activeJobs.length}
                </span>
              </button>

              <button
                type="button"
                onClick={() => setSelectedTab("paused")}
                className={cn(
                  "focus-ring inline-flex items-center gap-1.5 rounded-xl px-3 py-1.5 text-xs font-semibold transition cursor-pointer",
                  selectedTab === "paused"
                    ? "bg-background text-amber-600 dark:text-amber-400 shadow-sm"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                <PauseCircle className="h-3.5 w-3.5 text-amber-500" />
                <span>Ferme</span>
                <span className="rounded-full bg-amber-500/15 px-1.5 py-0.2 text-[10px] font-bold text-amber-800 dark:text-amber-300">
                  {pausedJobs.length}
                </span>
              </button>
            </div>

            {/* Barra di Ricerca */}
            <div className="relative w-full sm:w-64">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground pointer-events-none" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Cerca per nome o profilo…"
                className="w-full rounded-xl border border-border/80 bg-background pl-9 pr-8 py-1.5 text-xs text-foreground placeholder:text-muted-foreground focus:border-primary focus:ring-2 focus:ring-primary/20 outline-none transition"
              />
              {searchQuery ? (
                <button
                  type="button"
                  onClick={() => setSearchQuery("")}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground p-0.5 rounded-full cursor-pointer"
                >
                  <X className="h-3 w-3" />
                </button>
              ) : null}
            </div>
          </div>
        ) : null}

        {/* Nessun risultato dalla ricerca */}
        {jobs.length > 0 && totalFilteredCount === 0 ? (
          <div className="py-12 text-center text-sm text-muted-foreground rounded-2xl border border-dashed border-border/80 bg-card/40">
            Nessuna automazione trovata per i filtri selezionati.
          </div>
        ) : null}

        {/* Sezione 1: Automazioni Attive */}
        {(selectedTab === "all" || selectedTab === "active") && filteredActive.length > 0 ? (
          <section className="space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <CheckCircle2 className="h-4 w-4 text-emerald-500" />
                <h2 className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
                  Automazioni attive
                </h2>
                <span className="rounded-full bg-emerald-500/15 px-2 py-0.5 text-[10px] font-bold text-emerald-700 dark:text-emerald-300">
                  {filteredActive.length}
                </span>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-5 items-start">
              {filteredActive.map((job) => (
                <ScheduleJobCard
                  key={job.job_id}
                  job={job}
                  onEdit={() => {
                    setEditingJob(job);
                    setDialogMode("edit");
                  }}
                  onToggle={() => void toggleJob(job)}
                  onRunNow={() => void runNow(job.job_id)}
                  onDelete={() => setDeletingJob(job)}
                  runsSlot={
                    userId ? (
                      <ScheduleJobRuns
                        jobId={job.job_id}
                        userId={userId}
                        token={token}
                        expanded={expandedJobId === job.job_id}
                        onToggleExpand={() =>
                          setExpandedJobId((curr) => (curr === job.job_id ? null : job.job_id))
                        }
                      />
                    ) : null
                  }
                />
              ))}
            </div>
          </section>
        ) : null}

        {/* Sezione 2: Automazioni in pausa / ferme */}
        {(selectedTab === "all" || selectedTab === "paused") && filteredPaused.length > 0 ? (
          <section className="space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <PauseCircle className="h-4 w-4 text-amber-500" />
                <h2 className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
                  Automazioni in pausa
                </h2>
                <span className="rounded-full bg-amber-500/15 px-2 py-0.5 text-[10px] font-bold text-amber-800 dark:text-amber-300">
                  {filteredPaused.length}
                </span>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-5 items-start">
              {filteredPaused.map((job) => (
                <ScheduleJobCard
                  key={job.job_id}
                  job={job}
                  onEdit={() => {
                    setEditingJob(job);
                    setDialogMode("edit");
                  }}
                  onToggle={() => void toggleJob(job)}
                  onRunNow={() => void runNow(job.job_id)}
                  onDelete={() => setDeletingJob(job)}
                  runsSlot={
                    userId ? (
                      <ScheduleJobRuns
                        jobId={job.job_id}
                        userId={userId}
                        token={token}
                        expanded={expandedJobId === job.job_id}
                        onToggleExpand={() =>
                          setExpandedJobId((curr) => (curr === job.job_id ? null : job.job_id))
                        }
                      />
                    ) : null
                  }
                />
              ))}
            </div>
          </section>
        ) : null}

        {/* Stato Vuoto se 0 automazioni */}
        {jobs.length === 0 && !fetchError && cronEnabled ? (
          <SchedulesEmptyState
            onCreate={() => openCreate()}
            onUseTemplate={(prompt, name) => openCreate({ prompt, name })}
          />
        ) : null}

        {/* Modale Creazione / Modifica Automazione */}
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

        {/* Modale Eliminazione Automazione */}
        {deletingJob ? (
          <DeleteScheduleDialog
            job={deletingJob}
            onClose={() => setDeletingJob(null)}
            onConfirm={handleConfirmDelete}
            deleting={isDeleting}
          />
        ) : null}
      </div>
    </div>
  );
}
