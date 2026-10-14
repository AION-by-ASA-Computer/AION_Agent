"use client";

import Link from "next/link";
import { useState } from "react";
import { ArrowRight, CheckCircle2, ChevronDown, Loader2, OctagonAlert, RefreshCw, TriangleAlert } from "lucide-react";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";
import { getLocale } from "@/lib/i18n/i18n-store";
import { getStoredUserId } from "@/lib/auth/storage";
import { useDashboardData } from "@/components/dashboard/useDashboardData";
import { deriveDashboard, type Attention } from "@/components/dashboard/derive";
import { AgentMap } from "@/components/dashboard/AgentMap";
import { CommandBar } from "@/components/dashboard/CommandBar";
import { ActivityPanel } from "@/components/dashboard/ActivityPanel";

function greetingKey(d: Date): string {
  const h = d.getHours();
  if (h < 12) return "admin_dashboard.greeting_morning";
  if (h < 18) return "admin_dashboard.greeting_afternoon";
  return "admin_dashboard.greeting_evening";
}

const ATTENTION_VISIBLE = 4;

function AttentionRow({ a, onPoint, t }: { a: Attention; onPoint: (node: string | null) => void; t: ReturnType<typeof useT> }) {
  const Icon = a.severity === "error" ? OctagonAlert : TriangleAlert;
  return (
    <Link
      href={a.href}
      onMouseEnter={() => onPoint(a.node ?? null)}
      onFocus={() => onPoint(a.node ?? null)}
      onBlur={() => onPoint(null)}
      className="focus-ring group flex items-center gap-3.5 px-4 py-3 transition-colors hover:bg-secondary/50 focus-visible:bg-secondary/50 sm:px-5"
    >
      <Icon className={cn("h-4 w-4 shrink-0", a.severity === "error" ? "text-destructive" : "text-warning")} aria-hidden />
      <span className="sr-only">{t(`admin_dashboard.attention.severity_${a.severity}`)}</span>
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-medium">{a.title}</div>
        {a.detail && (
          <div className="truncate text-xs text-muted-foreground" title={a.detail}>
            {a.detail}
          </div>
        )}
      </div>
      <span className="inline-flex shrink-0 items-center gap-1 text-xs font-medium text-muted-foreground group-hover:text-foreground">
        <span className="hidden xl:inline">{a.action}</span>
        <ArrowRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5" aria-hidden />
      </span>
    </Link>
  );
}

function AttentionPanel({
  items,
  checking,
  onPoint,
  t,
}: {
  items: Attention[];
  checking: boolean;
  onPoint: (node: string | null) => void;
  t: ReturnType<typeof useT>;
}) {
  const [expanded, setExpanded] = useState(false);
  if (items.length === 0) {
    return (
      <div className="flex items-center gap-3 rounded-2xl border border-border/60 bg-card/40 px-4 py-3.5 text-sm" role="status">
        {checking ? (
          <>
            <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" aria-hidden />
            <span className="text-muted-foreground">{t("admin_dashboard.attention.checking")}</span>
          </>
        ) : (
          <>
            <CheckCircle2 className="h-4 w-4 text-success" aria-hidden />
            <span className="font-medium">{t("admin_dashboard.attention.all_clear")}</span>
            <span className="hidden text-muted-foreground sm:inline">{t("admin_dashboard.attention.all_clear_detail")}</span>
          </>
        )}
      </div>
    );
  }

  const errors = items.filter((a) => a.severity === "error").length;
  const warnings = items.length - errors;
  const rules = new Intl.PluralRules(getLocale());
  const plural = (key: string, count: number) =>
    t(`admin_dashboard.attention.${key}_${rules.select(count) === "one" ? "one" : "other"}`, { count });
  const summary = [errors > 0 && plural("blocking", errors), warnings > 0 && plural("to_check", warnings)]
    .filter(Boolean)
    .join(" · ");

  // The most urgent problem gets the stage; the rest wait in a compact queue beside it.
  const [lead, ...rest] = items;
  const queue = expanded ? rest : rest.slice(0, ATTENTION_VISIBLE);
  const hidden = rest.length - queue.length;
  const critical = lead.severity === "error";
  const LeadIcon = critical ? OctagonAlert : TriangleAlert;

  return (
    <section aria-labelledby="attention-title">
      <div className="mb-3 flex items-baseline gap-3 px-1">
        <h2 id="attention-title" className="text-lg font-semibold tracking-[-0.015em]">
          {t("admin_dashboard.attention.title")}
        </h2>
        <span className="text-sm tabular-nums text-muted-foreground">{summary}</span>
        {checking && (
          <Loader2 className="ml-auto h-4 w-4 shrink-0 self-center animate-spin text-muted-foreground" aria-label={t("admin_dashboard.status.checking")} />
        )}
      </div>

      <div className={cn("grid gap-3", rest.length > 0 && "lg:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]")}>
        <Link
          href={lead.href}
          onMouseEnter={() => onPoint(lead.node ?? null)}
          onMouseLeave={() => onPoint(null)}
          onFocus={() => onPoint(lead.node ?? null)}
          onBlur={() => onPoint(null)}
          className={cn(
            "focus-ring group relative flex min-h-[13rem] flex-col overflow-hidden rounded-3xl p-5 transition-colors sm:p-6",
            critical
              ? "bg-destructive/[0.09] hover:bg-destructive/[0.13] dark:bg-destructive/[0.12] dark:hover:bg-destructive/[0.17]"
              : "bg-warning/[0.09] hover:bg-warning/[0.13] dark:bg-warning/[0.1] dark:hover:bg-warning/[0.15]",
          )}
        >
          <LeadIcon
            className={cn(
              "pointer-events-none absolute -right-6 -top-6 h-40 w-40 opacity-[0.07] transition-transform duration-500 group-hover:rotate-6",
              critical ? "text-destructive" : "text-warning",
            )}
            strokeWidth={1.25}
            aria-hidden
          />
          <div className="flex items-center gap-2">
            <span
              className={cn(
                "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold",
                critical ? "bg-destructive text-destructive-foreground" : "bg-warning text-white dark:text-black",
              )}
            >
              <LeadIcon className="h-3.5 w-3.5" aria-hidden />
              {t(`admin_dashboard.attention.severity_${lead.severity}`)}
            </span>
            {rest.length > 0 && (
              <span className="text-xs font-medium text-muted-foreground">{t("admin_dashboard.attention.start_here")}</span>
            )}
          </div>
          <h3 className="mt-4 max-w-[32ch] text-balance text-xl font-semibold leading-snug tracking-[-0.015em] sm:text-2xl">
            {lead.title}
          </h3>
          {lead.detail && (
            <p className="mt-1.5 line-clamp-2 max-w-[60ch] break-words text-sm text-muted-foreground">{lead.detail}</p>
          )}
          <span className="mt-auto pt-6">
            <span
              className={cn(
                "inline-flex items-center gap-2 rounded-xl px-4 py-2.5 text-sm font-semibold shadow-sm transition-transform group-hover:translate-x-0.5",
                critical ? "bg-destructive text-destructive-foreground" : "bg-foreground text-background",
              )}
            >
              {lead.action}
              <ArrowRight className="h-4 w-4" aria-hidden />
            </span>
          </span>
        </Link>

        {rest.length > 0 && (
          <div className="flex flex-col overflow-hidden rounded-3xl border border-border/60 bg-card/40">
            <ul className="flex-1 divide-y divide-border/50" onMouseLeave={() => onPoint(null)}>
              {queue.map((a) => (
                <li key={a.id}>
                  <AttentionRow a={a} onPoint={onPoint} t={t} />
                </li>
              ))}
            </ul>
            {rest.length > ATTENTION_VISIBLE && (
              <button
                type="button"
                onClick={() => setExpanded((e) => !e)}
                aria-expanded={expanded}
                className="focus-ring flex w-full items-center justify-center gap-1.5 border-t border-border/50 px-5 py-2.5 text-xs font-medium text-muted-foreground transition-colors hover:bg-secondary/50 hover:text-foreground"
              >
                {expanded
                  ? t("admin_dashboard.attention.show_less")
                  : t("admin_dashboard.attention.show_more", { count: hidden })}
                <ChevronDown className={cn("h-3.5 w-3.5 transition-transform", expanded && "rotate-180")} aria-hidden />
              </button>
            )}
          </div>
        )}
      </div>
    </section>
  );
}

