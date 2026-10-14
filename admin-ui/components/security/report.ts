export type Severity = "low" | "medium" | "high" | "critical";
export type Violation = { severity: Severity; message: string };
export type FileFindings = { list: Violation[]; is_trusted?: boolean };
export type ScanResult = {
  id: string;
  timestamp: string;
  target_path: string;
  is_safe: boolean;
  violations: Record<string, FileFindings>;
};
export type ScanSummary = { id: string; timestamp: string; target_path: string; is_safe: boolean };
export type SavedReport = { id: string; timestamp: string; path: string; profile: string };
export type Investigation = { verdict?: string; risk_score?: number; summary?: string; fixes?: string[] };

const WEIGHT: Record<Severity, number> = { low: 1, medium: 2, high: 3, critical: 4 };

export const highestSeverity = (list: Violation[]): Severity =>
  list.reduce<Severity>((top, v) => (WEIGHT[v.severity] > WEIGHT[top] ? v.severity : top), "low");

export const baseName = (path: string) => path.split("/").pop() || path;

/** The report body without the machine-readable JSON block the agent appends. */
export function stripJson(text: string): string {
  return text.replace(/```json\s*([\s\S]*?)\s*```/g, "").replace(/\{[\s\S]*?\}/g, (m) => {
    try {
      JSON.parse(m);
      return "";
    } catch {
      return m;
    }
  });
}

/** Pulls the verdict JSON out of a finished report, tolerating the usual model slips. */
export function extractInvestigation(text: string): Investigation | null {
  let raw = text.match(/```json\s*([\s\S]*?)\s*```/)?.[1]?.trim() ?? "";
  if (!raw) {
    const open = text.lastIndexOf("{");
    const close = text.lastIndexOf("}");
    if (open !== -1 && close > open) raw = text.slice(open, close + 1);
  }
  if (!raw) return null;
  let s = raw
    .replace(/[\u0000-\u001F\u007F-\u009F]/g, "")
    .replace(/datetime\.[\w()]*/g, (m) => `"${m}"`)
    .replace(/:\s*None/g, ": null")
    .replace(/:\s*True/g, ": true")
    .replace(/:\s*False/g, ": false")
    .trim();
  if (s.startsWith("{") && !s.endsWith("}")) s += "}";
  try {
    return JSON.parse(s);
  } catch {
    return null;
  }
}

/** Backend verdicts are Italian (SICURO / SOSPETTO / …); anything else reads as dangerous. */
export function verdictTone(verdict?: string): "safe" | "suspicious" | "dangerous" | "unknown" {
  if (!verdict) return "unknown";
  const v = verdict.toUpperCase();
  if (v === "SICURO" || v === "SAFE") return "safe";
  if (v === "SOSPETTO" || v === "SUSPICIOUS") return "suspicious";
  return "dangerous";
}
