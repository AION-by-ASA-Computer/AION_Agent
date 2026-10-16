import { FileSpreadsheet, FileText, FileType2, type LucideIcon } from "lucide-react";
import type { TestStatus } from "./types";

export interface Scenario {
  id: string;
  /** i18n key suffix under admin_diagnostics.scenario */
  key: "excel" | "pdf" | "word";
  icon: LucideIcon;
  file: string;
  /** Whether `file` is something the agent reads or something it must produce. */
  fileRole: "input" | "output";
}

export const SCENARIOS: Scenario[] = [
  { id: "test_1_excel", key: "excel", icon: FileSpreadsheet, file: "dataset_vendite.xlsx", fileRole: "input" },
  { id: "test_2_pdf", key: "pdf", icon: FileText, file: "manuale_tesla.pdf", fileRole: "input" },
  { id: "test_3_word", key: "word", icon: FileType2, file: "agenda_kickoff.docx", fileRole: "output" },
];

export const freshStatus = (assistant?: string): Record<string, TestStatus> =>
  Object.fromEntries(SCENARIOS.map((s) => [s.id, { id: s.id, assistant, status: "idle", tool_count: 0 } as TestStatus]));
