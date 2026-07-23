"use client";

import { PauseCircle, PlayCircle, Zap } from "lucide-react";

import { useT } from "@/lib/i18n/use-t";

export function ScheduleStatsBar({
  total,
  active,
  paused,
}: {
  total: number;
  active: number;
  paused: number;
}) {
  const t = useT();
  if (total === 0) return null;

  const items = [
    {
      label: t("schedulesPage.stats.total"),
      value: total,
      icon: Zap,
      className: "border-border/70 bg-card/40 text-foreground",
    },
    {
      label: t("schedulesPage.stats.active"),
      value: active,
      icon: PlayCircle,
      className: "border-emerald-500/25 bg-emerald-500/8 text-emerald-700 dark:text-emerald-300",
    },
    {
      label: t("schedulesPage.stats.paused"),
      value: paused,
      icon: PauseCircle,
      className: "border-amber-500/25 bg-amber-500/8 text-amber-800 dark:text-amber-300",
    },
  ];

  return (
    <div className="mb-6 grid grid-cols-3 gap-2 sm:gap-3">
      {items.map(({ label, value, icon: Icon, className }) => (
        <div
          key={label}
          className={`rounded-2xl border px-3 py-3 shadow-sm backdrop-blur-sm ${className}`}
        >
          <div className="flex items-center gap-2">
            <Icon className="h-4 w-4 shrink-0 opacity-80" aria-hidden />
            <span className="text-[0.714em] font-semibold uppercase tracking-wide opacity-80">
              {label}
            </span>
          </div>
          <div className="mt-1 text-2xl font-bold tabular-nums">{value}</div>
        </div>
      ))}
    </div>
  );
}
