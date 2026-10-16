"use client";

import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, Loader2, Wrench } from "lucide-react";
import { apiFetch } from "@/lib/api/headers";
import { apiBase } from "@/lib/api";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";
import { getLocale } from "@/lib/i18n/i18n-store";

export type McpIntegrityIssue = {
  code: string;
  severity: "error" | "warning" | "info";
  server_slug?: string;
  from_slug?: string;
  message: string;
  repair?: string;
  count?: number;
};

type IntegrityReport = {
  ok: boolean;
  issue_count: number;
  issues: McpIntegrityIssue[];
};

type Props = {
  onRepaired?: () => void;
  className?: string;
};

export function McpIntegrityBanner({ onRepaired, className }: Props) {
  const t = useT();
  const [report, setReport] = useState<IntegrityReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [repairing, setRepairing] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await apiFetch(`${apiBase()}/admin/mcp/integrity`);
      if (res.ok) {
        setReport(await res.json());
      }
    } catch {
      setReport(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const repairAll = async () => {
    setRepairing(true);
    try {
      const res = await apiFetch(`${apiBase()}/admin/mcp/integrity/repair-all`, { method: "POST" });
      const data = res.ok ? await res.json() : null;
      await load();
      onRepaired?.();
      if (data?.failed?.length) {
        console.warn("MCP integrity repair partial failures", data.failed);
      }
    } finally {
      setRepairing(false);
    }
  };

  // Healthy is the default state: say nothing until there is something to fix.
  if (loading || !report || report.issue_count === 0) return null;

  const rules = new Intl.PluralRules(getLocale());
  const plural = (key: string, count: number) =>
    t(`admin_hub.integrity.${key}_${rules.select(count) === "one" ? "one" : "other"}`, { count });
  const errors = report.issues.filter((i) => i.severity === "error").length;
  const warnings = report.issues.filter((i) => i.severity === "warning").length;
  const summary = [errors > 0 && plural("errors", errors), warnings > 0 && plural("warnings", warnings)]
    .filter(Boolean)
    .join(" · ");

  return (
    <section
      aria-labelledby="mcp-integrity-title"
      className={cn("flex flex-col gap-3 rounded-3xl bg-warning/[0.09] p-4 sm:p-5 dark:bg-warning/[0.1]", className)}
    >
      <div className="flex flex-wrap items-start gap-3">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" aria-hidden />
        <div className="min-w-0 flex-1">
          <h2 id="mcp-integrity-title" className="text-sm font-semibold">
            {t("admin_hub.integrity.title")}
            {summary && <span className="ml-2 font-normal tabular-nums text-muted-foreground">{summary}</span>}
          </h2>
          <p className="mt-0.5 text-sm text-muted-foreground">{t("admin_hub.integrity.body")}</p>
        </div>
        <button
          type="button"
          onClick={() => void repairAll()}
          disabled={repairing}
          className="focus-ring inline-flex h-9 items-center gap-2 rounded-xl border border-border bg-card px-3 text-sm font-medium transition-colors hover:bg-secondary disabled:opacity-60"
        >
          {repairing ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <Wrench className="h-3.5 w-3.5" aria-hidden />}
          {t("admin_hub.integrity.repair")}
        </button>
      </div>
      <ul className="flex max-h-36 flex-col gap-1.5 overflow-y-auto pl-7 text-sm">
        {report.issues.slice(0, 8).map((issue, idx) => (
          <li key={`${issue.code}-${issue.server_slug}-${idx}`}>
            {issue.server_slug && <span className="mr-2 font-mono text-[13px] font-medium">{issue.server_slug}</span>}
            <span className="text-muted-foreground">{issue.message}</span>
          </li>
        ))}
        {report.issues.length > 8 && (
          <li className="text-muted-foreground">{t("admin_hub.integrity.more", { count: report.issues.length - 8 })}</li>
        )}
      </ul>
    </section>
  );
}

export function issuesForSlug(
  issues: McpIntegrityIssue[] | undefined,
  slug: string,
): McpIntegrityIssue[] {
  if (!issues?.length) return [];
  return issues.filter(
    (i) => i.server_slug === slug || i.from_slug === slug,
  );
}
