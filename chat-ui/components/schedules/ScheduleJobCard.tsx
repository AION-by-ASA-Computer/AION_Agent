"use client";

import { useState } from "react";
import Link from "next/link";
import {
  ArrowUpRight,
  Bot,
  Calendar,
  Clock,
  MoreVertical,
  PauseCircle,
  Pencil,
  Play,
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
  const [menuOpen, setMenuOpen] = useState(false);
  const scheduleLabel = describeCronHuman(job.cron_expression, t);

  return (
    <article
      className={cn(
        "group relative flex flex-col h-fit overflow-hidden rounded-2xl border shadow-xs transition-all duration-200",
        "before:absolute before:inset-x-0 before:top-0 before:h-px before:bg-gradient-to-r before:from-transparent before:via-white/15 before:to-transparent",
        job.enabled
          ? "bg-card/90 dark:bg-zinc-900/60 border-emerald-500/25 dark:border-emerald-500/25 hover:border-emerald-500/40 hover:-translate-y-0.5 hover:shadow-md dark:hover:shadow-black/40"
          : "bg-card/90 dark:bg-zinc-900/60 border-amber-500/25 dark:border-amber-500/25 hover:border-amber-500/40 hover:-translate-y-0.5 hover:shadow-md dark:hover:shadow-black/40",
      )}
    >
      <div className="p-5 space-y-4">
        {/* Header con Icona, Nome in alto, Badge di Stato e Menu Azioni a 3 puntini */}
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
                    "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[11px] font-semibold border",
                    job.enabled
                      ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 border-emerald-500/25"
                      : "bg-amber-500/10 text-amber-800 dark:text-amber-300 border-amber-500/25",
                  )}
                >
                  <span
                    className={cn(
                      "h-1.5 w-1.5 rounded-full",
                      job.enabled ? "bg-emerald-500 animate-pulse" : "bg-amber-500",
                    )}
                  />
                  <span>
                    {job.enabled ? t("schedulesPage.badge_active") : t("schedulesPage.badge_paused")}
                  </span>
                </span>
              </div>
            </div>
          </div>

          {/* Menu Azioni a 3 puntini */}
          <div className="relative shrink-0">
            <button
              type="button"
              onClick={() => setMenuOpen((v) => !v)}
              className="p-1.5 rounded-xl border border-border/80 dark:border-white/10 bg-background/90 dark:bg-zinc-800/80 text-muted-foreground hover:text-foreground hover:bg-muted dark:hover:bg-zinc-700/80 transition cursor-pointer shadow-2xs"
              title="Opzioni automazione"
              aria-label="Opzioni automazione"
            >
              <MoreVertical className="h-4 w-4" />
            </button>

            {menuOpen ? (
              <>
                <div
                  className="fixed inset-0 z-40"
                  aria-hidden
                  onClick={() => setMenuOpen(false)}
                />
                <div className="absolute right-0 top-full z-50 mt-1.5 w-48 rounded-2xl border border-border/80 dark:border-white/15 bg-popover dark:bg-zinc-900 p-1.5 text-popover-foreground shadow-2xl animate-in fade-in-0 zoom-in-95 duration-150">
                  <button
                    type="button"
                    onClick={() => {
                      setMenuOpen(false);
                      onRunNow();
                    }}
                    className="flex w-full items-center gap-2.5 rounded-xl px-2.5 py-2 text-left text-xs font-medium text-foreground hover:bg-muted dark:hover:bg-zinc-800 transition cursor-pointer"
                  >
                    <Play className="h-3.5 w-3.5 text-muted-foreground" />
                    <span>{t("schedulesPage.run_now") || "Esegui ora"}</span>
                  </button>

                  <button
                    type="button"
                    onClick={() => {
                      setMenuOpen(false);
                      onToggle();
                    }}
                    className="flex w-full items-center gap-2.5 rounded-xl px-2.5 py-2 text-left text-xs font-medium text-foreground hover:bg-muted dark:hover:bg-zinc-800 transition cursor-pointer"
                  >
                    {job.enabled ? (
                      <>
                        <PauseCircle className="h-3.5 w-3.5 text-amber-500" />
                        <span>{t("schedulesPage.pause") || "Metti in pausa"}</span>
                      </>
                    ) : (
                      <>
                        <Play className="h-3.5 w-3.5 text-emerald-500 fill-current" />
                        <span>{t("schedulesPage.resume") || "Attiva automazione"}</span>
                      </>
                    )}
                  </button>

                  <button
                    type="button"
                    onClick={() => {
                      setMenuOpen(false);
                      onEdit();
                    }}
                    className="flex w-full items-center gap-2.5 rounded-xl px-2.5 py-2 text-left text-xs font-medium text-foreground hover:bg-muted dark:hover:bg-zinc-800 transition cursor-pointer"
                  >
                    <Pencil className="h-3.5 w-3.5 text-muted-foreground" />
                    <span>{t("schedulesPage.edit") || "Modifica"}</span>
                  </button>

                  <div className="my-1 h-px bg-border/60 dark:bg-white/10" />

                  <button
                    type="button"
                    onClick={() => {
                      setMenuOpen(false);
                      onDelete();
                    }}
                    className="flex w-full items-center gap-2.5 rounded-xl px-2.5 py-2 text-left text-xs font-medium text-destructive hover:bg-destructive/10 transition cursor-pointer"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                    <span>{t("schedulesPage.delete") || "Elimina"}</span>
                  </button>
                </div>
              </>
            ) : null}
          </div>
        </div>

        {/* Informazioni Automazione (Badge unificati con lo stesso colore e stile sobrio) */}
        <div className="flex flex-wrap items-center gap-2 pt-0.5 text-xs">
          {/* Frequenza di esecuzione */}
          <div className="inline-flex items-center gap-1.5 rounded-xl border border-border/80 dark:border-white/10 bg-muted/40 dark:bg-zinc-800/60 px-3 py-1.5 text-xs font-medium text-foreground dark:text-zinc-200 shadow-2xs">
            <Clock className="h-3.5 w-3.5 text-muted-foreground dark:text-zinc-400 shrink-0" />
            <span>{scheduleLabel}</span>
          </div>

          {/* Profilo utilizzato */}
          <div className="inline-flex items-center gap-1.5 rounded-xl border border-border/80 dark:border-white/10 bg-muted/40 dark:bg-zinc-800/60 px-3 py-1.5 text-xs font-medium text-foreground dark:text-zinc-200 shadow-2xs">
            <Bot className="h-3.5 w-3.5 text-muted-foreground dark:text-zinc-400 shrink-0" />
            <span className="font-semibold">{job.profile_slug}</span>
          </div>

          {/* Prossima esecuzione (se attiva) */}
          {job.next_run_at && job.enabled ? (
            <div className="inline-flex items-center gap-1.5 rounded-xl border border-border/80 dark:border-white/10 bg-muted/40 dark:bg-zinc-800/60 px-3 py-1.5 text-xs font-medium text-foreground dark:text-zinc-200 shadow-2xs">
              <Calendar className="h-3.5 w-3.5 text-muted-foreground dark:text-zinc-400 shrink-0" />
              <span className="text-muted-foreground">{t("schedulesPage.next")}:</span>
              <strong className="font-semibold text-foreground dark:text-zinc-100">
                {formatNextRunAt(job.next_run_at, job.timezone)}
              </strong>
            </div>
          ) : null}

          {/* Link alla sessione fissa (se presente) */}
          {job.session_mode === "fixed" && job.session_id ? (
            <Link
              href={`/c/${job.session_id}`}
              className="inline-flex items-center gap-1.5 rounded-xl border border-border/80 dark:border-white/10 bg-muted/40 dark:bg-zinc-800/60 px-3 py-1.5 text-xs font-semibold text-foreground dark:text-zinc-200 hover:text-sky-600 dark:hover:text-sky-400 hover:border-sky-500/30 transition shadow-2xs ml-auto"
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
