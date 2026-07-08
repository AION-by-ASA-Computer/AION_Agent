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
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_top,hsl(var(--primary)/0.08),transparent_55%)]" />
      <div className="relative mx-auto max-w-lg">
        <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl border border-primary/20 bg-primary/10 text-primary">
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
                  "group rounded-2xl border border-border/70 bg-background/50 px-4 py-3 text-left transition",
                  "hover:border-primary/30 hover:bg-primary/5 hover:shadow-sm",
                )}
              >
                <div className="flex items-start gap-3">
                  <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-muted/80 text-muted-foreground transition group-hover:bg-primary/10 group-hover:text-primary">
                    <Icon className="h-4 w-4" aria-hidden />
                  </span>
                  <div className="min-w-0">
                    <div className="text-sm font-semibold text-foreground">
                      {t(`schedulesPage.templates.${key}.name`)}
                    </div>
                    <p className="mt-0.5 line-clamp-2 text-[11px] leading-snug text-muted-foreground">
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
          className="focus-ring mt-8 rounded-xl bg-primary px-5 py-2.5 text-sm font-semibold text-primary-foreground shadow-sm transition hover:bg-primary/90"
        >
          {t("schedulesPage.new")}
        </button>
      </div>
    </div>
  );
}
