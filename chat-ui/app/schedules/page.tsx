"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Clock, Play, Plus, Power, PowerOff, Trash2 } from "lucide-react";
import { SecondaryPageLayout } from "@/components/layout/SecondaryPageLayout";
import {
  CronScheduleBuilder,
  describeCronHuman,
} from "@/components/schedules/CronScheduleBuilder";
import { AppSelect } from "@/components/ui/radix-select";
import { ProjectSelector } from "@/components/query-memory/ProjectSelector";
import {
  createCronJob,
  deleteCronJob,
  fetchCronJobsStatus,
  fetchProfiles,
  listCronJobs,
  listCronJobRuns,
  patchCronJob,
  runCronJobNow,
  type ScheduledJobRow,
  type ScheduledRunRow,
} from "@/lib/api/aion";
import { isValidCronShape } from "@/lib/cron/schedule-builder";
import { useStoredToken, useStoredUserId } from "@/lib/auth/use-stored-auth";
import { useT } from "@/lib/i18n/use-t";

const inputClass =
  "focus-ring w-full rounded-lg border border-input bg-background px-3 py-2 text-sm";

/**
 * Format a UTC ISO string (next_run_at from the backend) in the job's own
 * timezone so the displayed time matches the cron schedule the user set.
 * Falls back to browser locale if the timezone is invalid or unavailable.
 */
function formatNextRunAt(isoUtc: string, tz?: string | null): string {
  const d = new Date(isoUtc);
  if (isNaN(d.getTime())) return isoUtc;
  try {
    return d.toLocaleString(undefined, {
      timeZone: tz || undefined,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    });
  } catch {
    // Fallback if tz string is unrecognized by Intl
    return d.toLocaleString();
  }
}

const COMMON_TIMEZONES = [
  "Europe/Rome",
  "Europe/London",
  "Europe/Berlin",
  "Europe/Paris",
  "UTC",
  "America/New_York",
  "America/Los_Angeles",
  "Asia/Tokyo",
];

