"use client";

import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, Loader2, Wrench } from "lucide-react";
import { apiFetch } from "@/lib/api/headers";
import { apiBase } from "@/lib/api";
import { cn } from "@/lib/cn";

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

  if (loading) {
    return (
      <div
        className={cn(
          "flex items-center gap-2 rounded-2xl border border-border/70 bg-card/40 px-4 py-3 text-sm text-muted-foreground shadow-sm backdrop-blur-sm",
          className,
        )}
      >
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
        Controllo integrità MCP…
      </div>
    );
  }

  if (!report || report.issue_count === 0) {
    return (
      <div
        className={cn(
          "flex items-center gap-2 rounded-2xl border border-emerald-500/25 bg-emerald-500/8 px-4 py-3 text-sm text-emerald-700 shadow-sm backdrop-blur-sm dark:text-emerald-300",
          className,
        )}
      >
        <CheckCircle2 className="h-4 w-4 shrink-0" aria-hidden />
        Integrità MCP: nessun problema rilevato
      </div>
    );
  }

  const errors = report.issues.filter((i) => i.severity === "error").length;
  const warnings = report.issues.filter((i) => i.severity === "warning").length;

  return (
    <div
      className={cn(
        "space-y-3 rounded-2xl border border-amber-500/35 bg-amber-500/10 px-4 py-3 text-sm shadow-sm backdrop-blur-sm",
        className,
      )}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-2.5">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-700 dark:text-amber-300" aria-hidden />
          <div>
            <p className="font-semibold text-amber-900 dark:text-amber-200">
              Integrità MCP — {report.issue_count} problemi
              {errors > 0 ? ` (${errors} errori` : ""}
              {warnings > 0 ? `${errors > 0 ? ", " : " ("}${warnings} avvisi` : ""}
              {errors > 0 || warnings > 0 ? ")" : ""}
            </p>
            <p className="mt-0.5 text-xs text-amber-900/80 dark:text-amber-200/80">
              Credenziali orfane, policy disallineate o env non coerenti con lo schema.
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={() => void repairAll()}
          disabled={repairing}
          className="focus-ring inline-flex items-center gap-1.5 rounded-xl border border-amber-500/30 bg-background/60 px-3 py-2 text-xs font-semibold text-amber-900 transition hover:bg-muted disabled:opacity-50 dark:text-amber-200"
        >
          {repairing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Wrench className="h-3.5 w-3.5" />}
          Ripara automaticamente
        </button>
      </div>
      <ul className="max-h-36 space-y-1.5 overflow-y-auto text-xs text-amber-900/90 dark:text-amber-100/90">
        {report.issues.slice(0, 8).map((issue, idx) => (
          <li key={`${issue.code}-${issue.server_slug}-${idx}`} className="flex gap-2">
            <span className="shrink-0 font-mono text-[0.714em] uppercase text-amber-700/80 dark:text-amber-400/80">
              {issue.severity}
            </span>
            <span>{issue.message}</span>
          </li>
        ))}
        {report.issues.length > 8 ? (
          <li className="text-amber-800/70 dark:text-amber-300/60">…e altri {report.issues.length - 8}</li>
        ) : null}
      </ul>
    </div>
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