export default function DashboardPage() {
  const t = useT();
  const locale = getLocale();
  const data = useDashboardData();
  // Rendered client-side only (behind AdminAuthGate), so reading storage here is safe.
  const [userId] = useState(() => (typeof window !== "undefined" ? getStoredUserId() : null));
  const [now] = useState(() => new Date());
  const [pointed, setPointed] = useState<string | null>(null);

  const view = deriveDashboard(data, t, locale);
  const fmt = (v: number | undefined) => (v === undefined ? "—" : new Intl.NumberFormat(locale).format(v));
  const time = data.lastUpdated
    ? new Intl.DateTimeFormat(locale, { hour: "2-digit", minute: "2-digit" }).format(data.lastUpdated)
    : null;

  return (
    <div className="mx-auto flex max-w-[84rem] flex-col gap-6">
      <header className="flex flex-col gap-4 pt-2 sm:flex-row sm:items-end">
        <div className="min-w-0 flex-1">
          <h1 className="text-balance text-2xl font-semibold tracking-[-0.02em] sm:text-[28px]">
            {t(greetingKey(now), { name: userId ?? "" }).replace(/,\s*$/, "")}
          </h1>
          <p className="mt-1 text-sm text-muted-foreground tabular-nums">
            {t("admin_dashboard.summary", {
              profiles: fmt(view.summary.profiles),
              mcp: fmt(view.summary.mcp),
              users: fmt(view.summary.users),
            })}
          </p>
        </div>
        <div className="flex items-center gap-3">
          {time && (
            <span className="text-xs text-muted-foreground tabular-nums">{t("admin_dashboard.updated_at", { time })}</span>
          )}
          <button
            type="button"
            onClick={data.refresh}
            disabled={data.refreshing}
            className="focus-ring inline-flex h-9 items-center gap-2 rounded-xl border border-border bg-card px-3 text-sm font-medium transition-colors hover:bg-secondary disabled:cursor-progress disabled:opacity-70"
          >
            <RefreshCw className={cn("h-3.5 w-3.5", data.refreshing && "animate-spin")} aria-hidden />
            {t("admin_dashboard.refresh")}
          </button>
        </div>
      </header>

      <CommandBar />

      <AttentionPanel items={view.attention} checking={view.checking} onPoint={setPointed} t={t} />

      <AgentMap
        columns={view.columns}
        title={t("admin_dashboard.map.title")}
        subtitle={t("admin_dashboard.map.subtitle")}
        legend={{ uses: t("admin_dashboard.map.legend_uses"), contains: t("admin_dashboard.map.legend_contains") }}
        highlight={pointed}
      />

      <ActivityPanel metrics={data.metrics} feedback={view.feedback} locale={locale} t={t} />
    </div>
  );
}
