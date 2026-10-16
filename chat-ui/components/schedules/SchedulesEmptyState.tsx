"use client";

import { CalendarClock, Inbox, Newspaper, Sparkles } from "lucide-react";

import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";

const TEMPLATE_ICONS = [Newspaper, Inbox, CalendarClock, Sparkles] as const;

export function SchedulesEmptyState({
  onCreate,
  onUseTemplate,
}: {
  onCreate: () => void;
  onUseTemplate: (prompt: string, name: string) => void;
}) {
  const t = useT();

  const templates = [
    { key: "briefing", icon: 0 },
    { key: "inbox", icon: 1 },
    { key: "weekly", icon: 2 },
    { key: "research", icon: 3 },
  ] as const;

  return (
    <div className="relative overflow-hidden rounded-3xl border border-dashed border-border/80 bg-gradient-to-b from-card/60 to-card/20 px-6 py-14 text-center shadow-sm backdrop-blur-sm">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_top,rgba(120,120,120,0.06),transparent_55%)]" />
      <div className="relative mx-auto max-w-lg">
        <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl border border-border/80 dark:border-white/10 bg-muted/60 dark:bg-zinc-800 text-foreground dark:text-zinc-200 shadow-sm">
          <CalendarClock className="h-7 w-7" aria-hidden />
        </div>
        <h2 className="text-lg font-semibold tracking-tight text-foreground">
          {t("schedulesPage.empty")}
        </h2>
        <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
          {t("schedulesPage.empty_hint")}
        </p>

        <div className="mt-8 grid grid-cols-1 gap-2 sm:grid-cols-2">
          {templates.map(({ key, icon }) => {
            const Icon = TEMPLATE_ICONS[icon];
            return (
              <button
                key={key}
                type="button"
                onClick={() =>
                  onUseTemplate(
                    t(`schedulesPage.templates.${key}.prompt`),
                    t(`schedulesPage.templates.${key}.name`),
                  )
                }
                className={cn(
                  "group rounded-2xl border border-border/70 dark:border-white/10 bg-background/50 dark:bg-zinc-900/50 px-4 py-3 text-left transition",
                  "hover:border-border dark:hover:border-white/20 hover:bg-muted/40 dark:hover:bg-zinc-800/50 hover:shadow-xs cursor-pointer",
                )}
              >
                <div className="flex items-start gap-3">
                  <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-muted/80 dark:bg-zinc-800 text-muted-foreground transition group-hover:bg-muted dark:group-hover:bg-zinc-700 group-hover:text-foreground">
                    <Icon className="h-4 w-4" aria-hidden />
                  </span>
                  <div className="min-w-0">
                    <div className="text-sm font-semibold text-foreground">
                      {t(`schedulesPage.templates.${key}.name`)}
                    </div>
                    <p className="mt-0.5 line-clamp-2 text-[0.786em] leading-snug text-muted-foreground">
                      {t(`schedulesPage.templates.${key}.desc`)}
                    </p>
                  </div>
                </div>
              </button>
            );
          })}
        </div>

        <button
          type="button"
          onClick={onCreate}
          className="focus-ring mt-8 rounded-xl bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900 px-5 py-2.5 text-sm font-semibold shadow-sm transition hover:bg-zinc-800 dark:hover:bg-white cursor-pointer"
        >
          {t("schedulesPage.new")}
        </button>
      </div>
    </div>
  );
}
