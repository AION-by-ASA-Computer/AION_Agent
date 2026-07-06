"use client";

import Link from "next/link";
import { ArrowUpRight, Clock, Play, Power, PowerOff, Trash2 } from "lucide-react";

import { describeCronHuman } from "@/components/schedules/CronScheduleBuilder";
import type { ScheduledJobRow } from "@/lib/api/aion";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";

export function ScheduleJobCard({
  job,
  onEdit,
  onToggle,
  onRunNow,
  onDelete,
  runsSlot,
}: {
  job: ScheduledJobRow;
  onEdit: () => void;
  onToggle: () => void;
  onRunNow: () => void;
  onDelete: () => void;
  runsSlot?: React.ReactNode;
}) {
  const t = useT();
  const scheduleLabel = describeCronHuman(job.cron_expression, t);

  const statusPill = job.enabled
    ? "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300"
    : "bg-amber-500/15 text-amber-800 dark:text-amber-300";

  const lastRunClass =
    job.last_run?.status === "success"
      ? "text-emerald-700 dark:text-emerald-400"
      : job.last_run?.status === "error"
        ? "text-destructive"
        : "text-muted-foreground";

  return (
    <article
      className={cn(
        "overflow-hidden rounded-2xl border shadow-sm backdrop-blur-sm transition hover:shadow-md",
        job.enabled
          ? "border-emerald-500/20 bg-gradient-to-br from-emerald-500/6 to-card/40"
          : "border-border/70 bg-card/35",
      )}
    >
      <div className="flex flex-wrap items-start justify-between gap-4 p-4 sm:p-5">
        <div className="flex min-w-0 flex-1 items-start gap-3.5">
          <div
            className={cn(
              "flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl border",
              job.enabled
                ? "border-emerald-500/20 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
                : "border-border/60 bg-muted/50 text-muted-foreground",
            )}
          >
            <Clock className="h-5 w-5" aria-hidden />
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-base font-semibold text-foreground">{job.name}</h3>
              <span className={cn("rounded-full px-2 py-0.5 text-[10px] font-bold uppercase", statusPill)}>
                {job.enabled ? t("schedulesPage.badge_active") : t("schedulesPage.badge_paused")}
              </span>
            </div>
            <p className="mt-0.5 text-sm text-muted-foreground">{scheduleLabel}</p>
            <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
              <span className="rounded-md bg-muted/50 px-2 py-0.5 font-medium">{job.profile_slug}</span>
              {job.timezone ? <span>{job.timezone}</span> : null}
              {job.next_run_at && job.enabled ? (
                <span>
                  {t("schedulesPage.next")}: {new Date(job.next_run_at).toLocaleString()}
                </span>
              ) : null}
            </div>
            {job.last_run?.status ? (
              <p className={cn("mt-2 text-xs font-medium", lastRunClass)}>
                {t("schedulesPage.last_run")}: {job.last_run.status}
              </p>
            ) : null}
            <p className="mt-2 line-clamp-2 text-xs leading-relaxed text-muted-foreground">{job.prompt}</p>
            {job.session_mode === "fixed" && job.session_id ? (
              <Link
                href={`/c/${job.session_id}`}
                className="focus-ring mt-2 inline-flex items-center gap-1 text-xs font-semibold text-primary hover:underline"
              >
                {t("schedulesPage.open_session")}
                <ArrowUpRight className="h-3 w-3" aria-hidden />
              </Link>
            ) : null}
          </div>
        </div>

        <div className="flex shrink-0 flex-wrap items-center gap-1.5">
          <button
            type="button"
            onClick={onRunNow}
            title={t("schedulesPage.run_now")}
            className="focus-ring rounded-xl border border-border/70 bg-background/60 p-2.5 text-foreground transition hover:bg-muted"
          >
            <Play className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={onToggle}
            title={job.enabled ? t("schedulesPage.pause") : t("schedulesPage.resume")}
            className="focus-ring rounded-xl border border-border/70 bg-background/60 p-2.5 transition hover:bg-muted"
          >
            {job.enabled ? <PowerOff className="h-4 w-4" /> : <Power className="h-4 w-4" />}
          </button>
          <button
            type="button"
            onClick={onEdit}
            className="focus-ring rounded-xl border border-border/70 bg-background/60 px-3.5 py-2 text-xs font-semibold transition hover:bg-muted"
          >
            {t("schedulesPage.edit")}
          </button>
          <button
            type="button"
            onClick={onDelete}
            className="focus-ring rounded-xl border border-destructive/25 bg-destructive/5 p-2.5 text-destructive transition hover:bg-destructive/10"
            title={t("schedulesPage.delete")}
          >
            <Trash2 className="h-4 w-4" />
          </button>
        </div>
      </div>
      {runsSlot}
    </article>
  );
}
