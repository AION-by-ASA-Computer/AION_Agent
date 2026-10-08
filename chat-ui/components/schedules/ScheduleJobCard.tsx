"use client";

import Link from "next/link";
import {
  ArrowUpRight,
  Bot,
  Calendar,
  CheckCircle2,
  Clock,
  PauseCircle,
  Play,
  Power,
  PowerOff,
  Trash2,
} from "lucide-react";

import { describeCronHuman } from "@/components/schedules/CronScheduleBuilder";
import type { ScheduledJobRow } from "@/lib/api/aion";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";

/**
 * Format a UTC ISO string (next_run_at from the backend) in the job's own
 * timezone so the displayed time matches the cron schedule the user set.
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
    return d.toLocaleString();
  }
}

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

  return (
    <article
      className={cn(
        "group relative flex flex-col h-fit overflow-hidden rounded-2xl border shadow-sm transition-all duration-200 hover:shadow-md",
        job.enabled
          ? "border-emerald-500/25 bg-gradient-to-b from-emerald-500/[0.04] to-card hover:border-emerald-500/40"
          : "border-amber-500/25 bg-gradient-to-b from-amber-500/[0.03] to-card hover:border-amber-500/40",
      )}
    >
      <div className="p-5 space-y-4">
        {/* Header con Icona, Nome in alto, Badge di Stato e Bottoni Azione in alto */}
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-3 min-w-0">
            {/* Icona colorata in base allo stato */}
            <div
              className={cn(
                "flex h-11 w-11 shrink-0 items-center justify-center overflow-hidden rounded-xl border transition-colors shadow-2xs",
                job.enabled
                  ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
                  : "border-amber-500/30 bg-amber-500/10 text-amber-600 dark:text-amber-400",
              )}
            >
              <Clock className="h-5 w-5" aria-hidden />
            </div>

            {/* Nome in alto con il badge di stato */}
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="font-bold text-foreground text-sm sm:text-base leading-tight truncate">
                  {job.name}
                </h3>
                <span
                  className={cn(
                    "inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[11px] font-semibold border",
                    job.enabled
                      ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 border-emerald-500/20"
                      : "bg-amber-500/10 text-amber-800 dark:text-amber-300 border-amber-500/20",
                  )}
                >
                  {job.enabled ? (
                    <>
                      <CheckCircle2 className="h-3 w-3" />
                      <span>{t("schedulesPage.badge_active")}</span>
                    </>
                  ) : (
                    <>
                      <PauseCircle className="h-3 w-3" />
                      <span>{t("schedulesPage.badge_paused")}</span>
                    </>
                  )}
                </span>
              </div>
            </div>
          </div>

          {/* Bottoni Azione in alto a destra */}
          <div className="flex shrink-0 items-center gap-1.5">
            <button
              type="button"
              onClick={onRunNow}
              title={t("schedulesPage.run_now")}
              className="p-1.5 rounded-xl border border-border/70 bg-background/80 text-foreground hover:bg-muted hover:text-primary transition cursor-pointer shadow-2xs"
            >
              <Play className="h-3.5 w-3.5" />
            </button>
            <button
              type="button"
              onClick={onToggle}
              title={job.enabled ? t("schedulesPage.pause") : t("schedulesPage.resume")}
              className={cn(
                "p-1.5 rounded-xl border transition cursor-pointer shadow-2xs",
                job.enabled
                  ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-600 hover:bg-emerald-500/20"
                  : "border-border/70 bg-background/80 text-muted-foreground hover:bg-muted hover:text-foreground",
              )}
            >
              {job.enabled ? <PowerOff className="h-3.5 w-3.5" /> : <Power className="h-3.5 w-3.5" />}
            </button>
            <button
              type="button"
              onClick={onEdit}
              className="px-2.5 py-1.5 rounded-xl border border-border/70 bg-background/80 text-xs font-semibold text-foreground hover:bg-muted transition cursor-pointer shadow-2xs"
            >
              {t("schedulesPage.edit")}
            </button>
            <button
              type="button"
              onClick={onDelete}
              className="p-1.5 rounded-xl border border-destructive/20 bg-destructive/5 text-destructive hover:bg-destructive/15 transition cursor-pointer shadow-2xs"
              title={t("schedulesPage.delete")}
            >
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>

        {/* Sotto: ogni quanto viene eseguito e vicino il profilo utilizzato */}
        <div className="flex flex-wrap items-center gap-2 pt-1 text-xs">
          {/* Frequenza */}
          <div className="inline-flex items-center gap-1.5 rounded-lg border border-border/60 bg-muted/40 px-2.5 py-1 font-medium text-foreground">
            <Clock className="h-3.5 w-3.5 text-primary opacity-80" />
            <span>{scheduleLabel}</span>
          </div>

          {/* Profilo utilizzato */}
          <div className="inline-flex items-center gap-1.5 rounded-lg border border-border/60 bg-muted/40 px-2.5 py-1 font-medium text-foreground">
            <Bot className="h-3.5 w-3.5 text-primary opacity-80" />
            <span className="font-semibold">{job.profile_slug}</span>
          </div>

          {/* Prossima esecuzione (se attiva) */}
          {job.next_run_at && job.enabled ? (
            <div className="inline-flex items-center gap-1.5 rounded-lg border border-border/50 bg-background/60 px-2.5 py-1 text-[11px] text-muted-foreground">
              <Calendar className="h-3 w-3 opacity-70" />
              <span>{t("schedulesPage.next")}:</span>
              <strong className="text-foreground font-semibold">{formatNextRunAt(job.next_run_at, job.timezone)}</strong>
            </div>
          ) : null}

          {/* Link alla sessione fissa (se presente) */}
          {job.session_mode === "fixed" && job.session_id ? (
            <Link
              href={`/c/${job.session_id}`}
              className="inline-flex items-center gap-1 rounded-lg border border-border/50 bg-background/60 px-2.5 py-1 text-[11px] font-semibold text-primary hover:bg-muted transition ml-auto"
            >
              <span>{t("schedulesPage.open_session")}</span>
              <ArrowUpRight className="h-3 w-3" aria-hidden />
            </Link>
          ) : null}
        </div>
      </div>

      {/* Sezione Esecuzioni Recenti */}
      {runsSlot}
    </article>
  );
}
