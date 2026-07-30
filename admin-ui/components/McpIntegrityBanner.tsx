"use client";

import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, Loader2, Wrench } from "lucide-react";
import { apiFetch } from "@/lib/api/headers";
import { apiBase } from "@/lib/api";

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
      <div className={`flex items-center gap-2 rounded-xl border border-white/10 bg-black/30 px-4 py-3 text-xs text-gray-500 ${className ?? ""}`}>
        <Loader2 className="h-4 w-4 animate-spin" />
        Controllo integrità MCP…
      </div>
    );
  }

  if (!report || report.issue_count === 0) {
    return (
      <div className={`flex items-center gap-2 rounded-xl border border-emerald-500/20 bg-emerald-500/5 px-4 py-3 text-xs text-emerald-300 ${className ?? ""}`}>
        <CheckCircle2 className="h-4 w-4 shrink-0" />
        Integrità MCP: nessun problema rilevato
      </div>
    );
  }

  const errors = report.issues.filter((i) => i.severity === "error").length;
  const warnings = report.issues.filter((i) => i.severity === "warning").length;

  return (
    <div className={`rounded-xl border border-amber-500/30 bg-amber-500/5 p-4 space-y-3 ${className ?? ""}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-2">
          <AlertTriangle className="h-5 w-5 text-amber-400 shrink-0 mt-0.5" />
          <div>
            <p className="text-sm font-semibold text-amber-100">
              Integrità MCP — {report.issue_count} problemi
              {errors > 0 ? ` (${errors} errori` : ""}
              {warnings > 0 ? `${errors > 0 ? ", " : " ("}${warnings} avvisi` : ""}
              {(errors > 0 || warnings > 0) ? ")" : ""}
            </p>
            <p className="text-xs text-amber-200/70 mt-0.5">
              Credenziali orfane, policy disallineate o env non coerenti con lo schema.
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={() => void repairAll()}
          disabled={repairing}
          className="flex items-center gap-1.5 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-1.5 text-xs font-bold text-amber-200 hover:bg-amber-500/20 disabled:opacity-50"
        >
          {repairing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Wrench className="h-3.5 w-3.5" />}
          Ripara automaticamente
        </button>
      </div>
      <ul className="space-y-1.5 max-h-36 overflow-y-auto text-xs text-amber-100/90">
        {report.issues.slice(0, 8).map((issue, idx) => (
          <li key={`${issue.code}-${issue.server_slug}-${idx}`} className="flex gap-2">
            <span className="font-mono text-[10px] text-amber-400/80 shrink-0 uppercase">{issue.severity}</span>
            <span>{issue.message}</span>
          </li>
        ))}
        {report.issues.length > 8 ? (
          <li className="text-amber-300/60">…e altri {report.issues.length - 8}</li>
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
