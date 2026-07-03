import type { PlanCapturePhase } from "./planDisplay";

export type ChatChunk =
  | {
      type: "turn_started";
      user_message_id?: string;
      assistant_message_id?: string;
    }
  | {
      type: "context_compacting";
      active?: boolean;
      tokens?: number;
      trigger?: number;
    }
  | { type: "token"; content?: string | null }
  | { type: "reasoning"; reasoning?: unknown }
  | { type: "error"; content?: string }
  | {
      type: "llm_error";
      code?: string;
      message?: string;
      content?: string;
      exc_type?: string;
    }
  | { type: "context_length_error"; content?: string; message?: string }
  | { type: "tool_event"; event?: Record<string, unknown> }
  | { type: "artifact_start"; artifact?: Record<string, unknown> }
  | { type: "artifact_content"; content?: string; artifact_id?: string }
  | { type: "artifact_end"; artifact?: Record<string, unknown> }
  | {
      type: "orchestration_plan_pending";
      plan_id?: string;
      plan?: Record<string, unknown>;
      plan_markdown?: string;
      todos?: unknown[];
      annotations?: Record<string, unknown>;
      revision?: number;
      goal?: string;
      force_sidebar_refresh?: boolean;
      highlight_task_id?: string;
      highlightTaskId?: string;
    }
  | { type: "orchestration_task_status"; [k: string]: unknown }
  | { type: "presentation_preview"; relative_path?: string; title?: string; pdf_relative_path?: string }
  | { type: "final"; text?: string }
  | { type: "turn_outcome"; code?: string; message?: string }
  | { type: "turn_status"; phase?: string; tool?: string; message?: string }
  | {
      type: "plan_phase";
      phase?: "clarifying" | "researching" | "drafting" | "finalizing" | "registered" | "research_budget_reached" | "error";
      message?: string;
    }
  | {
      type: "plan_progress";
      plan_markdown?: string;
      tasks_count?: number;
      revision?: number;
    }
  | {
      type: "prompt_snapshot";
      assistant_message_id?: string;
      snapshot?: Record<string, unknown>;
    }
  | { type: string; [k: string]: unknown };

export type ToolStepStatus = "running" | "done" | "error";

export type ToolStepState = {
  id: string;
  name: string;
  input: unknown;
  output?: string;
  error?: string;
  isError?: boolean;
  status?: ToolStepStatus;
  tokens_in?: number;
  tokens_out?: number;
};

export type ArtifactState = {
  id: string;
  title: string;
  artType: string;
  buffer: string;
  savedPath?: string;
  version?: number;
  execution?: string;
};

export type WebSourceCard = {
  index: number;
  title: string;
  url: string;
  provider?: string;
};

export type ReasoningSegment = {
  kind: "reasoning";
  id: string;
  content: string;
};

export type ToolSegment = {
  kind: "tool";
  id: string;
  name: string;
  input: unknown;
  output?: string;
  error?: string;
  isError?: boolean;
  status: ToolStepStatus;
  tokens_in?: number;
  tokens_out?: number;
};

export type ArtifactSegment = {
  kind: "artifact";
  id: string;
  title: string;
  artType: string;
  buffer: string;
  savedPath?: string;
  version?: number;
  execution?: string;
};

export type TextSegment = {
  kind: "text";
  id: string;
  content: string;
};

/** Live status line (MemPalace progress, warnings) — never merged into markdown body. */
export type StatusSegment = {
  kind: "status";
  id: string;
  content: string;
  tone?: "info" | "warning";
};

/** Transient indicator while plan or document artifact streams (not persisted). */
export type GeneratingSegment = {
  kind: "generating";
  id: string;
  target: "plan" | "artifact";
  title?: string;
};

export type TurnSegment =
  | ReasoningSegment
  | ToolSegment
  | ArtifactSegment
  | TextSegment
  | StatusSegment
  | GeneratingSegment;

export type TurnState = {
  assistantContent: string;
  reasoning: string;
  reasoningCollapsed: boolean;
  segments: TurnSegment[];
  toolSteps: Record<string, ToolStepState>;
  toolOrder: string[];
  activeToolKeyById: Record<string, string>;
  activeToolKeyByName: Record<string, string>;
  artifactOrder: string[];
  artifacts: Record<string, ArtifactState>;
  lastPlanEvent: ChatChunk | null;
  lastPlanProgress: ChatChunk | null;
  planPhase: string | null;
  /** True while streaming tokens inside `<plan>...</plan>` (hide from chat body). */
  planCaptureActive: boolean;
  /** Sub-state for streaming plan open-tag vs body (avoids `="title"` leaks across chunks). */
  planCapturePhase: PlanCapturePhase;
  planCapturePending: string;
  error: string | null;
  finalReceived: boolean;
  webSourceCards: WebSourceCard[];
  /** True while backend compresses STM before agent.run. */
  contextCompacting: boolean;
};

export function initialTurnState(): TurnState {
  return {
    assistantContent: "",
    reasoning: "",
    reasoningCollapsed: false,
    segments: [],
    toolSteps: {},
    toolOrder: [],
    activeToolKeyById: {},
    activeToolKeyByName: {},
    artifactOrder: [],
    artifacts: {},
    lastPlanEvent: null,
    lastPlanProgress: null,
    planPhase: null,
    planCaptureActive: false,
    planCapturePhase: "none",
    planCapturePending: "",
    error: null,
    finalReceived: false,
    webSourceCards: [],
    contextCompacting: false,
  };
}
