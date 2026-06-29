"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { CheckCircle2, Circle, ExternalLink, Loader2, Search, Trash2, XCircle } from "lucide-react";
import {
  cancelResearch,
  deleteResearch,
  fetchActiveResearch,
  fetchResearchLibrary,
  fetchResearchStatus,
  loadWatchedResearch,
  rememberWatchedResearch,
  reportUrl,
  startResearch,
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

function formatElapsed(startedAt?: number): string {
  if (!startedAt) return "";
  const sec = Math.max(0, Math.floor(Date.now() / 1000 - startedAt));
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

function activityIcon(act: ResearchActivity, isLatest: boolean) {
  if (act.phase === "error") return <XCircle className="h-3 w-3 shrink-0 text-destructive" />;
  if (act.phase === "warning") return <Circle className="h-3 w-3 shrink-0 text-amber-400" />;
  if (isLatest) return <Loader2 className="h-3 w-3 shrink-0 animate-spin text-violet-400" />;
  return <CheckCircle2 className="h-3 w-3 shrink-0 text-emerald-500/80" />;
}

function progressSummary(j: JobState, t: ReturnType<typeof useT>): string {
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
  if (j.status === "done") return t("research.phase.done_summary");
  if (j.status === "error") return t("research.phase.error_summary");
  if (j.status === "running") return t("research.phase.running_summary");
  return t("research.phase.starting");
}

function progressPercent(j: JobState): number | null {
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
}: {
  userId: string;
  token?: string | null;
  conversationId: string;
  adoptSessionId?: string | null;
  adoptQuery?: string | null;
  onAdoptHandled?: () => void;
}) {
  const t = useT();
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("");
  const [jobs, setJobs] = useState<JobState[]>([]);
  const [past, setPast] = useState<ResearchLibraryItem[]>([]);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const unsubRef = useRef<Map<string, () => void>>(new Map());
  const refreshRef = useRef<() => void>(() => {});

  useEffect(() => {
    const t = setInterval(() => setTick((n) => n + 1), 1000);
    return () => clearInterval(t);
  }, []);

  const jobsRef = useRef<JobState[]>([]);
  useEffect(() => {
    jobsRef.current = jobs;
  }, [jobs]);

  const refreshLibrary = useCallback(async () => {
    researchLog("refreshLibrary", { userId, conversationId });
    const [active, lib] = await Promise.all([
      fetchActiveResearch(userId, token, conversationId),
      fetchResearchLibrary(userId, token, { limit: 40, chatSessionId: conversationId }),
    ]);
    const libIds = new Set(lib.map((x) => x.id));

    const watched = loadWatchedResearch(conversationId).slice(0, 10);
    const reconcileIds = new Set<string>([
      ...active.map((a) => a.session_id),
      ...watched.map((w) => w.id),
      ...jobsRef.current
        .filter((j) => j.status === "running" || j.done || j.status === "done")
        .map((j) => j.session_id),
    ]);

    const statusById = new Map<string, Awaited<ReturnType<typeof fetchResearchStatus>>>();
    await Promise.all(
      [...reconcileIds].map(async (id) => {
        const st = await fetchResearchStatus(id, userId, token);
        if (st) statusById.set(id, st);
      })
    );

    setJobs((prev) => {
      const byId = new Map<string, JobState>();

      for (const w of watched) {
        const st = statusById.get(w.id);
        if (!st) continue;
        byId.set(w.id, {
          session_id: w.id,
          query: st.query || w.query,
          status: st.status || "running",
          progress: st.progress,
          activities: st.activities,
          started_at: st.started_at,
          done: st.status !== "running",
        });
      }

      for (const j of prev) {
        const st = statusById.get(j.session_id);
        const reconciled = st
          ? {
              ...j,
              status: st.status || j.status,
              query: st.query || j.query,
              progress:
                j.progress?.ts && st.progress?.ts && j.progress.ts > st.progress.ts
                  ? j.progress
                  : st.progress ?? j.progress,
              activities: st.activities?.length ? st.activities : j.activities,
              done: st.status !== "running" ? true : j.done,
            }
          : j;
        const keepLocal =
          reconciled.status === "running" ||
          reconciled.done ||
          reconciled.status === "done" ||
          reconciled.status === "error" ||
          reconciled.status === "interrupted";
        if (keepLocal && !(reconciled.status !== "running" && libIds.has(reconciled.session_id))) {
          byId.set(reconciled.session_id, reconciled);
        }
      }

      for (const a of active) {
        const cur = byId.get(a.session_id);
        const acts =
          (a.activities?.length || 0) >= (cur?.activities?.length || 0)
            ? a.activities
            : cur?.activities ?? a.activities;
        byId.set(a.session_id, {
          ...a,
          progress:
            cur?.progress?.ts && (!a.progress?.ts || cur.progress.ts > a.progress.ts)
              ? cur.progress
              : a.progress ?? cur?.progress,
          activities: acts,
          done: cur?.done,
        });
      }

      const merged = Array.from(byId.values()).sort(
        (a, b) => (b.started_at ?? 0) - (a.started_at ?? 0)
      );
      researchLog("jobs merged", {
        activeFromApi: active.length,
        watched: watched.length,
        library: lib.length,
        merged: merged.length,
        ids: merged.map((j) => `${j.session_id}:${j.status}`),
      });
      return merged;
    });

    for (const a of active) {
      attachStreamRef.current(a.session_id);
    }
    for (const w of watched) {
      const st = statusById.get(w.id);
      if (st?.status === "running") {
        attachStreamRef.current(w.id);
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
    researchLog("library loaded", { past: lib.length });
  }, [userId, token, conversationId]);

  refreshRef.current = () => {
    void refreshLibrary();
  };

  const attachStreamRef = useRef<(sessionId: string) => void>(() => {});

  const attachStream = useCallback(
    (sessionId: string) => {
      if (unsubRef.current.has(sessionId)) {
        researchLog("stream already attached", { sessionId });
        return;
      }
      researchLog("attach stream", { sessionId });
      const unsub = subscribeResearchStream(
        sessionId,
        userId,
        token,
        (ev) => {
          setJobs((prev) => {
            const idx = prev.findIndex((j) => j.session_id === sessionId);
            const patch = (j: JobState): JobState => {
              const mergedActs =
                (ev.activities?.length || 0) >= (j.activities?.length || 0)
                  ? ev.activities
                  : j.activities;
              return {
                ...j,
                progress: ev,
                activities: mergedActs ?? j.activities,
                status: ev.final ? ev.status || j.status : ev.status || j.status,
                done: ev.final ? true : j.done,
              };
            };
            if (idx === -1) {
              return [
                {
                  session_id: sessionId,
                  query: "",
                  status: ev.status || "running",
                  progress: ev,
                  activities: ev.activities,
                  done: Boolean(ev.final),
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
    [userId, token]
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

    researchLog("panel mount", { userId, conversationId, adoptSessionId, adoptQuery });
    void refreshLibrary();
    const slow = setInterval(() => void refreshLibrary(), 8000);
    const fast = setInterval(() => {
      const running = jobsRef.current.filter((j) => j.status === "running" && !j.done);
      if (!running.length) return;
      void Promise.all(
        running.map(async (j) => {
          const st = await fetchResearchStatus(j.session_id, userId, token);
          if (!st) return;
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
                done: st.status !== "running",
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
    researchLog("adopt session", { sessionId: adoptSessionId, query: q });
    rememberWatchedResearch(adoptSessionId, q, conversationId);
    setJobs((prev) => {
      if (prev.some((j) => j.session_id === adoptSessionId)) return prev;
      return [{ session_id: adoptSessionId, query: q, status: "running" }, ...prev];
    });
    attachStream(adoptSessionId);
    onAdoptHandled?.();
  }, [adoptSessionId, adoptQuery, attachStream, onAdoptHandled, conversationId]);

  const handleStart = async () => {
    const q = query.trim();
    if (!q) return;
    setStarting(true);
    setError(null);
    try {
      const res = await startResearch(
        userId,
        { query: q, category: category || undefined, chat_session_id: conversationId },
        token
      );
      rememberWatchedResearch(res.session_id, res.query, conversationId);
      setQuery("");
      setJobs((prev) => [
        { session_id: res.session_id, query: res.query, status: "running", started_at: Date.now() / 1000 },
        ...prev.filter((j) => j.session_id !== res.session_id),
      ]);
      attachStream(res.session_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setStarting(false);
    }
  };

  const openReport = (id: string, authToken?: string | null) => {
    let url = reportUrl(id);
    if (authToken) {
      url += `?access_token=${encodeURIComponent(authToken)}`;
    }
    window.open(url, "_blank", "noopener,noreferrer");
  };

  void tick;

  return (
    <div className="flex h-full flex-col gap-4 p-4 text-sm">
      <div className="space-y-2 rounded-lg border border-violet-500/30 bg-violet-500/5 p-3">
        <label className="text-xs font-medium text-violet-300">{t("research.deep_research")}</label>
        <p className="text-[11px] leading-relaxed text-muted-foreground">
          {t("research.description")}
        </p>
        <textarea
          className="focus-ring min-h-[72px] w-full resize-y rounded-md border border-border bg-background px-3 py-2 text-sm"
          placeholder={t("research.placeholder")}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <div className="flex flex-wrap gap-1">
          {["", "product", "comparison", "howto", "factcheck"].map((c) => (
            <button
              key={c || "auto"}
              type="button"
              className={cn(
                "rounded-full px-2 py-0.5 text-xs border",
                category === c
                  ? "border-violet-400 bg-violet-500/10 dark:bg-violet-500/20 text-violet-700 dark:text-violet-200"
                  : "border-border text-muted-foreground"
              )}
              onClick={() => setCategory(c)}
            >
              {t(`research.category.${c || "auto"}`)}
            </button>
          ))}
        </div>
        <button
          type="button"
          disabled={starting || !query.trim()}
          className="focus-ring inline-flex items-center gap-2 rounded-md bg-violet-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-violet-500 disabled:opacity-50"
          onClick={() => void handleStart()}
        >
          {starting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Search className="h-3.5 w-3.5" />}
          {t("research.start")}
        </button>
        {error && <p className="text-xs text-destructive">{error}</p>}
      </div>

      {jobs.length > 0 ? (
        <section>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            {t("research.activity")}
          </h3>
          <ul className="space-y-3">
            {jobs.map((j) => {
              const pct = progressPercent(j);
              const activities = j.activities?.length
                ? j.activities
                : j.progress?.activities?.length
                  ? j.progress.activities
                  : [];
              const showActs = activities.slice(-12).reverse();
              return (
                <li key={j.session_id} className="rounded-lg border border-violet-500/20 bg-card/60 p-3">
                  <div className="flex items-start justify-between gap-2">
                    <p className="font-medium line-clamp-3 text-[13px] leading-snug">{j.query}</p>
                    <span className="shrink-0 rounded-full bg-violet-500/15 px-2 py-0.5 text-[10px] text-violet-300">
                      {statusLabel(j.status, t)}
                    </span>
                  </div>
                  <p className="mt-1.5 text-xs text-violet-200/90">{progressSummary(j, t)}</p>
                  <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[10px] text-muted-foreground">
                    {j.started_at ? <span>⏱ {formatElapsed(j.started_at)}</span> : null}
                    {j.progress?.round != null ? (
                      <span>{t("research.round", { round: j.progress.round })}</span>
                    ) : null}
                    {j.progress?.total_sources != null ? (
                      <span>{t("research.sources", { count: j.progress.total_sources })}</span>
                    ) : null}
                    {j.progress?.total_findings != null ? (
                      <span>{t("research.findings", { count: j.progress.total_findings })}</span>
                    ) : null}
                  </div>
                  {j.status === "running" && (
                    <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-muted">
                      <div
                        className={cn(
                          "h-full bg-violet-500 transition-all duration-500",
                          pct == null && "w-1/3 animate-pulse"
                        )}
                        style={pct != null ? { width: `${pct}%` } : undefined}
                      />
                    </div>
                  )}
                  {showActs.length > 0 && (
                    <ol className="mt-3 max-h-44 space-y-1.5 overflow-y-auto border-t border-border/50 pt-2">
                      {showActs.map((act, idx) => {
                        const label = act.label || act.message || act.phase || "…";
                        const isLatest = idx === 0 && j.status === "running";
                        return (
                          <li
                            key={`${act.ts ?? idx}-${label.slice(0, 40)}`}
                            className={cn(
                              "flex gap-2 text-[11px] leading-snug",
                              isLatest ? "text-foreground" : "text-muted-foreground"
                            )}
                          >
                            {activityIcon(act, isLatest)}
                            <span className="min-w-0 flex-1">
                              <span className="block">{label}</span>
                              {act.ts ? (
                                <span className="text-[10px] opacity-60">{formatTime(act.ts)}</span>
                              ) : null}
                            </span>
                          </li>
                        );
                      })}
                    </ol>
                  )}
                  <div className="mt-2 flex gap-2">
                    {(j.status === "done" || j.done) && (
                      <button
                        type="button"
                        className="focus-ring inline-flex items-center gap-1 text-xs text-violet-300 hover:underline"
                        onClick={() => openReport(j.session_id, token)}
                      >
                        <ExternalLink className="h-3 w-3" /> {t("research.open_report")}
                      </button>
                    )}
                    {j.status === "running" && (
                      <button
                        type="button"
                        className="text-xs text-muted-foreground hover:text-foreground"
                        onClick={() => void cancelResearch(j.session_id, userId, token).then(refreshLibrary)}
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
      ) : (
        <p className="rounded-lg border border-dashed border-border/60 p-3 text-[11px] text-muted-foreground">
          {t("research.empty_panel_p1")}{" "}
          <code className="text-violet-300">AION Research</code>{" "}
          {t("research.empty_panel_p2")}
        </p>
      )}

      {past.length > 0 && (
        <section>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            {t("research.library")}
          </h3>
          <ul className="space-y-2">
            {past.map((p) => (
              <li
                key={p.id}
                className="flex items-start justify-between gap-2 rounded-lg border border-border/60 p-2"
              >
                <button
                  type="button"
                  className="min-w-0 flex-1 text-left text-xs hover:text-violet-300"
                  onClick={() => openReport(p.id, token)}
                >
                  <span className="line-clamp-2 block">{p.query || p.id}</span>
                  <span className="mt-0.5 block text-[10px] text-muted-foreground">
                    {statusLabel(p.status || "done", t)}
                    {p.source_count != null ? ` · ${t("research.sources", { count: p.source_count })}` : ""}
                    {p.duration != null && p.duration > 0
                      ? ` · ${Math.round(p.duration)}s`
                      : ""}
                  </span>
                </button>
                <button
                  type="button"
                  aria-label={t("btn.delete")}
                  className="shrink-0 text-muted-foreground hover:text-destructive"
                  onClick={() => void deleteResearch(p.id, userId, token).then(refreshLibrary)}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
