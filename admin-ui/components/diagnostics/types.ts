export interface ProfileOption {
  slug: string;
  name: string;
  description?: string;
}

export type TestState = "idle" | "running" | "completed" | "failed";

export interface EvalCriterion {
  name?: string;
  category?: string;
  description?: string;
  details?: string;
  passed?: boolean;
  points?: number;
  points_awarded?: number;
  max_points?: number;
  points_max?: number;
}

export interface GeneratedFile {
  name: string;
  size_bytes: number;
  category?: string;
  relative_to_outputs?: string;
}

export interface TimelineEvent {
  type?: string;
  name?: string;
  timestamp?: string;
  content?: string;
  parameters?: unknown;
  result?: unknown;
}

export interface LogEvent {
  id: string;
  test?: string;
  test_name?: string;
  assistant?: string;
  step: string;
  message: string;
  timestamp: string;
  content?: string;
  tool?: string;
  params?: Record<string, unknown>;
  result?: unknown;
  duration_sec?: number;
  status?: string;
  error?: string | boolean;
  preview?: string;
  final_output?: string;
  tool_count?: number;
  generated_files?: GeneratedFile[];
}

export interface TestStatus {
  id: string;
  assistant?: string;
  status: TestState;
  duration_sec?: number;
  tool_count: number;
  final_output?: string;
  reasoning?: string;
  timeline?: TimelineEvent[];
  generated_files?: GeneratedFile[];
  charts?: Record<string, unknown>[];
  single_report_filename?: string;
  score?: number;
  max_score?: number;
  rating?: string;
  passed?: boolean;
  eval_summary?: string;
  eval_criteria?: EvalCriterion[];
}

export interface ReportFile {
  filename: string;
  size_bytes: number;
  modified_at: string;
}

export type T = (key: string, vars?: Record<string, string | number>) => string;
