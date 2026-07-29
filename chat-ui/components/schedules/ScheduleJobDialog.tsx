"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Clock, X } from "lucide-react";

import { ComposerOptionRow } from "@/components/chat/ComposerOptionRow";
import { ProfileOptionGrid } from "@/components/chat/ProfileOptionGrid";
import { ProjectSelector } from "@/components/query-memory/ProjectSelector";
import {
  CronScheduleBuilder,
} from "@/components/schedules/CronScheduleBuilder";
import { AppSelect } from "@/components/ui/radix-select";
import {
  createCronJob,
  fetchProfiles,
  listCronJobRuns,
  patchCronJob,
  type ScheduledJobRow,
  type ScheduledRunRow,
} from "@/lib/api/aion";
import { isValidCronShape } from "@/lib/cron/schedule-builder";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";

const inputClass =
  "focus-ring w-full rounded-xl border border-input bg-background/60 px-3 py-2.5 text-sm";

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

const PROMPT_TEMPLATES = ["briefing", "inbox", "weekly", "research"] as const;

export function ScheduleJobDialog({
  mode,
  job,
  userId,
  token,
  initialName,
  initialPrompt,
  onClose,
}: {
  mode: "create" | "edit";
  job: ScheduledJobRow | null;
  userId: string;
  token: string | null;
  initialName?: string;
  initialPrompt?: string;
  onClose: () => void;
}) {
  const t = useT();
  const [profiles, setProfiles] = useState<
    Array<{ name: string; slug: string; description?: string }>
  >([]);
  const [name, setName] = useState(job?.name ?? initialName ?? "");
  const [cron, setCron] = useState(job?.cron_expression ?? "0 9 * * *");
  const [prompt, setPrompt] = useState(job?.prompt ?? initialPrompt ?? "");
  const [profile, setProfile] = useState(job?.profile_slug ?? "generic_assistant");
  const [sessionMode, setSessionMode] = useState<"fixed" | "new">(
    (job?.session_mode as "fixed" | "new") ?? "fixed",
  );
  const [timezone, setTimezone] = useState(job?.timezone ?? "Europe/Rome");
  const [sqlProject, setSqlProject] = useState(job?.sql_query_project ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const sqlProjectPayload =
    (sqlProject || "").trim().toLowerCase() === "default"
      ? null
      : (sqlProject || "").trim() || null;

  useEffect(() => {
    if (!userId) return;
    void fetchProfiles(userId, token).then((rows) => {
      const mapped = rows.map((row) => ({
        name: row.name,
        slug: (row as { slug?: string }).slug || row.name,
        description: row.description,
      }));
      setProfiles(mapped);
      if (!job && mapped[0]?.slug) setProfile(mapped[0].slug);
    });
  }, [userId, token, job]);

  const tzItems = COMMON_TIMEZONES.map((tz) => ({ value: tz, label: tz }));

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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/55 p-4 backdrop-blur-[2px]">
      <div className="max-h-[92vh] w-full max-w-xl overflow-y-auto rounded-2xl border border-border/80 bg-background/95 shadow-2xl backdrop-blur-xl">
        <form onSubmit={(e) => void save(e)} className="p-6">
          <div className="mb-5 flex items-start gap-3">
            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl border border-primary/20 bg-primary/10 text-primary">
              <Clock className="h-5 w-5" aria-hidden />
            </div>
            <div className="min-w-0 flex-1">
              <h2 className="text-lg font-semibold tracking-tight">
                {mode === "create" ? t("schedulesPage.create_title") : t("schedulesPage.edit_title")}
              </h2>
              <p className="mt-0.5 text-xs text-muted-foreground">{t("schedulesPage.dialog_subtitle")}</p>
            </div>
            <button
              type="button"
              onClick={onClose}
              className="focus-ring rounded-lg p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
              aria-label={t("schedulesPage.cancel")}
            >
              <X className="h-5 w-5" />
            </button>
          </div>

          <div className="space-y-5">
            <div>
              <label className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-muted-foreground">
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

            <div className="rounded-2xl border border-border/60 bg-card/30 p-4">
              <label className="mb-2 block text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                {t("schedulesPage.schedule_label")}
              </label>
              <CronScheduleBuilder
                key={job?.job_id ?? "new"}
                initialValue={job?.cron_expression ?? cron}
                onChange={setCron}
                timezone={timezone}
              />
            </div>

            <div>
              <label className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                {t("schedulesPage.field_timezone")}
              </label>
              <AppSelect
                value={timezone}
                onValueChange={setTimezone}
                items={tzItems}
                triggerClassName="w-full max-w-none"
              />
            </div>

            <div>
              <div className="mb-2 flex items-center justify-between gap-2">
                <label className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  {t("schedulesPage.field_prompt")}
                  <span className="ml-1 text-destructive">*</span>
                </label>
                <span className="text-[0.714em] text-muted-foreground">{t("schedulesPage.prompt_templates")}</span>
              </div>
              <div className="mb-2 flex flex-wrap gap-1.5">
                {PROMPT_TEMPLATES.map((key) => (
                  <button
                    key={key}
                    type="button"
                    onClick={() => {
                      setPrompt(t(`schedulesPage.templates.${key}.prompt`));
                      if (!name.trim()) setName(t(`schedulesPage.templates.${key}.name`));
                    }}
                    className="focus-ring rounded-full border border-border/70 bg-muted/30 px-2.5 py-1 text-[0.714em] font-semibold text-muted-foreground transition hover:border-primary/30 hover:bg-primary/5 hover:text-foreground"
                  >
                    {t(`schedulesPage.templates.${key}.name`)}
                  </button>
                ))}
              </div>
              <textarea
                className={cn(inputClass, "min-h-[96px] resize-y")}
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                required
                rows={4}
              />
            </div>

            {profiles.length > 0 && (
              <div>
                <label className="mb-2 block text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  {t("schedulesPage.field_profile")}
                </label>
                <ProfileOptionGrid
                  profiles={profiles}
                  value={profile}
                  onChange={setProfile}
                  emptyLabel={t("schedulesPage.profile_none")}
                />
              </div>
            )}

            <div>
              <label className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                {t("schedulesPage.field_sql_project")}
              </label>
              <ProjectSelector
                userId={userId}
                token={token}
                profileSlug={profile}
                value={sqlProject || ""}
                onChange={setSqlProject}
                className="w-full"
              />
              <p className="mt-1 text-[0.786em] text-muted-foreground">
                {t("schedulesPage.field_sql_project_hint")}
              </p>
            </div>

            <fieldset className="space-y-1 rounded-2xl border border-border/60 bg-card/20 p-3">
              <legend className="px-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                {t("schedulesPage.session_legend")}
              </legend>
              <ComposerOptionRow
                label={t("schedulesPage.session_fixed")}
                description={t("schedulesPage.session_fixed_desc")}
                selected={sessionMode === "fixed"}
                onClick={() => setSessionMode("fixed")}
              />
              <ComposerOptionRow
                label={t("schedulesPage.session_new")}
                description={t("schedulesPage.session_new_desc")}
                selected={sessionMode === "new"}
                onClick={() => setSessionMode("new")}
              />
            </fieldset>
          </div>

          {error ? (
            <div className="mt-4 rounded-xl border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
              {error}
            </div>
          ) : null}

          <div className="mt-6 flex justify-end gap-2.5">
            <button
              type="button"
              onClick={onClose}
              className="focus-ring rounded-xl border border-border px-4 py-2 text-sm font-medium hover:bg-muted"
            >
              {t("schedulesPage.cancel")}
            </button>
            <button
              type="submit"
              disabled={saving}
              className="focus-ring rounded-xl bg-primary px-5 py-2 text-sm font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
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

export function ScheduleJobRuns({
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
    <div className="border-t border-border/50 bg-background/30 px-4 py-3 sm:px-5">
      <p className="mb-2 text-[0.714em] font-bold uppercase tracking-wide text-muted-foreground">
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
                className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-border/50 bg-card/40 px-3 py-2 text-xs"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className={`font-semibold capitalize ${statusClass}`}>{run.status}</span>
                    <span className="text-muted-foreground">{when}</span>
                  </div>
                  {run.error_message ? (
                    <p className="mt-0.5 line-clamp-2 text-destructive">{run.error_message}</p>
                  ) : null}
                  {run.assistant_preview && !run.error_message ? (
                    <p className="mt-0.5 line-clamp-2 text-muted-foreground">{run.assistant_preview}</p>
                  ) : null}
                </div>
                {chatId ? (
                  <Link
                    href={`/c/${chatId}`}
                    className="focus-ring shrink-0 rounded-lg border border-border px-2.5 py-1 text-xs font-semibold text-primary hover:bg-muted"
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
