"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertTriangle, ExternalLink, History, Loader2, Pencil, Play, RefreshCw, Trash2 } from "lucide-react";
import { apiBase } from "@/lib/api";
import { apiFetch } from "@/lib/api/headers";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";
import { chatUrl } from "@/lib/paths";
import { getLocale } from "@/lib/i18n/i18n-store";
import { PageToast, ToastState } from "@/components/PageToast";
import { Dialog } from "@/components/profiles/Dialog";
import { DeleteDialog } from "@/components/ui/ConfirmDialogs";
import { Select } from "@/components/ui/Select";
import { SearchField } from "@/components/ui/SearchField";
import { ghostBtn, inputCls, outlineBtn, solidBtn } from "@/components/ui/classes";
import { fullWhen, shortWhen, toMs } from "@/components/conversations/format";
import { Transcript } from "@/components/conversations/Transcript";
import type { ThreadMessage } from "@/components/conversations/types";

const k = "admin_schedules";
const ALL = "__all";
const GRID = "md:grid-cols-[minmax(0,2fr)_minmax(0,1.1fr)_minmax(0,1fr)_minmax(0,1.1fr)_7.5rem_10.5rem]";

type CronJob = {
  job_id: string;
  user_id: string;
  name: string;
  cron_expression: string;
  timezone: string;
  profile_slug: string;
  prompt: string;
  session_mode: string;
  session_id?: string | null;
  enabled: boolean;
  next_run_at?: string | null;
  last_run?: { status?: string; started_at?: string } | null;
  sql_query_project?: string | null;
};

type CronRun = {
  run_id: string;
  status: string;
  started_at?: string;
  finished_at?: string;
  error_message?: string;
  assistant_preview?: string;
  conversation_id?: string | null;
};

type Option = { value: string; label: string };
type Tone = "ok" | "bad" | "live" | "idle";
type StatusFilter = "all" | "on" | "off";

const toneOf = (status?: string): Tone => {
  const s = (status || "").toLowerCase();
  if (/succ|ok|done|complete/.test(s)) return "ok";
  if (/fail|err|timeout/.test(s)) return "bad";
  if (/run|pend|start|queue/.test(s)) return "live";
  return "idle";
};

const TONE: Record<Tone, string> = {
  ok: "bg-success/12 text-success",
  bad: "bg-destructive/12 text-destructive",
  live: "bg-warning/15 text-warning",
  idle: "bg-secondary text-muted-foreground",
};

function StatusPill({ status, t }: { status?: string; t: (k: string) => string }) {
  if (!status) return <span className="text-muted-foreground">—</span>;
  const tone = toneOf(status);
  const known = tone === "ok" ? "success" : tone === "bad" ? "error" : tone === "live" ? "running" : null;
  return (
    <span className={cn("inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium", TONE[tone])}>
      <span className={cn("h-1.5 w-1.5 rounded-full bg-current", tone === "live" && "animate-pulse")} aria-hidden />
      {known ? t(`${k}.status.${known}`) : status}
    </span>
  );
}

/** Upcoming time: "in 12 min" within a day, otherwise a full date. */
function nextWhen(iso: string, now: number): string {
  const ms = toMs(iso);
  const diff = ms - now;
  if (diff > 0 && diff < 24 * 3600_000) {
    const rtf = new Intl.RelativeTimeFormat(getLocale(), { numeric: "auto", style: "short" });
    if (diff < 3600_000) return rtf.format(Math.max(1, Math.round(diff / 60_000)), "minute");
    return rtf.format(Math.round(diff / 3600_000), "hour");
  }
  return fullWhen(ms);
}

function Switch({ checked, onChange, label, disabled }: { checked: boolean; onChange: (v: boolean) => void; label: string; disabled?: boolean }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cn(
        "focus-ring relative inline-flex h-6 w-10 shrink-0 items-center rounded-full border transition-colors disabled:cursor-not-allowed disabled:opacity-50",
        checked ? "border-success/40 bg-success" : "border-border bg-secondary",
      )}
    >
      <span className={cn("inline-block h-4 w-4 rounded-full bg-background shadow-sm transition-transform duration-200 ease-out", checked ? "translate-x-5" : "translate-x-1")} />
    </button>
  );
}

const iconBtn =
  "focus-ring inline-flex h-8 w-8 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-background hover:text-foreground disabled:opacity-50";

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-sm font-medium">{label}</span>
      {children}
      {hint && <span className="text-xs text-muted-foreground">{hint}</span>}
    </label>
  );
}

