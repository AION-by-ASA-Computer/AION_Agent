"use client";

import { AlertTriangle, Clock, Bot, Database, Loader2, Trash2, X } from "lucide-react";
import { describeCronHuman } from "@/components/schedules/CronScheduleBuilder";
import type { ScheduledJobRow } from "@/lib/api/aion";
import { useT } from "@/lib/i18n/use-t";

export function DeleteScheduleDialog({
  job,
  onClose,
  onConfirm,
  deleting = false,
}: {
  job: ScheduledJobRow;
  onClose: () => void;
  onConfirm: () => Promise<void> | void;
  deleting?: boolean;
}) {
  const t = useT();
  const scheduleLabel = describeCronHuman(job.cron_expression, t);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 sm:p-6 backdrop-blur-sm animate-in fade-in duration-200"
      role="presentation"
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg rounded-3xl border border-border bg-card text-card-foreground shadow-2xl overflow-hidden animate-in zoom-in-95 duration-200"
        role="dialog"
        aria-modal="true"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header Modale */}
        <div className="flex items-center justify-between border-b border-border p-5 sm:p-6 bg-muted/20 shrink-0">
          <div className="flex items-center gap-3.5 min-w-0 pr-4">
            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl border border-destructive/30 bg-destructive/10 text-destructive shadow-xs">
              <Trash2 className="h-5 w-5" aria-hidden />
            </div>
            <div className="min-w-0 flex-1">
              <h2 className="text-lg sm:text-xl font-bold tracking-tight text-foreground truncate">
                {t("schedulesPage.delete_dialog_title")}
              </h2>
              <p className="mt-0.5 text-xs text-muted-foreground">
                {t("schedulesPage.delete_dialog_subtitle")}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-xl p-2 text-muted-foreground hover:bg-muted hover:text-foreground transition cursor-pointer shrink-0"
            aria-label={t("schedulesPage.cancel")}
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Corpo Modale */}
        <div className="p-5 sm:p-6 space-y-4 bg-background">
          {/* Banner di avviso irreversibilità */}
          <div className="rounded-2xl border border-destructive/25 bg-destructive/10 p-4 text-xs sm:text-sm text-destructive dark:text-red-300 leading-relaxed space-y-1.5">
            <div className="flex items-center gap-2 font-bold text-destructive">
              <AlertTriangle className="h-4 w-4 shrink-0" />
              <span>{t("schedulesPage.delete_dialog_warning")}</span>
            </div>
            <p className="text-muted-foreground text-xs leading-relaxed">
              {t("schedulesPage.delete_dialog_desc")}{" "}
              <strong className="text-foreground font-semibold font-mono">&ldquo;{job.name}&rdquo;</strong>?{" "}
              {t("schedulesPage.delete_dialog_desc_end")}
            </p>
          </div>

          {/* Dettagli dell'automazione */}
          <div className="rounded-2xl border border-border/70 bg-card p-4 space-y-2.5 shadow-2xs text-xs">
            <div className="flex items-center justify-between gap-2 border-b border-border/40 pb-2">
              <span className="text-muted-foreground font-medium">Nome automazione:</span>
              <span className="font-bold text-foreground truncate max-w-xs">{job.name}</span>
            </div>
            <div className="flex items-center justify-between gap-2">
              <span className="inline-flex items-center gap-1.5 text-muted-foreground font-medium">
                <Clock className="h-3.5 w-3.5 text-primary opacity-80" />
                <span>Pianificazione:</span>
              </span>
              <span className="font-semibold text-foreground">{scheduleLabel}</span>
            </div>
            <div className="flex items-center justify-between gap-2">
              <span className="inline-flex items-center gap-1.5 text-muted-foreground font-medium">
                <Bot className="h-3.5 w-3.5 text-primary opacity-80" />
                <span>Profilo agente:</span>
              </span>
              <span className="font-semibold text-foreground">{job.profile_slug}</span>
            </div>
            {job.sql_query_project && (
              <div className="flex items-center justify-between gap-2 pt-1 border-t border-border/40">
                <span className="inline-flex items-center gap-1.5 text-muted-foreground font-medium">
                  <Database className="h-3.5 w-3.5 text-primary opacity-80" />
                  <span>Progetto Memoria:</span>
                </span>
                <span className="font-semibold text-foreground">{job.sql_query_project}</span>
              </div>
            )}
          </div>
        </div>

        {/* Footer con pulsanti di azione */}
        <div className="border-t border-border p-4 sm:px-6 bg-muted/20 flex items-center justify-end gap-3 shrink-0">
          <button
            type="button"
            onClick={onClose}
            disabled={deleting}
            className="rounded-xl border border-border px-4 py-2 text-xs font-semibold text-foreground hover:bg-muted transition cursor-pointer disabled:opacity-50"
          >
            {t("schedulesPage.cancel")}
          </button>
          <button
            type="button"
            onClick={() => void onConfirm()}
            disabled={deleting}
            className="rounded-xl bg-destructive px-5 py-2 text-xs font-semibold text-destructive-foreground shadow-sm hover:bg-destructive/90 transition cursor-pointer flex items-center gap-2 disabled:opacity-50"
          >
            {deleting ? (
              <>
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                <span>Eliminazione…</span>
              </>
            ) : (
              <>
                <Trash2 className="h-3.5 w-3.5" />
                <span>{t("schedulesPage.delete_dialog_btn")}</span>
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
