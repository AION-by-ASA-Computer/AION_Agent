"use client";

import { Plug } from "lucide-react";

import { useT } from "@/lib/i18n/use-t";

const CHECKLIST_KEYS = [
  "integrationsPage.checklist_hub",
  "integrationsPage.checklist_per_user",
  "integrationsPage.checklist_env",
  "integrationsPage.checklist_login",
] as const;

export function IntegrationsEmptyState() {
  const t = useT();

  return (
    <div className="relative overflow-hidden rounded-3xl border border-dashed border-border/80 bg-gradient-to-b from-card/60 to-card/20 px-6 py-14 text-center shadow-sm backdrop-blur-sm">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_top,hsl(var(--primary)/0.08),transparent_55%)]" />
      <div className="relative mx-auto max-w-lg">
        <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl border border-primary/20 bg-primary/10 text-primary">
          <Plug className="h-7 w-7" aria-hidden />
        </div>
        <h2 className="text-lg font-semibold tracking-tight text-foreground">
          {t("integrationsPage.empty")}
        </h2>
        <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
          {t("integrationsPage.empty_hint")}
        </p>
        <ul className="mt-8 space-y-2 text-left text-xs leading-relaxed text-muted-foreground">
          {CHECKLIST_KEYS.map((key) => (
            <li
              key={key}
              className="rounded-xl border border-border/60 bg-background/50 px-3.5 py-2.5"
            >
              {t(key)}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