const duration = (r: CronRun) => {
  const a = toMs(r.started_at);
  const b = toMs(r.finished_at);
  if (!a || !b || b < a) return "";
  const sec = Math.round((b - a) / 1000);
  if (sec < 60) return `${sec}s`;
  const m = Math.floor(sec / 60);
  return m < 60 ? `${m}m ${sec % 60}s` : `${Math.floor(m / 60)}h ${m % 60}m`;
};

function RunDetail({ run, t }: { run: CronRun; t: (k: string, v?: Record<string, string | number>) => string }) {
  const convId = run.conversation_id || null;
  const [thread, setThread] = useState<{ id: string; state: "ready" | "error"; messages: ThreadMessage[] } | null>(null);
  const [showTools, setShowTools] = useState(false);

  useEffect(() => {
    if (!convId) return;
    let live = true;
    apiFetch(`${apiBase()}/admin/conversations/${encodeURIComponent(convId)}/messages?include_internal=true`)
      .then((res) => (res.ok ? res.json() : Promise.reject(res)))
      .then((data) => live && setThread({ id: convId, state: "ready", messages: data.messages || [] }))
      .catch(() => live && setThread({ id: convId, state: "error", messages: [] }));
    return () => {
      live = false;
    };
  }, [convId]);

  const loaded = thread && thread.id === convId ? thread : null;
  const toolCount = loaded?.messages.filter((m) => m.tool_name).length ?? 0;
  const href = convId ? chatUrl(`/c/${encodeURIComponent(convId)}`) : null;
  const chip = "focus-ring inline-flex h-8 items-center gap-1.5 rounded-lg border px-2.5 text-xs font-medium transition-colors";

  return (
    <section className="flex min-h-0 flex-col overflow-hidden rounded-2xl border border-border/70 bg-background" aria-label={t(`${k}.runs.detail_aria`)}>
      <header className="flex flex-col gap-3 border-b border-border/60 px-5 py-4">
        <div className="flex flex-wrap items-center gap-3">
          <StatusPill status={run.status} t={t} />
          <div className="ml-auto flex items-center gap-2">
            {toolCount > 0 && (
              <button type="button" aria-pressed={showTools} onClick={() => setShowTools((v) => !v)} className={cn(chip, showTools ? "border-foreground/30 bg-secondary" : "border-border hover:bg-secondary")}>
                {t("admin_conversations.detail.show_tools")}
                <span className="tabular-nums text-muted-foreground">{toolCount}</span>
              </button>
            )}
            {href ? (
              <a href={href} target="_blank" rel="noopener" className="focus-ring inline-flex h-9 items-center gap-2 rounded-xl bg-foreground px-3.5 text-sm font-semibold text-background transition-opacity hover:opacity-90">
                <ExternalLink className="h-3.5 w-3.5" aria-hidden />
                {t(`${k}.runs.open_chat`)}
              </a>
            ) : (
              <span className="text-xs text-muted-foreground">{t(`${k}.runs.no_chat`)}</span>
            )}
          </div>
        </div>
        <dl className="flex flex-wrap gap-x-8 gap-y-2 text-sm">
          {[
            [t(`${k}.runs.started`), run.started_at ? fullWhen(toMs(run.started_at)) : "—"],
            [t(`${k}.runs.finished`), run.finished_at ? fullWhen(toMs(run.finished_at)) : "—"],
            [t(`${k}.runs.duration`), duration(run) || "—"],
          ].map(([label, value]) => (
            <div key={label} className="min-w-0">
              <dt className="text-xs text-muted-foreground">{label}</dt>
              <dd className="mt-0.5 tabular-nums">{value}</dd>
            </div>
          ))}
        </dl>
        {run.error_message && <p className="whitespace-pre-wrap break-words rounded-xl bg-destructive/10 px-3.5 py-3 text-sm text-destructive">{run.error_message}</p>}
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto px-3 py-6 sm:px-6" aria-busy={!!convId && !loaded}>
        {!convId ? (
          run.assistant_preview ? (
            <p className="mx-auto max-w-3xl whitespace-pre-wrap break-words text-sm leading-relaxed">{run.assistant_preview}</p>
          ) : (
            <p className="py-16 text-center text-sm text-muted-foreground">{t(`${k}.runs.no_output`)}</p>
          )
        ) : !loaded ? (
          <div className="flex items-center justify-center gap-2 py-16 text-sm text-muted-foreground" role="status">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
            {t("admin_conversations.detail.loading")}
          </div>
        ) : loaded.state === "error" ? (
          <p className="py-16 text-center text-sm text-destructive">{t("admin_conversations.detail.load_error")}</p>
        ) : loaded.messages.length === 0 ? (
          <p className="py-16 text-center text-sm text-muted-foreground">{t("admin_conversations.detail.no_messages")}</p>
        ) : (
          <Transcript messages={loaded.messages} convId={loaded.id} highlightId={null} showTools={showTools} t={t} />
        )}
      </div>
    </section>
  );
}