export default function SchedulesPage() {
  const t = useT();
  const userId = useStoredUserId();
  const token = useStoredToken();
  const [jobs, setJobs] = useState<ScheduledJobRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [cronEnabled, setCronEnabled] = useState(true);
  const [cronHint, setCronHint] = useState<string | null>(null);
  const [dialogMode, setDialogMode] = useState<"create" | "edit" | null>(null);
  const [editingJob, setEditingJob] = useState<ScheduledJobRow | null>(null);

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

  const active = jobs.filter((j) => j.enabled);
  const paused = jobs.filter((j) => !j.enabled);

  if (loading) {
    return (
      <div className="mx-auto max-w-3xl p-8 text-muted-foreground">
        {t("schedulesPage.loading")}
      </div>
    );
  }

  return (
    <SecondaryPageLayout
      title={t("schedulesPage.title")}
      subtitle={t("schedulesPage.subtitle")}
      backLabel={t("schedulesPage.back_chat")}
      headerAction={
        cronEnabled ? (
          <button
            type="button"
            onClick={() => {
              setEditingJob(null);
              setDialogMode("create");
            }}
            className="focus-ring flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90"
          >
            <Plus className="h-4 w-4" aria-hidden />
            {t("schedulesPage.new")}
          </button>
        ) : null
      }
    >
      {!cronEnabled && (
        <div className="mb-4 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm text-amber-900 dark:text-amber-200">
          {cronHint || t("schedulesPage.feature_disabled")}
        </div>
      )}

      {fetchError && (
        <div className="mb-4 rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {fetchError}
        </div>
      )}

      {jobs.length > 0 && (
        <div className="mb-6 flex flex-wrap gap-2">
          <span className="rounded-full bg-emerald-500/15 px-3 py-1 text-xs font-medium text-emerald-700 dark:text-emerald-400">
            {active.length} {t("schedulesPage.badge_active")}
          </span>
          {paused.length > 0 && (
            <span className="rounded-full bg-amber-500/15 px-3 py-1 text-xs font-medium text-amber-800 dark:text-amber-300">
              {paused.length} {t("schedulesPage.badge_paused")}
            </span>
          )}
        </div>
      )}

      {active.length > 0 && (
        <section className="mb-8">
          <h2 className="mb-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            {t("schedulesPage.section_active")}
          </h2>
          <div className="space-y-2">
            {active.map((job) => (
              <ScheduleJobCard
                key={job.job_id}
                job={job}
                userId={userId}
                token={token}
                onEdit={() => {
                  setEditingJob(job);
                  setDialogMode("edit");
                }}
                onToggle={() => void toggleJob(job)}
                onRunNow={() => void runNow(job.job_id)}
                onDelete={() => void removeJob(job.job_id)}
              />
            ))}
          </div>
        </section>
      )}

      {paused.length > 0 && (
        <section className="mb-8">
          <h2 className="mb-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            {t("schedulesPage.section_paused")}
          </h2>
          <div className="space-y-2">
            {paused.map((job) => (
              <ScheduleJobCard
                key={job.job_id}
                job={job}
                userId={userId}
                token={token}
                onEdit={() => {
                  setEditingJob(job);
                  setDialogMode("edit");
                }}
                onToggle={() => void toggleJob(job)}
                onRunNow={() => void runNow(job.job_id)}
                onDelete={() => void removeJob(job.job_id)}
              />
            ))}
          </div>
        </section>
      )}

      {jobs.length === 0 && !fetchError && (
        <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-border py-16 px-4 text-center text-muted-foreground">
          <Clock className="mb-3 h-10 w-10 opacity-40" aria-hidden />
          <p className="text-sm font-medium text-foreground">{t("schedulesPage.empty")}</p>
          <p className="mt-2 max-w-md text-xs">{t("schedulesPage.empty_hint")}</p>
          <button
            type="button"
            onClick={() => setDialogMode("create")}
            className="focus-ring mt-6 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
          >
            {t("schedulesPage.new")}
          </button>
        </div>
      )}

      {dialogMode && (
        <ScheduleJobDialog
          mode={dialogMode}
          job={editingJob}
          userId={userId}
          token={token}
          onClose={() => {
            setDialogMode(null);
            setEditingJob(null);
            void load();
          }}
        />
      )}
    </SecondaryPageLayout>
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

function ScheduleJobCard({
  job,
  userId,
  token,
  onEdit,
  onToggle,
  onRunNow,
  onDelete,
}: {
  job: ScheduledJobRow;
  userId: string;
  token: string | null;
  onEdit: () => void;
  onToggle: () => void;
  onRunNow: () => void;
  onDelete: () => void;
}) {
  const t = useT();
  const scheduleLabel = describeCronHuman(job.cron_expression, t);

  return (
    <div
      className={`rounded-xl border ${
        job.enabled ? "border-emerald-500/25 bg-emerald-500/5" : "border-border bg-card/30"
      }`}
    >
      <div className="flex flex-wrap items-center justify-between gap-3 p-4">
      <div className="flex min-w-0 items-start gap-3">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-muted">
          <Clock className="h-5 w-5 text-muted-foreground" aria-hidden />
        </div>
        <div className="min-w-0">
          <div className="font-medium">{job.name}</div>
          <div className="text-xs text-muted-foreground">{scheduleLabel}</div>
          <div className="mt-1 text-xs text-muted-foreground">
            {job.profile_slug}
            {job.timezone ? ` · ${job.timezone}` : ""}
          </div>
          {job.next_run_at && job.enabled && (
            <p className="mt-1 text-xs text-muted-foreground">
              {t("schedulesPage.next")}: {formatNextRunAt(job.next_run_at, job.timezone)}
            </p>
          )}
          {job.last_run?.status && (
            <span
              className={`mt-2 inline-block rounded-full px-2 py-0.5 text-xs ${
                job.last_run.status === "success"
                  ? "bg-emerald-500/15 text-emerald-800 dark:text-emerald-300"
                  : job.last_run.status === "error"
                    ? "bg-destructive/15 text-destructive"
                    : "bg-muted text-muted-foreground"
              }`}
            >
              {t("schedulesPage.last_run")}: {job.last_run.status}
            </span>
          )}
          <p className="mt-2 line-clamp-2 text-xs text-muted-foreground">{job.prompt}</p>
          {job.session_mode === "fixed" && job.session_id && (
            <Link href={`/c/${job.session_id}`} className="mt-1 inline-block text-xs text-primary hover:underline">
              {t("schedulesPage.open_session")}
            </Link>
          )}
        </div>
      </div>
      <div className="flex shrink-0 flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={onRunNow}
          title={t("schedulesPage.run_now")}
          className="focus-ring rounded-lg border border-border px-3 py-2 text-sm hover:bg-muted"
        >
          <Play className="h-4 w-4" />
        </button>
        <button
          type="button"
          onClick={onToggle}
          className="focus-ring rounded-lg border border-border px-3 py-2 text-sm hover:bg-muted"
          title={job.enabled ? t("schedulesPage.pause") : t("schedulesPage.resume")}
        >
          {job.enabled ? <PowerOff className="h-4 w-4" /> : <Power className="h-4 w-4" />}
        </button>
        <button
          type="button"
          onClick={onEdit}
          className="focus-ring rounded-lg border border-border px-4 py-2 text-sm font-medium hover:bg-muted"
        >
          {t("schedulesPage.edit")}
        </button>
        <button
          type="button"
          onClick={onDelete}
          className="focus-ring rounded-lg border border-destructive/30 px-3 py-2 text-sm text-destructive hover:bg-destructive/10"
          title={t("schedulesPage.delete")}
        >
          <Trash2 className="h-4 w-4" />
        </button>
      </div>
      </div>
      {userId ? <ScheduleJobRuns jobId={job.job_id} userId={userId} token={token} /> : null}
    </div>
  );
}

function ScheduleJobRuns({
  jobId,
  userId,
  token,
}: {
  jobId: string;
  userId: string;
  token: string | null;
}) {
  const t = useT();
  const [runs, setRuns] = useState<ScheduledRunRow[]>([]);
  const [loading, setLoading] = useState(true);

  const loadRuns = useCallback(async () => {
    try {
      const rows = await listCronJobRuns(userId, jobId, token);
      setRuns(rows.slice(0, 8));
    } catch {
      setRuns([]);
    } finally {
      setLoading(false);
    }
  }, [userId, jobId, token]);

  useEffect(() => {
    setLoading(true);
    void loadRuns();
  }, [loadRuns]);

  useEffect(() => {
    if (!runs.some((r) => r.status === "running")) return;
    const timer = setInterval(() => void loadRuns(), 2000);
    return () => clearInterval(timer);
  }, [runs, loadRuns]);

  return (
    <div className="border-t border-border/60 px-4 py-3">
      <p className="mb-2 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
        {t("schedulesPage.recent_runs")}
      </p>
      {loading ? (
        <p className="text-xs text-muted-foreground">{t("schedulesPage.runs_loading")}</p>
      ) : runs.length === 0 ? (
        <p className="text-xs text-muted-foreground">{t("schedulesPage.runs_empty")}</p>
      ) : (
        <ul className="space-y-1.5">
          {runs.map((run) => {
            const chatId = run.conversation_id || run.session_id;
            const when = run.started_at ? new Date(run.started_at).toLocaleString() : "";
            const statusClass =
              run.status === "success"
                ? "text-emerald-700 dark:text-emerald-400"
                : run.status === "error"
                  ? "text-destructive"
                  : run.status === "running"
                    ? "text-amber-700 dark:text-amber-300"
                    : "text-muted-foreground";
            return (
              <li
                key={run.run_id}
                className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border/50 bg-background/40 px-2.5 py-2 text-xs"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className={`font-medium capitalize ${statusClass}`}>{run.status}</span>
                    <span className="text-muted-foreground">{when}</span>
                  </div>
                  {run.error_message && (
                    <p className="mt-0.5 line-clamp-2 text-destructive">{run.error_message}</p>
                  )}
                  {run.assistant_preview && !run.error_message && (
                    <p className="mt-0.5 line-clamp-2 text-muted-foreground">{run.assistant_preview}</p>
                  )}
                </div>
                {chatId ? (
                  <Link
                    href={`/c/${chatId}`}
                    className="focus-ring shrink-0 rounded-md border border-border px-2 py-1 text-xs font-medium text-primary hover:bg-muted"
                  >
                    {t("schedulesPage.open_run_chat")}
                  </Link>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

function ScheduleJobDialog({
  mode,
  job,
  userId,
  token,
  onClose,
}: {
  mode: "create" | "edit";
  job: ScheduledJobRow | null;
  userId: string;
  token: string | null;
  onClose: () => void;
}) {
  const t = useT();
  const [profiles, setProfiles] = useState<Array<{ name: string; slug: string }>>([]);
  const [name, setName] = useState(job?.name ?? "");
  const [cron, setCron] = useState(job?.cron_expression ?? "0 9 * * *");
  const [prompt, setPrompt] = useState(job?.prompt ?? "");
  const [profile, setProfile] = useState(job?.profile_slug ?? "generic_assistant");
  const [sessionMode, setSessionMode] = useState<"fixed" | "new">(
    (job?.session_mode as "fixed" | "new") ?? "fixed",
  );
  const [timezone, setTimezone] = useState(job?.timezone ?? "Europe/Rome");
  const [sqlProject, setSqlProject] = useState(job?.sql_query_project ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const sqlProjectPayload = (sqlProject || "").trim().toLowerCase() === "default"
    ? null
    : (sqlProject || "").trim() || null;

  useEffect(() => {
    if (!userId) return;
    void fetchProfiles(userId, token).then((rows) => {
      const mapped = rows.map((row) => ({
        name: row.name,
        slug: (row as { slug?: string }).slug || row.name,
      }));
      setProfiles(mapped);
      if (!job && mapped[0]?.slug) setProfile(mapped[0].slug);
    });
  }, [userId, token, job]);

  const tzItems = COMMON_TIMEZONES.map((tz) => ({ value: tz, label: tz }));
  const profileItems = profiles.map((p) => ({ value: p.slug, label: p.name }));

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (!userId || !name.trim() || !prompt.trim()) {
      setError(t("schedulesPage.form_required"));
      return;
    }
    if (!isValidCronShape(cron)) {
      setError(t("schedulesPage.cron.invalid"));
      return;
    }
    setSaving(true);
    setError(null);
    try {
      if (mode === "create") {
        const created = await createCronJob(
          userId,
          {
            name: name.trim(),
            cron_expression: cron,
            prompt: prompt.trim(),
            profile_slug: profile,
            session_mode: sessionMode,
            sql_query_project: sqlProjectPayload,
            timezone,
            enabled: true,
          },
          token,
        );
        if (!created) throw new Error(t("schedulesPage.save_error"));
      } else if (job) {
        const updated = await patchCronJob(
          userId,
          job.job_id,
          {
            name: name.trim(),
            cron_expression: cron,
            prompt: prompt.trim(),
            profile_slug: profile,
            session_mode: sessionMode,
            sql_query_project: sqlProjectPayload,
            timezone,
          },
          token,
        );
        if (!updated) throw new Error(t("schedulesPage.save_error"));
      }
      onClose();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : t("schedulesPage.save_error"));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-xl border border-border bg-background shadow-xl">
        <form onSubmit={(e) => void save(e)} className="p-6">
          <div className="mb-4 flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-muted">
              <Clock className="h-5 w-5" aria-hidden />
            </div>
            <div className="min-w-0 flex-1">
              <h2 className="text-lg font-semibold">
                {mode === "create" ? t("schedulesPage.create_title") : t("schedulesPage.edit_title")}
              </h2>
              <p className="text-xs text-muted-foreground">{t("schedulesPage.dialog_subtitle")}</p>
            </div>
            <button
              type="button"
              onClick={onClose}
              className="focus-ring text-muted-foreground hover:text-foreground"
              aria-label={t("schedulesPage.cancel")}
            >
              ×
            </button>
          </div>

          <div className="space-y-4">
            <div>
              <label className="mb-1 block text-sm font-medium">
                {t("schedulesPage.field_name")}
                <span className="ml-1 text-destructive">*</span>
              </label>
              <input
                className={inputClass}
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
              />
            </div>

            <div>
              <label className="mb-2 block text-sm font-medium">{t("schedulesPage.schedule_label")}</label>
              <CronScheduleBuilder
                key={job?.job_id ?? "new"}
                initialValue={job?.cron_expression ?? cron}
                onChange={setCron}
                timezone={timezone}
              />
            </div>

            <div>
              <label className="mb-1 block text-sm font-medium">{t("schedulesPage.field_timezone")}</label>
              <AppSelect
                value={timezone}
                onValueChange={setTimezone}
                items={tzItems}
                triggerClassName="w-full max-w-none"
              />
            </div>

            <div>
              <label className="mb-1 block text-sm font-medium">
                {t("schedulesPage.field_prompt")}
                <span className="ml-1 text-destructive">*</span>
              </label>
              <textarea
                className={cnTextarea}
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                required
                rows={4}
              />
            </div>

            {profileItems.length > 0 && (
              <div>
                <label className="mb-1 block text-sm font-medium">{t("schedulesPage.field_profile")}</label>
                <AppSelect
                  value={profile}
                  onValueChange={setProfile}
                  items={profileItems}
                  triggerClassName="w-full max-w-none"
                />
              </div>
            )}

            <div>
              <label className="mb-1 block text-sm font-medium">
                {t("schedulesPage.field_sql_project")}
              </label>
              <ProjectSelector
                userId={userId}
                token={token}
                profileSlug={profile}
                value={sqlProject || "default"}
                onChange={setSqlProject}
                className="w-full"
              />
              <p className="mt-1 text-[11px] text-muted-foreground">
                {t("schedulesPage.field_sql_project_hint")}
              </p>
            </div>

            <fieldset className="space-y-2">
              <legend className="text-sm font-medium">{t("schedulesPage.session_legend")}</legend>
              <label className="flex cursor-pointer items-center gap-2 text-sm">
                <input
                  type="radio"
                  name="session_mode"
                  checked={sessionMode === "fixed"}
                  onChange={() => setSessionMode("fixed")}
                />
                {t("schedulesPage.session_fixed")}
              </label>
              <label className="flex cursor-pointer items-center gap-2 text-sm">
                <input
                  type="radio"
                  name="session_mode"
                  checked={sessionMode === "new"}
                  onChange={() => setSessionMode("new")}
                />
                {t("schedulesPage.session_new")}
              </label>
            </fieldset>
          </div>

          {error && (
            <div className="mt-4 rounded-lg border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
              {error}
            </div>
          )}

          <div className="mt-6 flex justify-end gap-3">
            <button
              type="button"
              onClick={onClose}
              className="focus-ring rounded-lg border border-border px-4 py-2 text-sm hover:bg-muted"
            >
              {t("schedulesPage.cancel")}
            </button>
            <button
              type="submit"
              disabled={saving}
              className="focus-ring rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
            >
              {saving
                ? t("schedulesPage.saving")
                : mode === "create"
                  ? t("schedulesPage.create")
                  : t("schedulesPage.save")}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

const cnTextarea = `${inputClass} min-h-[88px] resize-y`;
