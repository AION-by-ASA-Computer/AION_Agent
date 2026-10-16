"use client";

import { CheckCircle2, FileSearch, Loader2, ShieldAlert, ShieldCheck } from "lucide-react";
import { cn } from "@/lib/cn";
import { outlineBtn, ghostBtn } from "@/components/ui/classes";
import { baseName, highestSeverity, type ScanResult, type Severity } from "./report";

type T = (key: string, vars?: Record<string, string | number>) => string;
const k = "admin_security";
const PREVIEW = 3;

export const SEVERITY_CLS: Record<Severity, string> = {
  low: "bg-secondary text-muted-foreground",
  medium: "bg-warning/15 text-warning",
  high: "bg-destructive/12 text-destructive",
  critical: "bg-destructive text-destructive-foreground",
};

export function SeverityPill({ severity, t }: { severity: Severity; t: T }) {
  return <span className={cn("shrink-0 rounded-full px-2 py-0.5 text-xs font-semibold", SEVERITY_CLS[severity])}>{t(`${k}.sev.${severity}`)}</span>;
}

export function FindingsList({
  scan,
  activeFile,
  streaming,
  onInvestigate,
  onTrust,
  t,
}: {
  scan: ScanResult | null;
  activeFile: string | null;
  streaming: boolean;
  onInvestigate: (file: string) => void;
  onTrust: (file: string) => void;
  t: T;
}) {
  if (!scan) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center px-6 py-16 text-center">
        <h3 className="text-base font-semibold tracking-[-0.015em]">{t(`${k}.findings.empty_title`)}</h3>
        <p className="mt-1.5 max-w-[34ch] text-sm text-muted-foreground">{t(`${k}.findings.empty_body`)}</p>
      </div>
    );
  }

  const entries = Object.entries(scan.violations || {});
  if (entries.length === 0) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center px-6 py-16 text-center">
        <CheckCircle2 className="h-5 w-5 text-success" aria-hidden />
        <h3 className="mt-3 text-base font-semibold tracking-[-0.015em]">{t(`${k}.findings.clean_title`)}</h3>
        <p className="mt-1.5 max-w-[34ch] text-sm text-muted-foreground">{t(`${k}.findings.clean_body`)}</p>
      </div>
    );
  }

  const open = entries.filter(([, d]) => !d.is_trusted).length;
  return (
    <>
      <div
        className={cn("flex items-center gap-2 border-b border-border/60 px-5 py-2.5 text-sm font-medium", scan.is_safe ? "text-success" : "text-destructive")}
        role="status"
      >
        {scan.is_safe ? <ShieldCheck className="h-4 w-4" aria-hidden /> : <ShieldAlert className="h-4 w-4" aria-hidden />}
        {scan.is_safe ? t(`${k}.findings.banner_safe`) : t(`${k}.findings.banner_unsafe`, { n: open })}
      </div>
      <ul className="min-h-0 flex-1 overflow-y-auto">
        {entries.map(([file, data]) => {
          const list = data.list || [];
          const trusted = !!data.is_trusted;
          const active = file === activeFile;
          return (
            <li key={file} className={cn("border-b border-border/40 px-5 py-4 last:border-b-0", active && "bg-secondary/70")}>
              <div className="flex items-center gap-2">
                <span className="min-w-0 flex-1 truncate font-mono text-[13px] font-medium" title={file}>
                  {baseName(file)}
                </span>
                {trusted ? (
                  <span className="inline-flex shrink-0 items-center gap-1 text-xs font-medium text-success">
                    <ShieldCheck className="h-3.5 w-3.5" aria-hidden />
                    {t(`${k}.findings.trusted`)}
                  </span>
                ) : (
                  <SeverityPill severity={highestSeverity(list)} t={t} />
                )}
              </div>
              <ul className={cn("mt-2 flex flex-col gap-1 text-xs text-muted-foreground", trusted && "opacity-60")}>
                {list.slice(0, PREVIEW).map((v, i) => (
                  <li key={i} className="line-clamp-2 break-words">
                    {v.message}
                  </li>
                ))}
                {list.length > PREVIEW && <li>{t(`${k}.findings.more`, { n: list.length - PREVIEW })}</li>}
              </ul>
              <div className="mt-3 flex items-center gap-1.5">
                <button type="button" className={cn(outlineBtn, "h-8 px-2.5 text-[13px]")} onClick={() => onInvestigate(file)} disabled={streaming}>
                  {streaming && active ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <FileSearch className="h-3.5 w-3.5" aria-hidden />}
                  {t(`${k}.findings.investigate`)}
                </button>
                {!trusted && (
                  <button type="button" className={cn(ghostBtn, "h-8 px-2.5 text-[13px]")} onClick={() => onTrust(file)}>
                    {t(`${k}.findings.trust`)}
                  </button>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </>
  );
}