function RunsDialog({ job, runs, loading, now, t, onClose }: { job: CronJob; runs: CronRun[]; loading: boolean; now: number; t: (k: string, v?: Record<string, string | number>) => string; onClose: () => void }) {
  const [pick, setPick] = useState<string | null>(null);
  const current = runs.find((r) => r.run_id === pick) ?? runs[0] ?? null;
  const ok = runs.filter((r) => toneOf(r.status) === "ok").length;
  const bad = runs.filter((r) => toneOf(r.status) === "bad").length;

  return (
    <Dialog title={t(`${k}.runs.title`, { name: job.name })} closeLabel={t(`${k}.runs.close`)} onClose={onClose} className="max-w-6xl">
      <div className="flex flex-col gap-4">
        <p className="-mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted-foreground">
          <code className="font-mono tabular-nums text-foreground/80">{job.cron_expression}</code>
          <span>{job.timezone}</span>
          {!loading && runs.length > 0 && <span className="tabular-nums">{t(`${k}.runs.summary`, { n: runs.length, ok, bad })}</span>}
        </p>

        {loading ? (
          <div className="flex items-center gap-2 py-10 text-sm text-muted-foreground" role="status">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
            {t(`${k}.runs.loading`)}
          </div>
        ) : runs.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-border px-6 py-14 text-center">
            <p className="text-sm font-medium">{t(`${k}.runs.empty`)}</p>
            <p className="mx-auto mt-1 max-w-[42ch] text-sm text-muted-foreground">{t(`${k}.runs.empty_body`)}</p>
          </div>
        ) : (
          <div className="grid min-h-0 gap-4 md:h-[min(42rem,72vh)] md:grid-cols-[minmax(0,15rem)_minmax(0,1fr)]">
            <ul className="flex max-h-60 flex-col gap-0.5 overflow-y-auto rounded-2xl border border-border/70 bg-background p-1.5 md:max-h-none" aria-label={t(`${k}.runs.list_aria`)}>
              {runs.map((r) => {
                const active = r.run_id === current?.run_id;
                const ms = toMs(r.started_at);
                return (
                  <li key={r.run_id}>
                    <button
                      type="button"
                      aria-current={active ? "true" : undefined}
                      onClick={() => setPick(r.run_id)}
                      className={cn("focus-ring flex w-full flex-col items-start gap-1 rounded-xl px-3 py-2 text-left transition-colors", active ? "bg-secondary" : "hover:bg-secondary/60")}
                    >
                      <StatusPill status={r.status} t={t} />
                      <span className="flex w-full items-center justify-between gap-2 text-xs tabular-nums text-muted-foreground">
                        <span title={fullWhen(ms)}>{ms ? shortWhen(ms, now) : ""}</span>
                        <span>{duration(r)}</span>
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>

            {current && <RunDetail key={current.run_id} run={current} t={t} />}
          </div>
        )}
      </div>
    </Dialog>
  );
}

export default function SchedulesPage() {
  const t = useT();
  const [jobs, setJobs] = useState<CronJob[]>([]);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [now, setNow] = useState(() => Date.now());
  const [toast, setToast] = useState<ToastState>(null);

  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<StatusFilter>("all");
  const [userFilter, setUserFilter] = useState(ALL);

  const [profiles, setProfiles] = useState<Record<string, string>>({});
  const [sqlProjects, setSqlProjects] = useState<Option[]>([]);

  const [editing, setEditing] = useState<CronJob | null>(null);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({ name: "", cron: "", prompt: "", profile: "", tz: "", sessionMode: "fixed", enabled: true, sql: "" });
  const patch = (p: Partial<typeof form>) => setForm((f) => ({ ...f, ...p }));

  const [runsJob, setRunsJob] = useState<CronJob | null>(null);
  const [runs, setRuns] = useState<CronRun[]>([]);
  const [runsLoading, setRunsLoading] = useState(false);

  const [deleting, setDeleting] = useState<CronJob | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);

  const [schedulerOn, setSchedulerOn] = useState<boolean | null>(null);
  const [updatingGlobal, setUpdatingGlobal] = useState(false);
  const [restarting, setRestarting] = useState(false);
  const [pendingGlobal, setPendingGlobal] = useState<boolean | null>(null);

  const fail = useCallback((e: unknown, fallback: string) => setToast({ message: e instanceof Error && e.message ? e.message : fallback, variant: "error" }), []);

  const fetchSetup = useCallback(async () => {
    try {
      const res = await apiFetch(`${apiBase()}/admin/query-memory/projects`);
      if (res.ok) {
        const data = await res.json();
        setSqlProjects((data.projects || []).map((p: { slug: string; display_name: string }) => ({ value: p.slug, label: `${p.display_name} (${p.slug})` })));
      }
    } catch {
      // optional: the SQL project picker just stays empty
    }
    try {
      const res = await apiFetch(`${apiBase()}/admin/profiles`);
      if (res.ok) {
        const data: { slug: string; name: string }[] = await res.json();
        setProfiles(Object.fromEntries((data || []).map((p) => [p.slug, p.name || p.slug])));
      }
    } catch {
      // slugs are shown instead of names
    }
  }, []);

  const fetchGlobal = useCallback(async () => {
    try {
      const res = await apiFetch(`${apiBase()}/admin/settings`);
      if (res.ok) {
        const data = await res.json();
        setSchedulerOn(data.settings?.AION_CRON_ENABLED === "1");
      }
    } catch {
      // status stays unknown
    }
  }, []);

  const fetchJobs = useCallback(async () => {
    try {
      const res = await apiFetch(`${apiBase()}/admin/cron-jobs`);
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        if (res.status === 503 && String(err.detail || "").includes("AION_CRON_ENABLED=0")) {
          setSchedulerOn(false);
          setJobs([]);
          setState("ready");
          return;
        }
        throw new Error(err.detail || "load");
      }
      const data = await res.json();
      setJobs(data.jobs || []);
      setNow(Date.now());
      setState("ready");
    } catch {
      setState("error");
    }
  }, []);

  const reload = useCallback(() => {
    setState("loading");
    fetchGlobal();
    fetchJobs();
  }, [fetchGlobal, fetchJobs]);

  useEffect(() => {
    reload();
    fetchSetup();
  }, [reload, fetchSetup]);

  const pollHealth = useCallback(async () => {
    await new Promise((r) => setTimeout(r, 2000));
    for (let attempt = 0; attempt < 30; attempt++) {
      try {
        const res = await fetch(`${apiBase()}/health`);
        if (res.ok && (await res.json()).status === "ok") {
          setRestarting(false);
          setToast({ message: t(`${k}.restart.done`), variant: "success" });
          reload();
          return;
        }
      } catch {
        // backend still coming back
      }
      await new Promise((r) => setTimeout(r, 1500));
    }
    setRestarting(false);
    setToast({ message: t(`${k}.restart.slow`), variant: "error" });
    reload();
  }, [reload, t]);

  const applyGlobal = async (next: boolean) => {
    setUpdatingGlobal(true);
    try {
      const cur = await apiFetch(`${apiBase()}/admin/settings`);
      if (!cur.ok) throw new Error();
      const settings = (await cur.json()).settings || {};
      const res = await apiFetch(`${apiBase()}/admin/settings`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ settings: { ...settings, AION_CRON_ENABLED: next ? "1" : "0" } }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail);
      }
      if ((await res.json()).restarting) {
        setRestarting(true);
        pollHealth();
      } else {
        setToast({ message: t(`${k}.scheduler.${next ? "toast_on" : "toast_off"}`), variant: "success" });
        reload();
      }
    } catch (e) {
      fail(e, t(`${k}.scheduler.toggle_failed`));
    } finally {
      setUpdatingGlobal(false);
    }
  };

  const confirmGlobal = () => {
    if (pendingGlobal === null) return;
    const next = pendingGlobal;
    setPendingGlobal(null);
    applyGlobal(next);
  };

  const openEdit = (j: CronJob) => {
    setEditing(j);
    setForm({ name: j.name, cron: j.cron_expression, prompt: j.prompt, profile: j.profile_slug, tz: j.timezone, sessionMode: j.session_mode, enabled: j.enabled, sql: j.sql_query_project ?? "" });
  };

  const save = async () => {
    if (!editing) return;
    setSaving(true);
    try {
      const res = await apiFetch(`${apiBase()}/admin/cron-jobs/${editing.job_id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: form.name.trim(),
          cron_expression: form.cron.trim(),
          prompt: form.prompt,
          profile_slug: form.profile,
          timezone: form.tz.trim(),
          session_mode: form.sessionMode,
          enabled: form.enabled,
          sql_query_project: form.sql || null,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(typeof err.detail === "string" ? err.detail : t(`${k}.toast.save_failed`));
      }
      setEditing(null);
      setToast({ message: t(`${k}.toast.updated`), variant: "success" });
      await fetchJobs();
    } catch (e) {
      fail(e, t(`${k}.toast.save_failed`));
    } finally {
      setSaving(false);
    }
  };

  const runNow = async (j: CronJob) => {
    setBusyId(j.job_id);
    try {
      const res = await apiFetch(`${apiBase()}/admin/cron-jobs/${j.job_id}/run-now`, { method: "POST" });
      if (!res.ok) throw new Error();
      setToast({ message: t(`${k}.toast.run_started`, { name: j.name }), variant: "success" });
      await fetchJobs();
    } catch (e) {
      fail(e, t(`${k}.toast.run_failed`));
    } finally {
      setBusyId(null);
    }
  };

  const setEnabled = async (j: CronJob, enabled: boolean) => {
    setJobs((all) => all.map((x) => (x.job_id === j.job_id ? { ...x, enabled } : x)));
    try {
      const res = await apiFetch(`${apiBase()}/admin/cron-jobs/${j.job_id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled }),
      });
      if (!res.ok) throw new Error();
      await fetchJobs();
    } catch (e) {
      setJobs((all) => all.map((x) => (x.job_id === j.job_id ? { ...x, enabled: j.enabled } : x)));
      fail(e, t(`${k}.toast.update_failed`));
    }
  };

  const confirmDelete = async () => {
    if (!deleting) return;
    setDeleteBusy(true);
    try {
      const res = await apiFetch(`${apiBase()}/admin/cron-jobs/${deleting.job_id}`, { method: "DELETE" });
      if (!res.ok) throw new Error();
      setDeleting(null);
      setToast({ message: t(`${k}.toast.deleted`), variant: "success" });
      await fetchJobs();
    } catch (e) {
      fail(e, t(`${k}.toast.delete_failed`));
    } finally {
      setDeleteBusy(false);
    }
  };

  const openRuns = async (j: CronJob) => {
    setRunsJob(j);
    setRuns([]);
    setRunsLoading(true);
    try {
      const res = await apiFetch(`${apiBase()}/admin/cron-jobs/${j.job_id}/runs`);
      if (!res.ok) throw new Error();
      setRuns((await res.json()).runs || []);
    } catch {
      setRuns([]);
    } finally {
      setRunsLoading(false);
    }
  };

  const profileName = useCallback((slug: string) => profiles[slug] || slug, [profiles]);

  const userOptions = useMemo<Option[]>(
    () => [{ value: ALL, label: t(`${k}.list.all_users`) }, ...Array.from(new Set(jobs.map((j) => j.user_id).filter(Boolean))).sort().map((v) => ({ value: v, label: v }))],
    [jobs, t],
  );
  const profileOptions = useMemo<Option[]>(() => {
    const slugs = new Set(Object.keys(profiles));
    if (form.profile) slugs.add(form.profile);
    return Array.from(slugs).map((v) => ({ value: v, label: profileName(v) })).sort((a, b) => a.label.localeCompare(b.label));
  }, [profiles, form.profile, profileName]);

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    return jobs
      .filter((j) => {
        if (status === "on" && !j.enabled) return false;
        if (status === "off" && j.enabled) return false;
        if (userFilter !== ALL && j.user_id !== userFilter) return false;
        if (!q) return true;
        return [j.name, j.user_id, j.profile_slug, profileName(j.profile_slug), j.prompt, j.cron_expression].some((v) => (v || "").toLowerCase().includes(q));
      })
      .sort((a, b) => Number(b.enabled) - Number(a.enabled) || (toMs(a.next_run_at) || Infinity) - (toMs(b.next_run_at) || Infinity) || a.name.localeCompare(b.name));
  }, [jobs, query, status, userFilter, profileName]);

  const filtering = !!query.trim() || status !== "all" || userFilter !== ALL;
  const clearFilters = () => {
    setQuery("");
    setStatus("all");
    setUserFilter(ALL);
  };

  const valid = form.name.trim() !== "" && form.cron.trim().split(/\s+/).length === 5 && form.tz.trim() !== "" && form.profile !== "";
  const noneAtAll = state === "ready" && jobs.length === 0;
  const loading = state === "loading";

  return (
    <div className="mx-auto flex max-w-[84rem] flex-col gap-6">
      <PageToast toast={toast} onDismiss={() => setToast(null)} />

      <header className="flex flex-col gap-4 pt-2 sm:flex-row sm:items-end">
        <div className="min-w-0 flex-1">
          <h1 className="text-balance text-2xl font-semibold tracking-[-0.02em] sm:text-[28px]">{t(`${k}.title`)}</h1>
          <p className="mt-1 max-w-[60ch] text-sm text-muted-foreground">{t(`${k}.subtitle`)}</p>
        </div>
        <button type="button" className={outlineBtn} onClick={reload} disabled={loading}>
          <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} aria-hidden />
          {t(`${k}.refresh`)}
        </button>
      </header>

      {schedulerOn !== null && (
        <section
          aria-label={t(`${k}.scheduler.title`)}
          className={cn("flex flex-wrap items-center gap-x-4 gap-y-3 rounded-2xl border px-5 py-4", schedulerOn ? "border-border/70 bg-card" : "border-warning/30 bg-warning/10")}
        >
          <span className={cn("flex h-9 w-9 shrink-0 items-center justify-center rounded-xl", schedulerOn ? "bg-success/12 text-success" : "bg-warning/15 text-warning")}>
            {schedulerOn ? <span className="h-2.5 w-2.5 rounded-full bg-current" aria-hidden /> : <AlertTriangle className="h-4 w-4" aria-hidden />}
          </span>
          <div className="min-w-[14rem] flex-1">
            <h2 className="text-sm font-semibold">{t(`${k}.scheduler.${schedulerOn ? "on_title" : "off_title"}`)}</h2>
            <p className="mt-0.5 max-w-[64ch] text-sm text-muted-foreground">{t(`${k}.scheduler.${schedulerOn ? "on_body" : "off_body"}`)}</p>
          </div>
          <div className="flex items-center gap-3">
            {updatingGlobal && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" aria-hidden />}
            <Switch checked={schedulerOn} disabled={updatingGlobal || restarting} onChange={(v) => setPendingGlobal(v)} label={t(`${k}.scheduler.title`)} />
          </div>
        </section>
      )}

      {noneAtAll ? (
        <div className="flex flex-col items-center rounded-3xl border border-dashed border-border px-6 py-20 text-center">
          <h2 className="text-lg font-semibold tracking-[-0.015em]">{t(`${k}.list.none_title`)}</h2>
          <p className="mt-1.5 max-w-[46ch] text-sm text-muted-foreground">{t(`${k}.list.none_body`)}</p>
        </div>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <div className="min-w-[14rem] flex-1 sm:max-w-sm">
              <SearchField value={query} onChange={setQuery} placeholder={t(`${k}.list.search`)} />
            </div>

            <div role="group" aria-label={t(`${k}.list.status_aria`)} className="inline-flex shrink-0 rounded-xl border border-border bg-card p-0.5">
              {(["all", "on", "off"] as const).map((v) => (
                <button
                  key={v}
                  type="button"
                  aria-pressed={status === v}
                  onClick={() => setStatus(v)}
                  className={cn("focus-ring h-8 rounded-[10px] px-3 text-sm font-medium transition-colors", status === v ? "bg-secondary text-foreground" : "text-muted-foreground hover:text-foreground")}
                >
                  {t(`${k}.list.status_${v}`)}
                </button>
              ))}
            </div>

            {userOptions.length > 2 && (
              <Select size="sm" value={userFilter} onChange={setUserFilter} options={userOptions} aria-label={t(`${k}.list.col_user`)} className="w-44" />
            )}

            {state === "ready" && (
              <span className="ml-auto text-sm tabular-nums text-muted-foreground">
                {filtering ? t(`${k}.list.count_filtered`, { shown: rows.length, total: jobs.length }) : t(`${k}.list.count`, { n: jobs.length })}
              </span>
            )}
          </div>

          {loading ? (
            <div className="flex items-center gap-2 px-1 py-10 text-sm text-muted-foreground" role="status">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
              {t(`${k}.loading`)}
            </div>
          ) : state === "error" ? (
            <div className="flex flex-col items-start gap-3 px-1 py-10">
              <p className="text-sm text-destructive">{t(`${k}.error`)}</p>
              <button type="button" className={outlineBtn} onClick={reload}>
                {t(`${k}.retry`)}
              </button>
            </div>
          ) : rows.length === 0 ? (
            <div className="rounded-3xl border border-border/70 bg-card px-6 py-16 text-center">
              <h2 className="text-lg font-semibold tracking-[-0.015em]">{t(`${k}.list.empty_title`)}</h2>
              <p className="mt-1.5 text-sm text-muted-foreground">{t(`${k}.list.empty_body`)}</p>
              {filtering && (
                <button type="button" className={cn(ghostBtn, "mt-3")} onClick={clearFilters}>
                  {t(`${k}.list.clear`)}
                </button>
              )}
            </div>
          ) : (
            <div className="rounded-3xl border border-border/70 bg-card">
              <div className={cn("hidden items-center gap-4 border-b border-border/60 px-5 py-2.5 text-xs font-medium text-muted-foreground md:grid", GRID)}>
                <span>{t(`${k}.list.col_job`)}</span>
                <span>{t(`${k}.list.col_user`)}</span>
                <span>{t(`${k}.list.col_profile`)}</span>
                <span>{t(`${k}.list.col_next`)}</span>
                <span>{t(`${k}.list.col_last`)}</span>
                <span className="text-right">{t(`${k}.list.col_actions`)}</span>
              </div>
              <ul className="overflow-hidden rounded-b-3xl">
                {rows.map((j) => {
                  const next = j.enabled && j.next_run_at ? nextWhen(j.next_run_at, now) : "";
                  const lastMs = toMs(j.last_run?.started_at);
                  return (
                    <li key={j.job_id} className={cn("grid items-center gap-x-4 gap-y-2 border-b border-border/40 px-5 py-3.5 last:border-b-0 hover:bg-secondary/40", GRID)}>
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <span className={cn("truncate text-sm font-medium", !j.enabled && "text-muted-foreground")}>{j.name}</span>
                          {!j.enabled && <span className="shrink-0 rounded-full bg-secondary px-2 py-0.5 text-xs text-muted-foreground">{t(`${k}.list.paused`)}</span>}
                        </div>
                        <div className="mt-0.5 flex min-w-0 flex-wrap items-center gap-x-2 text-xs text-muted-foreground">
                          <code className="font-mono tabular-nums text-foreground/80">{j.cron_expression}</code>
                          <span className="truncate">
                            {j.timezone} · {t(`${k}.list.session_${j.session_mode === "new" ? "new" : "fixed"}`)}
                          </span>
                        </div>
                      </div>

                      <div className="min-w-0 truncate text-sm text-muted-foreground md:text-foreground" title={j.user_id}>
                        {j.user_id}
                      </div>
                      <div className="min-w-0 truncate text-sm text-muted-foreground">{profileName(j.profile_slug) || "—"}</div>

                      <div className="text-sm tabular-nums text-muted-foreground" title={j.next_run_at ? fullWhen(toMs(j.next_run_at)) : undefined}>
                        {next || "—"}
                      </div>

                      <div className="flex flex-col items-start gap-0.5">
                        <StatusPill status={j.last_run?.status} t={t} />
                        {lastMs > 0 && (
                          <span className="text-xs tabular-nums text-muted-foreground" title={fullWhen(lastMs)}>
                            {shortWhen(lastMs, now)}
                          </span>
                        )}
                      </div>

                      <div className="flex items-center justify-start gap-0.5 md:justify-end">
                        <Switch checked={j.enabled} onChange={(v) => setEnabled(j, v)} label={t(`${k}.actions.${j.enabled ? "disable" : "enable"}`, { name: j.name })} />
                        <span className="ml-1 flex items-center">
                          <button type="button" className={iconBtn} title={t(`${k}.actions.run`)} aria-label={t(`${k}.actions.run`)} disabled={busyId === j.job_id} onClick={() => runNow(j)}>
                            {busyId === j.job_id ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <Play className="h-4 w-4" aria-hidden />}
                          </button>
                          <button type="button" className={iconBtn} title={t(`${k}.actions.history`)} aria-label={t(`${k}.actions.history`)} onClick={() => openRuns(j)}>
                            <History className="h-4 w-4" aria-hidden />
                          </button>
                          <button type="button" className={iconBtn} title={t(`${k}.actions.edit`)} aria-label={t(`${k}.actions.edit`)} onClick={() => openEdit(j)}>
                            <Pencil className="h-4 w-4" aria-hidden />
                          </button>
                          <button type="button" className={cn(iconBtn, "hover:text-destructive")} title={t(`${k}.actions.delete`)} aria-label={t(`${k}.actions.delete`)} onClick={() => setDeleting(j)}>
                            <Trash2 className="h-4 w-4" aria-hidden />
                          </button>
                        </span>
                      </div>
                    </li>
                  );
                })}
              </ul>
            </div>
          )}
        </>
      )}

      {editing && (
        <Dialog title={t(`${k}.edit.title`)} closeLabel={t(`${k}.edit.cancel`)} onClose={() => !saving && setEditing(null)} className="max-w-2xl">
          <form
            className="flex flex-col gap-4"
            onSubmit={(e) => {
              e.preventDefault();
              if (valid && !saving) save();
            }}
          >
            <Field label={t(`${k}.edit.name`)}>
              <input className={inputCls} value={form.name} onChange={(e) => patch({ name: e.target.value })} autoFocus />
            </Field>

            <div className="grid gap-4 sm:grid-cols-2">
              <Field label={t(`${k}.edit.cron`)} hint={t(`${k}.edit.cron_hint`)}>
                <input className={cn(inputCls, "font-mono tabular-nums")} value={form.cron} onChange={(e) => patch({ cron: e.target.value })} placeholder="0 9 * * 1-5" spellCheck={false} autoComplete="off" />
              </Field>
              <Field label={t(`${k}.edit.timezone`)}>
                <input className={inputCls} value={form.tz} onChange={(e) => patch({ tz: e.target.value })} placeholder="Europe/Rome" spellCheck={false} autoComplete="off" />
              </Field>
            </div>

            <Field label={t(`${k}.edit.prompt`)}>
              <textarea className={cn(inputCls, "min-h-28 resize-y leading-relaxed")} value={form.prompt} onChange={(e) => patch({ prompt: e.target.value })} />
            </Field>

            <div className="grid gap-4 sm:grid-cols-2">
              <div className="flex flex-col gap-1.5">
                <span className="text-sm font-medium">{t(`${k}.edit.profile`)}</span>
                <Select value={form.profile} onChange={(v) => patch({ profile: v })} options={profileOptions} aria-label={t(`${k}.edit.profile`)} />
              </div>
              <div className="flex flex-col gap-1.5">
                <span className="text-sm font-medium">{t(`${k}.edit.session_mode`)}</span>
                <Select
                  value={form.sessionMode}
                  onChange={(v) => patch({ sessionMode: v })}
                  aria-label={t(`${k}.edit.session_mode`)}
                  options={[
                    { value: "fixed", label: t(`${k}.list.session_fixed`) },
                    { value: "new", label: t(`${k}.list.session_new`) },
                  ]}
                />
              </div>
            </div>

            <div className="flex flex-col gap-1.5">
              <span className="text-sm font-medium">{t(`${k}.edit.sql_project`)}</span>
              <Select value={form.sql} onChange={(v) => patch({ sql: v })} options={[{ value: "", label: t(`${k}.edit.sql_none`) }, ...sqlProjects]} aria-label={t(`${k}.edit.sql_project`)} />
              {sqlProjects.length === 0 && <span className="text-xs text-muted-foreground">{t(`${k}.edit.sql_empty`)}</span>}
            </div>

            <div className="flex items-center justify-between gap-4 rounded-2xl border border-border/70 px-4 py-3">
              <div>
                <p className="text-sm font-medium">{t(`${k}.edit.enabled`)}</p>
                <p className="text-xs text-muted-foreground">{t(`${k}.edit.enabled_hint`)}</p>
              </div>
              <Switch checked={form.enabled} onChange={(v) => patch({ enabled: v })} label={t(`${k}.edit.enabled`)} />
            </div>

            <div className="flex justify-end gap-2 pt-1">
              <button type="button" className={ghostBtn} onClick={() => setEditing(null)} disabled={saving}>
                {t(`${k}.edit.cancel`)}
              </button>
              <button type="submit" className={solidBtn} disabled={!valid || saving}>
                {saving && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />}
                {saving ? t(`${k}.edit.saving`) : t(`${k}.edit.save`)}
              </button>
            </div>
          </form>
        </Dialog>
      )}

      {runsJob && <RunsDialog job={runsJob} runs={runs} loading={runsLoading} now={now} t={t} onClose={() => setRunsJob(null)} />}

      {deleting && <DeleteDialog name={deleting.name} busy={deleteBusy} ns={`${k}.delete`} t={t} onConfirm={confirmDelete} onClose={() => !deleteBusy && setDeleting(null)} />}

      {pendingGlobal !== null && (
        <Dialog title={t(`${k}.restart.title`)} closeLabel={t(`${k}.restart.cancel`)} onClose={() => setPendingGlobal(null)}>
          <div className="flex flex-col gap-5">
            <p className="text-sm text-muted-foreground">{t(`${k}.restart.body_${pendingGlobal ? "on" : "off"}`)}</p>
            <div className="flex justify-end gap-2">
              <button type="button" className={ghostBtn} autoFocus onClick={() => setPendingGlobal(null)}>
                {t(`${k}.restart.cancel`)}
              </button>
              <button type="button" className={solidBtn} onClick={confirmGlobal}>
                {t(`${k}.restart.confirm`)}
              </button>
            </div>
          </div>
        </Dialog>
      )}

      {restarting && (
        <div role="alertdialog" aria-live="polite" aria-labelledby="restart-title" className="fixed inset-0 z-50 flex items-center justify-center bg-black/55 p-4">
          <div className="flex w-full max-w-sm flex-col items-center gap-4 rounded-3xl border border-border bg-card px-6 py-8 text-center shadow-[0_24px_60px_-20px_rgba(0,0,0,0.45)]">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" aria-hidden />
            <div>
              <h2 id="restart-title" className="text-lg font-semibold tracking-[-0.015em]">
                {t(`${k}.restart.working_title`)}
              </h2>
              <p className="mt-1.5 text-sm text-muted-foreground">{t(`${k}.restart.working_body`)}</p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
