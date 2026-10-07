"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  BookOpen,
  CheckCircle2,
  ChevronRight,
  Circle,
  ExternalLink,
  Globe,
  HelpCircle,
  History,
  Lightbulb,
  Loader2,
  Plus,
  Search,
  Sparkles,
  Trash2,
  XCircle,
} from "lucide-react";
import {
  cancelResearch,
  deleteResearch,
  fetchActiveResearch,
  fetchResearchLibrary,
  fetchResearchStatus,
  forgetWatchedResearch,
  loadWatchedResearch,
  rememberWatchedResearch,
  reportUrl,
  subscribeResearchStream,
  type ResearchActivity,
  type ResearchJob,
  type ResearchLibraryItem,
  type ResearchProgress,
} from "@/lib/api/research";
import { cn } from "@/lib/cn";
import { researchLog } from "@/lib/research-debug";
import { useT } from "@/lib/i18n/use-t";

type JobState = ResearchJob & { progress?: ResearchProgress; done?: boolean };

function formatElapsed(startedAt?: number, completedAt?: number): string {
  if (!startedAt) return "";
  const end = completedAt || Date.now() / 1000;
  const sec = Math.max(0, Math.floor(end - startedAt));
  if (sec < 60) return `${sec}s`;
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${m}m ${s}s`;
}

function formatTime(ts?: number): string {
  if (!ts) return "";
  return new Date(ts * 1000).toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function statusLabel(status: string, t: ReturnType<typeof useT>): string {
  switch (status) {
    case "running":
      return t("research.status.running");
    case "done":
      return t("research.status.done");
    case "error":
      return t("research.status.error");
    case "cancelled":
      return t("research.status.cancelled");
    case "interrupted":
      return t("research.status.interrupted");
    default:
      return status;
  }
}

function activityIcon(act: ResearchActivity, isLatest: boolean, isJobRunning?: boolean) {
  if (act.phase === "error")
    return <XCircle className="h-3.5 w-3.5 shrink-0 text-red-500" />;
  if (act.phase === "warning")
    return <Circle className="h-3.5 w-3.5 shrink-0 text-amber-400" />;
  if (isLatest && isJobRunning)
    return <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-violet-400" />;
  return <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-emerald-500/90" />;
}

function progressSummary(j: JobState, t: ReturnType<typeof useT>): string {
  if (j.status === "done" || j.done) return t("research.phase.done_summary") || "Ricerca completata con successo";
  if (j.status === "error") return t("research.phase.error_summary") || "Ricerca terminata con errore";
  if (j.status === "cancelled") return t("research.status.cancelled") || "Ricerca annullata";
  const acts = j.activities?.length ? j.activities : j.progress?.activities;
  if (acts?.length) {
    const last = acts[acts.length - 1];
    if (last?.label) return last.label;
    if (last?.message) return last.message;
  }
  const p = j.progress;
  if (p?.label) return p.label;
  if (p?.message) return p.message;
  const phase = p?.phase;
  if (phase === "probing") return t("research.phase.probing");
  if (phase === "planning") return t("research.phase.planning");
  if (phase === "searching") return t("research.phase.searching");
  if (phase === "reading") return t("research.phase.reading");
  if (phase === "writing") return t("research.phase.writing");
  if (j.status === "running") return t("research.phase.running_summary");
  return t("research.phase.starting");
}

function progressPercent(j: JobState): number | null {
  if (j.status === "done" || j.done) return 100;
  const round = j.progress?.round;
  const maxRounds = j.progress?.max_rounds;
  if (round && maxRounds && maxRounds > 0) {
    return Math.min(95, Math.round((round / maxRounds) * 100));
  }
  if (j.status === "running") return null;
  return 100;
}

export function DeepResearchPanel({
  userId,
  token,
  conversationId,
  adoptSessionId,
  adoptQuery,
  onAdoptHandled,
  onPromptSuggestion,
}: {
  userId: string;
  token?: string | null;
  conversationId: string;
  adoptSessionId?: string | null;
  adoptQuery?: string | null;
  onAdoptHandled?: () => void;
  onPromptSuggestion?: (text: string) => void;
}) {
  const t = useT();
  const [jobs, setJobs] = useState<JobState[]>([]);
  const [past, setPast] = useState<ResearchLibraryItem[]>([]);
  const [tick, setTick] = useState(0);

  const jobsRef = useRef<JobState[]>([]);
  jobsRef.current = jobs;

  const refreshRef = useRef<() => void>(() => { });
  const unsubRef = useRef<Map<string, () => void>>(new Map());

  useEffect(() => {
    const timer = setInterval(() => setTick((n) => n + 1), 1000);
    return () => clearInterval(timer);
  }, []);

  const refreshLibrary = useCallback(async () => {
    const lib = await fetchResearchLibrary(userId, token);
    const activeFromBackend = await fetchActiveResearch(userId, token);
    const watched = loadWatchedResearch(conversationId);

    researchLog("refresh library", {
      backendActive: activeFromBackend.length,
      watched: watched.length,
    });

    // Cleanup finished items from watched list
    for (const item of lib) {
      if (item.status !== "running") {
        forgetWatchedResearch(item.id, conversationId);
      }
    }

    const completedLibIds = new Set(
      lib.filter((x) => x.status !== "running").map((x) => x.id)
    );

    const activeMap = new Map<string, JobState>();

    for (const w of watched) {
      if (!completedLibIds.has(w.id)) {
        activeMap.set(w.id, {
          session_id: w.id,
          query: w.query,
          status: "running",
          started_at: w.ts / 1000,
        });
      }
    }

    for (const b of activeFromBackend) {
      if (!completedLibIds.has(b.session_id)) {
        const prev = activeMap.get(b.session_id);
        activeMap.set(b.session_id, {
          ...prev,
          ...b,
          status: b.status || "running",
        });
      }
    }

    for (const item of lib) {
      if (item.status === "running") {
        const prev = activeMap.get(item.id);
        activeMap.set(item.id, {
          ...prev,
          session_id: item.id,
          query: item.query || prev?.query || "",
          status: "running",
          started_at: item.started_at || prev?.started_at,
        });
      }
    }

    setJobs((prev) => {
      const merged: JobState[] = [];
      for (const [sid, job] of activeMap.entries()) {
        const existing = prev.find((x) => x.session_id === sid);
        const isAlreadyDone = existing?.done || existing?.status === "done" || existing?.status === "error";
        merged.push({
          ...job,
          status: isAlreadyDone ? (existing?.status || job.status) : job.status,
          progress: existing?.progress ?? job.progress,
          activities: existing?.activities ?? job.activities,
          done: isAlreadyDone ? true : existing?.done,
        });
      }
      return merged;
    });

    for (const sid of activeMap.keys()) {
      if (!unsubRef.current.has(sid)) {
        attachStreamRef.current(sid);
      }
    }

    setPast(
      lib
        .filter((x) => x.status !== "running")
        .sort((a, b) => {
          const ta = a.completed_at || a.started_at || 0;
          const tb = b.completed_at || b.started_at || 0;
          return tb - ta;
        })
    );
  }, [userId, token, conversationId]);

  refreshRef.current = () => {
    void refreshLibrary();
  };

  const attachStreamRef = useRef<(sessionId: string) => void>(() => { });

  const attachStream = useCallback(
    (sessionId: string) => {
      if (unsubRef.current.has(sessionId)) {
        return;
      }
      const unsub = subscribeResearchStream(
        sessionId,
        userId,
        token,
        (ev) => {
          const isFinal = Boolean(
            ev.final ||
            ev.status === "done" ||
            ev.status === "error" ||
            ev.status === "cancelled"
          );
          if (isFinal) {
            forgetWatchedResearch(sessionId, conversationId);
          }
          setJobs((prev) => {
            const idx = prev.findIndex((j) => j.session_id === sessionId);
            const patch = (j: JobState): JobState => {
              const mergedActs =
                (ev.activities?.length || 0) >= (j.activities?.length || 0)
                  ? ev.activities
                  : j.activities;
              const nextStatus = ev.status || (isFinal ? "done" : j.status);
              return {
                ...j,
                progress: ev,
                activities: mergedActs ?? j.activities,
                status: nextStatus,
                completed_at: (ev as any).completed_at ?? (isFinal ? Date.now() / 1000 : j.completed_at),
                done: isFinal || j.done,
              };
            };
            if (idx === -1) {
              return [
                {
                  session_id: sessionId,
                  query: "",
                  status: ev.status || (isFinal ? "done" : "running"),
                  progress: ev,
                  activities: ev.activities,
                  completed_at: (ev as any).completed_at ?? (isFinal ? Date.now() / 1000 : undefined),
                  done: isFinal,
                },
                ...prev,
              ];
            }
            return prev.map((j) => (j.session_id === sessionId ? patch(j) : j));
          });
        },
        () => {
          unsubRef.current.delete(sessionId);
          refreshRef.current();
        }
      );
      unsubRef.current.set(sessionId, unsub);
    },
    [userId, token, conversationId]
  );

  attachStreamRef.current = attachStream;

  const prevConversationRef = useRef(conversationId);

  useEffect(() => {
    const conversationChanged = prevConversationRef.current !== conversationId;
    prevConversationRef.current = conversationId;
    if (conversationChanged) {
      unsubRef.current.forEach((u) => u());
      unsubRef.current.clear();
      setJobs([]);
      setPast([]);
    }

    void refreshLibrary();
    const slow = setInterval(() => void refreshLibrary(), 8000);
    const fast = setInterval(() => {
      const running = jobsRef.current.filter((j) => j.status === "running" && !j.done);
      if (!running.length) return;
      void Promise.all(
        running.map(async (j) => {
          const st = await fetchResearchStatus(j.session_id, userId, token);
          if (!st) return;
          const isDone = st.status !== "running";
          if (isDone) {
            forgetWatchedResearch(j.session_id, conversationId);
          }
          setJobs((prev) =>
            prev.map((row) => {
              if (row.session_id !== j.session_id) return row;
              return {
                ...row,
                status: st.status || row.status,
                query: st.query || row.query,
                progress: st.progress ?? row.progress,
                activities: st.activities?.length ? st.activities : row.activities,
                started_at: st.started_at ?? row.started_at,
                completed_at: st.completed_at ?? (isDone ? Date.now() / 1000 : row.completed_at),
                done: isDone,
              };
            })
          );
        })
      );
    }, 2500);
    return () => {
      clearInterval(slow);
      clearInterval(fast);
      unsubRef.current.forEach((u) => u());
      unsubRef.current.clear();
    };
  }, [refreshLibrary, userId, token, conversationId]);

  useEffect(() => {
    if (!adoptSessionId) return;
    const q = (adoptQuery || "").trim() || t("research.adopt_default_query");
    rememberWatchedResearch(adoptSessionId, q, conversationId);
    setJobs((prev) => {
      if (prev.some((j) => j.session_id === adoptSessionId)) return prev;
      return [{ session_id: adoptSessionId, query: q, status: "running" }, ...prev];
    });
    attachStream(adoptSessionId);
    onAdoptHandled?.();
  }, [adoptSessionId, adoptQuery, attachStream, onAdoptHandled, conversationId, t]);

  const openReport = (id: string, authToken?: string | null) => {
    let url = reportUrl(id);
    if (authToken) {
      url += `?access_token=${encodeURIComponent(authToken)}`;
    }
    window.open(url, "_blank", "noopener,noreferrer");
  };

  void tick;

  const [view, setView] = useState<"main" | "library">("main");
  const [showInfo, setShowInfo] = useState(false);

  /* ============================================================ */
  /* LIBRARY VIEW (PAST RESEARCHES)                               */
  /* ============================================================ */
  if (view === "library") {
    return (
      <div className="relative flex h-full flex-col p-4 text-sm overflow-y-auto custom-scrollbar animate-in fade-in-0 duration-200">
        {/* Top Header with Back Button */}
        <div className="flex items-center justify-between pb-3 mb-3 border-b border-black/[0.06] dark:border-white/[0.08]">
          <button
            type="button"
            onClick={() => setView("main")}
            className="inline-flex items-center gap-1.5 rounded-full border border-black/[0.08] dark:border-white/[0.09] bg-card/80 px-3 py-1.5 text-xs font-semibold text-foreground shadow-2xs hover:bg-card hover:border-violet-500/40 transition-all active:scale-[0.98] cursor-pointer"
          >
            <ArrowLeft className="size-3.5 text-muted-foreground" />
            <span>Torna a Deep Research</span>
          </button>
          <span className="rounded-full bg-violet-500/15 text-violet-400 px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wider">
            {past.length} completate
          </span>
        </div>

        <div className="space-y-3">
          <div className="flex items-center justify-between px-1">
            <h3 className="text-xs font-bold uppercase tracking-wider text-muted-foreground flex items-center gap-1.5">
              <BookOpen size={14} className="text-violet-400" />
              <span>Ricerche Recenti</span>
            </h3>
          </div>

          {past.length === 0 ? (
            <div className="rounded-2xl border border-dashed border-border/70 bg-card/30 p-8 text-center text-xs text-muted-foreground">
              Nessuna ricerca precedente completata.
            </div>
          ) : (
            <ul className="space-y-2">
              {past.map((p) => (
                <li
                  key={p.id}
                  className="group flex items-start justify-between gap-2.5 rounded-2xl border border-black/[0.06] dark:border-white/[0.08] bg-card/40 dark:bg-card/25 p-3.5 transition-all hover:bg-card/80 hover:border-violet-500/30 shadow-2xs"
                >
                  <button
                    type="button"
                    className="min-w-0 flex-1 text-left text-xs hover:text-violet-400 transition-colors cursor-pointer"
                    onClick={() => openReport(p.id, token)}
                  >
                    <span className="line-clamp-2 font-semibold text-foreground group-hover:text-violet-400 transition-colors">
                      {p.query || p.id}
                    </span>
                    <span className="mt-1.5 flex items-center gap-2 text-[11px] text-muted-foreground">
                      <span className="rounded-full bg-muted/80 px-2 py-0.5 text-[10px] font-semibold">
                        {statusLabel(p.status || "done", t)}
                      </span>
                      {p.source_count != null ? (
                        <span>{t("research.sources", { count: p.source_count })}</span>
                      ) : null}
                      {p.duration != null && p.duration > 0 ? (
                        <span>· {Math.round(p.duration)}s</span>
                      ) : null}
                    </span>
                  </button>
                  <div className="flex items-center gap-1 shrink-0 pt-0.5">
                    <button
                      type="button"
                      className="focus-ring rounded-lg p-1.5 text-muted-foreground hover:bg-violet-500/10 hover:text-violet-400 transition-colors cursor-pointer"
                      onClick={() => openReport(p.id, token)}
                      title={t("research.open_report")}
                    >
                      <ExternalLink className="h-3.5 w-3.5" />
                    </button>
                    <button
                      type="button"
                      aria-label={t("btn.delete")}
                      className="focus-ring rounded-lg p-1.5 text-muted-foreground hover:bg-destructive/10 hover:text-destructive transition-colors opacity-0 group-hover:opacity-100 cursor-pointer"
                      onClick={() =>
                        void deleteResearch(p.id, userId, token).then(refreshLibrary)
                      }
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    );
  }

  /* ============================================================ */
  /* MAIN DEEP RESEARCH VIEW                                      */
  /* ============================================================ */
  return (
    <div className="relative flex h-full flex-col gap-4 p-4 text-sm overflow-y-auto custom-scrollbar animate-in fade-in-0 duration-200">
      {/* Active Research Activity & Step Timeline */}
      {jobs.length > 0 ? (
        <>
          {/* Header Hero Card */}
          <div className="relative overflow-hidden rounded-2xl border border-violet-500/20 bg-gradient-to-b from-violet-500/10 via-card/70 to-card/40 p-4 shadow-sm backdrop-blur-xl">
            <div className="flex items-start gap-3">
              <div className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-violet-600 to-indigo-600 text-white shadow-md shadow-violet-500/25">
                <Globe size={20} />
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <h3 className="font-semibold text-foreground text-sm">Deep Research</h3>
                    <span className="rounded-full bg-violet-500/15 text-violet-400 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide">
                      Multi-Round Web
                    </span>
                  </div>
                  <button
                    type="button"
                    onClick={() => setShowInfo((v) => !v)}
                    className="focus-ring rounded-full p-1 text-muted-foreground hover:bg-violet-500/15 hover:text-violet-400 transition-colors"
                    title="Informazioni su Deep Research"
                  >
                    <Lightbulb size={16} className={showInfo ? "text-violet-400" : "text-muted-foreground"} />
                  </button>
                </div>
                <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                  {t("research.description") ||
                    "Ricerca autonoma multi-round: analisi fonti, sintesi incrociata e generazione report strutturato."}
                </p>
              </div>
            </div>
          </div>

          {/* Quick Access to Library Button */}
          <button
            type="button"
            onClick={() => setView("library")}
            className="flex w-full items-center justify-between rounded-2xl border border-black/[0.06] dark:border-white/[0.08] bg-card/60 dark:bg-card/30 p-3 text-left transition-all duration-200 hover:-translate-y-0.5 hover:border-violet-500/40 hover:bg-card/90 hover:shadow-md cursor-pointer group"
          >
            <div className="flex items-center gap-2.5">
              <div className="flex size-7 shrink-0 items-center justify-center rounded-lg bg-violet-500/15 text-violet-400 group-hover:bg-violet-500 group-hover:text-white transition-colors">
                <BookOpen size={14} />
              </div>
              <span className="text-xs font-semibold text-foreground group-hover:text-violet-400 transition-colors">
                Ricerche Recenti
              </span>
            </div>
            <div className="flex items-center gap-1.5">
              {past.length > 0 && (
                <span className="rounded-full bg-violet-500/15 text-violet-400 px-2 py-0.5 text-[10px] font-bold">
                  {past.length}
                </span>
              )}
              <ChevronRight size={13} className="text-muted-foreground group-hover:text-violet-400 group-hover:translate-x-0.5 transition-all" />
            </div>
          </button>

          <section className="space-y-2.5">
            <div className="flex items-center justify-between px-1">
              <h3 className="text-[0.714em] font-bold uppercase tracking-wider text-muted-foreground">
                {t("research.activity")}
              </h3>
              <span className="flex items-center gap-1.5 text-[0.68em] text-violet-400 font-semibold">
                {jobs.filter((j) => (j.status === "running" || !j.status) && !j.done).length > 0 ? (
                  <>
                    <span className="h-1.5 w-1.5 rounded-full bg-violet-500 animate-pulse" />
                    <span>{jobs.filter((j) => (j.status === "running" || !j.status) && !j.done).length} in esecuzione</span>
                  </>
                ) : (
                  <span className="text-emerald-500 flex items-center gap-1">
                    <CheckCircle2 size={12} />
                    <span>Completata</span>
                  </span>
                )}
              </span>
            </div>
            <ul className="space-y-3">
              {jobs.map((j) => {
                const isDone = j.status === "done" || j.done;
                const isRunning = (j.status === "running" || !j.status) && !j.done;
                const pct = progressPercent(j);
                const activities = j.activities?.length
                  ? j.activities
                  : j.progress?.activities?.length
                    ? j.progress.activities
                    : [];
                const showActs = activities.slice(-15).reverse();

                return (
                  <li
                    key={j.session_id}
                    className="rounded-2xl border border-violet-500/25 bg-card/70 dark:bg-card/40 p-4 shadow-sm backdrop-blur-xl"
                  >
                    {/* Title & Status Badge */}
                    <div className="flex items-start justify-between gap-2.5">
                      <div className="min-w-0 flex-1">
                        <p className="font-semibold text-foreground text-xs sm:text-sm leading-snug">
                          {j.query || "Ricerca in corso..."}
                        </p>
                      </div>
                      <span
                        className={cn(
                          "shrink-0 rounded-full px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wide",
                          isDone
                            ? "bg-emerald-500/15 text-emerald-500 border border-emerald-500/20"
                            : j.status === "error"
                              ? "bg-destructive/15 text-destructive border border-destructive/20"
                              : "bg-violet-500/15 text-violet-300 border border-violet-500/20"
                        )}
                      >
                        {statusLabel(isDone ? "done" : j.status, t)}
                      </span>
                    </div>

                    {/* Summary Callout */}
                    <div className="mt-2.5 rounded-xl bg-violet-500/10 border border-violet-500/15 p-2 text-xs text-violet-300 font-medium">
                      {progressSummary(j, t)}
                    </div>

                    {/* Metrics Badges */}
                    <div className="mt-2.5 flex flex-wrap gap-1.5 text-[11px]">
                      {j.started_at ? (
                        <span className="rounded-lg bg-muted/60 px-2 py-0.5 text-muted-foreground font-mono">
                          ⏱ {formatElapsed(j.started_at, j.completed_at)}
                        </span>
                      ) : null}
                      {j.progress?.round != null ? (
                        <span className="rounded-lg bg-violet-500/15 px-2 py-0.5 text-violet-300 font-medium">
                          {t("research.round", { round: j.progress.round })}
                        </span>
                      ) : null}
                      {j.progress?.total_sources != null ? (
                        <span className="rounded-lg bg-muted/60 px-2 py-0.5 text-muted-foreground">
                          {t("research.sources", { count: j.progress.total_sources })}
                        </span>
                      ) : null}
                      {j.progress?.total_findings != null ? (
                        <span className="rounded-lg bg-muted/60 px-2 py-0.5 text-muted-foreground">
                          {t("research.findings", { count: j.progress.total_findings })}
                        </span>
                      ) : null}
                    </div>

                    {/* Progress Bar */}
                    {isRunning && (
                      <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-muted/70">
                        <div
                          className={cn(
                            "h-full bg-gradient-to-r from-violet-500 to-indigo-500 transition-all duration-500",
                            pct == null && "w-1/3 animate-pulse"
                          )}
                          style={pct != null ? { width: `${pct}%` } : undefined}
                        />
                      </div>
                    )}

                    {/* Visual Step Timeline */}
                    {showActs.length > 0 && (
                      <div className="mt-3.5 space-y-2 border-t border-border/40 pt-3">
                        <span className="text-[0.68em] font-bold uppercase tracking-wider text-muted-foreground">
                          Avanzamento fasi
                        </span>
                        <ol className="max-h-52 space-y-2 overflow-y-auto custom-scrollbar pr-1">
                          {showActs.map((act, idx) => {
                            const label = act.label || act.message || act.phase || "…";
                            const isLatest = idx === 0 && isRunning;
                            return (
                              <li
                                key={`${act.ts ?? idx}-${label.slice(0, 40)}`}
                                className={cn(
                                   "flex items-start gap-2.5 rounded-xl p-2 text-xs leading-snug transition-colors",
                                  isLatest
                                    ? "bg-violet-500/10 border border-violet-500/20 text-foreground font-medium"
                                    : "text-muted-foreground hover:bg-muted/30"
                                )}
                              >
                                <div className="mt-0.5">{activityIcon(act, isLatest, isRunning)}</div>
                                <div className="min-w-0 flex-1">
                                  <span className="block break-words">{label}</span>
                                  {act.ts ? (
                                    <span className="text-[10px] opacity-60 font-mono mt-0.5 block">
                                      {formatTime(act.ts)}
                                    </span>
                                  ) : null}
                                </div>
                              </li>
                            );
                          })}
                        </ol>
                      </div>
                    )}

                    {/* Bottom Action Buttons */}
                    <div className="mt-3.5 flex items-center justify-between border-t border-border/40 pt-2.5">
                      {isDone && (
                        <button
                          type="button"
                          className="focus-ring inline-flex items-center gap-1.5 rounded-xl bg-gradient-to-r from-violet-600 to-indigo-600 px-3 py-1.5 text-xs font-semibold text-white shadow-sm shadow-violet-500/25 transition-all hover:scale-[1.02] active:scale-[0.98] cursor-pointer"
                          onClick={() => openReport(j.session_id, token)}
                        >
                          <ExternalLink className="h-3.5 w-3.5" />
                          {t("research.open_report")}
                        </button>
                      )}
                      {isRunning && (
                        <button
                          type="button"
                          className="focus-ring ml-auto rounded-xl border border-red-500/30 bg-red-500/15 px-3 py-1 text-xs font-semibold text-red-600 dark:text-red-400 hover:bg-red-500/25 hover:text-red-700 dark:hover:text-red-300 transition-colors cursor-pointer"
                          onClick={() =>
                            void cancelResearch(j.session_id, userId, token).then(
                              refreshLibrary
                            )
                          }
                        >
                          {t("btn.cancel")}
                        </button>
                      )}
                    </div>
                  </li>
                );
              })}
            </ul>
          </section>
        </>
      ) : (
        /* Empty / Idle State: Centered Hero Section */
        <div className="flex flex-col items-center text-center my-auto py-4">
          <div className="relative mb-3 flex size-14 items-center justify-center rounded-2xl bg-gradient-to-br from-violet-600 to-indigo-600 text-white shadow-lg shadow-violet-500/25 ring-4 ring-violet-500/10">
            <Globe size={28} />
          </div>

          <div className="flex items-center gap-2">
            <h3 className="text-base font-bold text-foreground">Deep Research</h3>
            <span className="rounded-full border border-violet-500/30 bg-violet-500/15 px-2.5 py-0.5 text-[10.5px] font-bold uppercase tracking-wider text-violet-600 dark:text-violet-400">
              Multi-Round Web
            </span>
            <button
              type="button"
              onClick={() => setShowInfo((v) => !v)}
              className="focus-ring rounded-full p-1 text-muted-foreground hover:bg-violet-500/15 hover:text-violet-400 transition-colors"
              title="Informazioni su Deep Research"
              aria-label="Informazioni su Deep Research"
            >
              <Lightbulb size={16} className={showInfo ? "text-violet-400" : "text-muted-foreground"} />
            </button>
          </div>

          <p className="mt-2 text-sm leading-relaxed text-muted-foreground max-w-sm">
            {t("research.description") ||
              "Ricerca autonoma multi-round: analisi di decine di fonti web, sintesi incrociata e generazione di report strutturati."}
          </p>

          {/* Library Button */}
          <div className="mt-4 w-full">
            <button
              type="button"
              onClick={() => setView("library")}
              className="flex w-full items-center justify-between rounded-2xl border border-black/[0.06] dark:border-white/[0.08] bg-card/60 dark:bg-card/30 p-3 text-left transition-all duration-200 hover:-translate-y-0.5 hover:border-violet-500/40 hover:bg-card/90 hover:shadow-md cursor-pointer group"
            >
              <div className="flex items-center gap-2.5">
                <div className="flex size-8 shrink-0 items-center justify-center rounded-xl bg-violet-500/15 text-violet-400 group-hover:bg-violet-500 group-hover:text-white transition-colors">
                  <BookOpen size={16} />
                </div>
                <div>
                  <span className="text-xs font-semibold text-foreground group-hover:text-violet-400 transition-colors block">
                    Ricerche Recenti
                  </span>
                  <span className="text-[11px] text-muted-foreground">
                    {past.length > 0 ? `${past.length} ricerche completate` : "Archivio report e cronologia"}
                  </span>
                </div>
              </div>
              <div className="flex items-center gap-1.5">
                {past.length > 0 && (
                  <span className="rounded-full bg-violet-500/15 text-violet-400 px-2 py-0.5 text-[10.5px] font-bold">
                    {past.length}
                  </span>
                )}
                <ChevronRight size={14} className="text-muted-foreground group-hover:text-violet-400 group-hover:translate-x-0.5 transition-all" />
              </div>
            </button>
          </div>

          {/* Suggestion Cards */}
          <div className="mt-5 w-full space-y-2 text-left">
            <div className="flex items-center justify-between px-1">
              <span className="text-[0.75em] font-bold uppercase tracking-wider text-muted-foreground/80">
                Idee per ricerche approfondite
              </span>
            </div>

            <div className="grid grid-cols-1 gap-2">
              {[
                {
                  title: "Analisi di Mercato & Trend AI 2026",
                  desc: "Panoramica completa su modelli, agenti autonomi e metriche di settore.",
                  prompt:
                    "Esegui una Deep Research sui trend emergenti nell'AI, architetture agentiche e benchmark del 2026.",
                },
                {
                  title: "Confronto Tecnico & Benchmark",
                  desc: "Analisi comparata tra soluzioni concorrenti, pro, contro e scenari d'uso.",
                  prompt:
                    "Esegui una ricerca approfondita confrontando le principali soluzioni open-source per il Model Context Protocol.",
                },
                {
                  title: "Guida Operativa & Best Practice",
                  desc: "Studio e linee guida di implementazione enterprise per sicurezza e privacy.",
                  prompt:
                    "Analizza a fondo le migliori pratiche di sicurezza e governance per agenti AI in ambito aziendale.",
                },
              ].map((item, idx) => (
                <button
                  key={idx}
                  type="button"
                  onClick={() => onPromptSuggestion?.(item.prompt)}
                  className="group relative flex flex-col rounded-2xl border border-black/[0.06] dark:border-white/[0.08] bg-card/60 dark:bg-card/30 p-3.5 text-left transition-all duration-200 hover:-translate-y-0.5 hover:border-violet-500/40 hover:bg-card/90 hover:shadow-md cursor-pointer"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-xs font-semibold text-foreground group-hover:text-violet-400 transition-colors flex items-center gap-1.5">
                      <Plus
                        size={14}
                        className="text-violet-400 opacity-70 group-hover:opacity-100 transition-opacity"
                      />
                      {item.title}
                    </span>
                    <ArrowRight size={13} className="text-muted-foreground opacity-0 group-hover:opacity-100 group-hover:translate-x-0.5 transition-all text-violet-400" />
                  </div>
                  <p className="mt-1 text-[0.78em] leading-relaxed text-muted-foreground">
                    {item.desc}
                  </p>
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Info Popover / Modal overlay */}
      {showInfo && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-xs animate-in fade-in duration-150">
          <div className="w-full max-w-sm rounded-2xl border border-violet-500/30 bg-background/95 p-5 shadow-2xl backdrop-blur-xl animate-in zoom-in-95 duration-150">
            <div className="flex items-center justify-between border-b border-border/50 pb-3">
              <div className="flex items-center gap-2">
                <div className="flex size-7 items-center justify-center rounded-lg bg-violet-500/15 text-violet-400">
                  <Globe size={16} />
                </div>
                <h4 className="text-sm font-bold text-foreground">Come avviare Deep Research</h4>
              </div>
              <button
                type="button"
                onClick={() => setShowInfo(false)}
                className="focus-ring rounded-lg p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
              >
                <Plus size={16} className="rotate-45" />
              </button>
            </div>

            <div className="mt-3.5 space-y-3 text-xs leading-relaxed text-muted-foreground">
              <div className="flex items-start gap-2.5">
                <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-violet-500/15 text-violet-600 dark:text-violet-400 font-bold text-[11px]">1</span>
                <p>
                  Seleziona la modalità <strong className="text-foreground">Deep Research</strong> dal selettore agente nella barra di scrittura in basso.
                </p>
              </div>
              <div className="flex items-start gap-2.5">
                <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-violet-500/15 text-violet-600 dark:text-violet-400 font-bold text-[11px]">2</span>
                <div>
                  <p>Oppure chiedi direttamente in chat:</p>
                  <span className="mt-1 block rounded-lg border border-violet-500/20 bg-violet-500/5 p-2 font-mono text-[11px] text-foreground">
                    «Esegui una ricerca approfondita su [argomento]»
                  </span>
                </div>
              </div>
              <div className="flex items-start gap-2.5">
                <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-violet-500/15 text-violet-600 dark:text-violet-400 font-bold text-[11px]">3</span>
                <p>
                  L&apos;agente esplorerà il web in più cicli, raccoglierà fonti verificate e compilerà un report finale visualizzabile in questo pannello.
                </p>
              </div>
            </div>

            <div className="mt-4 pt-3 border-t border-border/50 text-right">
              <button
                type="button"
                onClick={() => setShowInfo(false)}
                className="rounded-xl bg-violet-600 px-4 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-violet-700 transition-colors cursor-pointer"
              >
                Ho capito
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
