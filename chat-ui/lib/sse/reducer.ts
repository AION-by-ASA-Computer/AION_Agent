import type { ChatChunk, TurnSegment, TurnState } from "./types";
import { feedPlanAwareDisplay, stripPlanBlocksForChatDisplay } from "./planDisplay";
import {
  generatingTitleForFileTool,
  isFilePreviewTool,
  isScriptLikeTitle,
} from "./filePreviewTools";
import { initialTurnState } from "./types";

/** Legacy <plan> token stripping — off when tool-first Plan Mode is default. */
const PLAN_TEXT_PARSER_ENABLED =
  process.env.NEXT_PUBLIC_AION_PLAN_TEXT_PARSER === "1";

function coerceReasoningPiece(value: unknown): string {
  if (value == null) return "";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function coerceTokenPiece(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function segId(prefix: string, n: number): string {
  return `${prefix}_${n}`;
}

function appendReasoningSegment(segments: TurnSegment[], piece: string): TurnSegment[] {
  if (!piece) return segments;
  const last = segments[segments.length - 1];
  if (last?.kind === "reasoning") {
    return [
      ...segments.slice(0, -1),
      { ...last, content: last.content + piece },
    ];
  }
  return [...segments, { kind: "reasoning", id: segId("reasoning", segments.length), content: piece }];
}

function appendTextSegment(segments: TurnSegment[], piece: string): TurnSegment[] {
  if (!piece) return segments;
  const last = segments[segments.length - 1];
  if (last?.kind === "text") {
    return [
      ...segments.slice(0, -1),
      { ...last, content: last.content + piece },
    ];
  }
  return [...segments, { kind: "text", id: segId("text", segments.length), content: piece }];
}

const LIVE_STATUS_ID = "live_turn_status";
const LIVE_GENERATING_PLAN_ID = "live_generating_plan";

function generatingIdForArtifact(artifactId: string): string {
  return `live_generating_artifact_${artifactId}`;
}

function upsertGeneratingSegment(
  segments: TurnSegment[],
  id: string,
  target: "plan" | "artifact",
  title?: string,
): TurnSegment[] {
  const without = segments.filter((s) => s.kind !== "generating" || s.id !== id);
  return [...without, { kind: "generating", id, target, title }];
}

function removeGeneratingSegment(segments: TurnSegment[], id: string): TurnSegment[] {
  return segments.filter((s) => s.kind !== "generating" || s.id !== id);
}

function upsertStatusSegment(
  segments: TurnSegment[],
  content: string,
  tone: "info" | "warning" = "info",
): TurnSegment[] {
  const trimmed = content.trim();
  if (!trimmed) return segments;
  const without = segments.filter((s) => s.kind !== "status" || s.id !== LIVE_STATUS_ID);
  return [
    ...without,
    { kind: "status", id: LIVE_STATUS_ID, content: trimmed, tone },
  ];
}

function latestToolKeyForName(state: TurnState, name: string): string | undefined {
  for (let i = state.toolOrder.length - 1; i >= 0; i -= 1) {
    const key = state.toolOrder[i];
    if (state.toolSteps[key]?.name === name) return key;
  }
  return undefined;
}

function resolveToolId(
  state: TurnState,
  ev: Record<string, unknown>,
  name: string,
): string {
  const eid = typeof ev.id === "string" && ev.id ? ev.id : "";
  if (eid && state.toolSteps[eid]) return eid;
  if (eid && state.activeToolKeyById[eid]) return state.activeToolKeyById[eid];
  return state.activeToolKeyByName[name] || latestToolKeyForName(state, name) || eid || name;
}

function syncLegacyToolFromSegment(next: TurnState, seg: Extract<TurnSegment, { kind: "tool" }>): void {
  next.toolSteps[seg.id] = {
    id: seg.id,
    name: seg.name,
    input: seg.input,
    output: seg.output,
    isError: seg.isError,
    status: seg.status,
  };
  if (!next.toolOrder.includes(seg.id)) {
    next.toolOrder.push(seg.id);
  }
}

function upsertToolSegment(
  segments: TurnSegment[],
  tool: Extract<TurnSegment, { kind: "tool" }>,
): TurnSegment[] {
  const idx = segments.findIndex((s) => s.kind === "tool" && s.id === tool.id);
  if (idx >= 0) {
    const copy = [...segments];
    copy[idx] = tool;
    return copy;
  }
  return [...segments, tool];
}

function applyStreamError(
  next: TurnState,
  chunk: { message?: unknown; content?: unknown },
  fallback = "LLM request failed.",
): TurnState {
  const message =
    typeof chunk.message === "string" && chunk.message.trim()
      ? chunk.message.trim()
      : typeof chunk.content === "string" && chunk.content.trim()
        ? chunk.content.trim()
        : fallback;
  next.error = message;
  return next;
}

export function reduceChunk(prev: TurnState, chunk: ChatChunk): TurnState {
  const next: TurnState = {
    ...prev,
    segments: [...prev.segments],
    toolSteps: { ...prev.toolSteps },
    toolOrder: [...prev.toolOrder],
    activeToolKeyById: { ...prev.activeToolKeyById },
    activeToolKeyByName: { ...prev.activeToolKeyByName },
    artifacts: { ...prev.artifacts },
    artifactOrder: [...prev.artifactOrder],
    webSourceCards: [...prev.webSourceCards],
  };
  const cType = chunk.type;

  if (cType === "context_compacting") {
    const active = Boolean((chunk as { active?: boolean }).active);
    next.contextCompacting = active;
    return next;
  }

  if (cType === "token") {
    const piece = coerceTokenPiece(chunk.content);
    next.assistantContent += piece;
    if (PLAN_TEXT_PARSER_ENABLED) {
      const wasInPlan = next.planCaptureActive;
      const filtered = feedPlanAwareDisplay(
        piece,
        next.planCapturePhase,
        next.planCapturePending,
      );
      next.planCapturePhase = filtered.phase;
      next.planCapturePending = filtered.pending;
      next.planCaptureActive = filtered.phase !== "none";
      if (!wasInPlan && filtered.inPlan) {
        next.segments = upsertGeneratingSegment(next.segments, LIVE_GENERATING_PLAN_ID, "plan");
      }
      if (wasInPlan && !filtered.inPlan) {
        next.segments = removeGeneratingSegment(next.segments, LIVE_GENERATING_PLAN_ID);
      }
      if (filtered.display) {
        next.segments = appendTextSegment(next.segments, filtered.display);
      }
    } else {
      next.segments = appendTextSegment(next.segments, piece);
    }
    return next;
  }

  if (cType === "reasoning") {
    const piece = coerceReasoningPiece(chunk.reasoning);
    next.reasoningCollapsed = false;
    next.reasoning += piece;
    next.segments = appendReasoningSegment(next.segments, piece);
    return next;
  }

  if (cType === "llm_error" || cType === "context_length_error" || cType === "error") {
    return applyStreamError(
      next,
      chunk as { message?: unknown; content?: unknown },
    );
  }

  if (cType === "tool_event") {
    const ev = (chunk.event || {}) as Record<string, unknown>;
    const et = String(ev.type || "");
    const name = String(ev.name ?? "tool");

    if (et === "request_sync") {
      const name = String(ev.tool_name || ev.name || "tool");
      const id = `sync:${name}`;
      if (!next.toolSteps[id]) {
        const toolSeg: Extract<TurnSegment, { kind: "tool" }> = {
          kind: "tool",
          id,
          name,
          input: { _pending: true },
          status: "running",
        };
        next.segments = upsertToolSegment(next.segments, toolSeg);
        next.toolSteps[id] = { id, name, input: { _pending: true }, status: "running" };
        if (!next.toolOrder.includes(id)) next.toolOrder.push(id);
        next.activeToolKeyByName[name] = id;
      }
      if (isFilePreviewTool(name)) {
        const title = generatingTitleForFileTool(name, ev.input);
        const inputObj =
          ev.input && typeof ev.input === "object"
            ? (ev.input as Record<string, unknown>)
            : {};
        const hasPreviewPayload =
          Boolean(String(inputObj.relative_path ?? "").trim()) ||
          Boolean(String(inputObj.content ?? "").trim()) ||
          Boolean(String(inputObj.new_string ?? "").trim()) ||
          Boolean(String(inputObj.patch_text ?? "").trim());
        if (hasPreviewPayload) {
          next.segments = upsertGeneratingSegment(
            next.segments,
            `live_generating_tool_${name}`,
            "artifact",
            title,
          );
        }
      }
    } else if (et === "tool_start") {
      const id =
        typeof ev.id === "string" && ev.id ? ev.id : `${name}:${next.toolOrder.length}`;
      const toolSeg: any = {
        kind: "tool",
        id,
        name,
        input: ev.input,
        status: "running",
        masked: ev.masked,
      };
      next.segments = upsertToolSegment(next.segments, toolSeg);
      next.toolSteps[id] = { id, name, input: ev.input, status: "running", masked: ev.masked } as any;
      if (!next.toolOrder.includes(id)) next.toolOrder.push(id);
      next.activeToolKeyByName[name] = id;
      if (typeof ev.id === "string" && ev.id) next.activeToolKeyById[ev.id] = id;
      if (isFilePreviewTool(name)) {
        const title = generatingTitleForFileTool(name, ev.input);
        const inputObj =
          ev.input && typeof ev.input === "object"
            ? (ev.input as Record<string, unknown>)
            : {};
        const hasPreviewPayload =
          Boolean(String(inputObj.relative_path ?? "").trim()) ||
          Boolean(String(inputObj.content ?? "").trim()) ||
          Boolean(String(inputObj.new_string ?? "").trim()) ||
          Boolean(String(inputObj.patch_text ?? "").trim());
        if (hasPreviewPayload) {
          next.segments = upsertGeneratingSegment(
            next.segments,
            `live_generating_tool_${name}`,
            "artifact",
            title,
          );
        }
      }
    } else if (et === "tool_end") {
      const id = resolveToolId(next, ev, name);
      const cur = next.toolSteps[id] || { id, name, input: ev.input ?? {} };
      const output = String(ev.output ?? "");
      const tokens_in = typeof ev.tokens_in === "number" ? ev.tokens_in : undefined;
      const tokens_out = typeof ev.tokens_out === "number" ? ev.tokens_out : undefined;
      const toolSeg: any = {
        kind: "tool",
        id,
        name: cur.name || name,
        input: cur.input ?? ev.input,
        output,
        status: "done",
        tokens_in,
        tokens_out,
        masked: ev.masked || (cur as any).masked,
      };
      next.segments = upsertToolSegment(next.segments, toolSeg);
      next.toolSteps[id] = { ...cur, output, status: "done", tokens_in, tokens_out, masked: ev.masked || (cur as any).masked } as any;
      if (!next.toolOrder.includes(id)) next.toolOrder.push(id);
      delete next.activeToolKeyByName[name];
      if (typeof ev.id === "string") delete next.activeToolKeyById[ev.id];

      if (name === "web_search") {
        try {
          const data = JSON.parse(output) as { results?: unknown[] };
          const rows = Array.isArray(data?.results) ? data.results : [];
          const seen = new Set(next.webSourceCards.map((c) => c.url));
          let idx = next.webSourceCards.length;
          for (const row of rows) {
            const r = row as Record<string, unknown>;
            const url = String(r?.url ?? "").trim();
            if (!url || seen.has(url)) continue;
            seen.add(url);
            idx += 1;
            next.webSourceCards.push({
              index: idx,
              title: String(r?.title || url).slice(0, 500),
              url,
              provider: r?.provider != null ? String(r.provider) : undefined,
            });
          }
        } catch {
          /* ignore */
        }
      }
    } else if (et === "tool_error") {
      const id = resolveToolId(next, ev, name);
      const cur = next.toolSteps[id] || { id, name, input: ev.input ?? {} };
      const toolSeg: any = {
        kind: "tool",
        id,
        name: cur.name || name,
        input: cur.input ?? ev.input,
        output: String(ev.error ?? ""),
        status: "error",
        isError: true,
        masked: ev.masked || (cur as any).masked,
      };
      next.segments = upsertToolSegment(next.segments, toolSeg);
      next.toolSteps[id] = {
        ...cur,
        output: String(ev.error ?? ""),
        isError: true,
        status: "error",
        masked: ev.masked || (cur as any).masked,
      } as any;
      if (!next.toolOrder.includes(id)) next.toolOrder.push(id);
      delete next.activeToolKeyByName[name];
      if (typeof ev.id === "string") delete next.activeToolKeyById[ev.id];
    }
    return next;
  }

  if (cType === "artifact_start") {
    const art = (chunk.artifact || {}) as Record<string, unknown>;
    const id = String(art.identifier ?? "unknown");
    const artType = String(art.type ?? "text");
    const title = String(art.title ?? id);
    const isPlan = artType.toLowerCase() === "plan";
    if (!next.artifacts[id]) next.artifactOrder.push(id);
    next.artifacts[id] = {
      id,
      title,
      artType,
      buffer: "",
    };
    if (isPlan) {
      next.segments = upsertGeneratingSegment(next.segments, LIVE_GENERATING_PLAN_ID, "plan");
    }
    if (!isPlan) {
      const pending = art.pending === true || art.source === "tool";
      if (pending) {
        for (const toolName of [
          "sandbox_write_workspace_file",
          "sandbox_edit_workspace_file",
          "sandbox_apply_patch",
        ]) {
          next.segments = removeGeneratingSegment(
            next.segments,
            `live_generating_tool_${toolName}`,
          );
        }
      }
      const aSeg: Extract<TurnSegment, { kind: "artifact" }> = {
        kind: "artifact",
        id,
        title: String(art.title ?? id),
        artType,
        buffer: "",
      };
      const idx = next.segments.findIndex((s) => s.kind === "artifact" && s.id === id);
      if (idx >= 0) {
        const copy = [...next.segments];
        copy[idx] = aSeg;
        next.segments = copy;
      } else {
        next.segments = [...next.segments, aSeg];
      }
    }
    return next;
  }

  if (cType === "artifact_content") {
    const aid = chunk.artifact_id;
    const ids = aid && next.artifacts[String(aid)] ? [String(aid)] : [...next.artifactOrder];
    for (const id of ids) {
      const a = next.artifacts[id];
      if (!a) continue;
      const buf = a.buffer + String(chunk.content ?? "");
      next.artifacts[id] = { ...a, buffer: buf };
      if (a.artType.toLowerCase() === "plan") continue;
      const idx = next.segments.findIndex((s) => s.kind === "artifact" && s.id === id);
      if (idx >= 0) {
        const seg = next.segments[idx] as Extract<TurnSegment, { kind: "artifact" }>;
        const copy = [...next.segments];
        copy[idx] = { ...seg, buffer: buf };
        next.segments = copy;
      }
    }
    return next;
  }

  if (cType === "artifact_end") {
    const art = (chunk.artifact || {}) as Record<string, unknown>;
    const id = String(art.identifier ?? "");
    const cur = next.artifacts[id];
    const isPlan = cur?.artType.toLowerCase() === "plan";
    if (cur) {
      next.artifacts[id] = {
        ...cur,
        savedPath: String(art.path ?? ""),
        version: Number(art.version ?? 1),
        execution: art.execution != null ? String(art.execution) : undefined,
      };
      const idx = next.segments.findIndex((s) => s.kind === "artifact" && s.id === id);
      if (idx >= 0) {
        const seg = next.segments[idx] as Extract<TurnSegment, { kind: "artifact" }>;
        const copy = [...next.segments];
        copy[idx] = {
          ...seg,
          savedPath: String(art.path ?? ""),
          version: Number(art.version ?? 1),
          execution: art.execution != null ? String(art.execution) : undefined,
        };
        next.segments = copy;
      }
    }
    next.segments = removeGeneratingSegment(
      next.segments,
      isPlan ? LIVE_GENERATING_PLAN_ID : generatingIdForArtifact(id),
    );
    return next;
  }

  if (cType === "orchestration_plan_pending") {
    next.lastPlanEvent = chunk;
    next.segments = removeGeneratingSegment(next.segments, LIVE_GENERATING_PLAN_ID);
    return next;
  }

  if (cType === "plan_progress") {
    next.lastPlanProgress = chunk;
    const md =
      typeof (chunk as { plan_markdown?: unknown }).plan_markdown === "string"
        ? (chunk as { plan_markdown: string }).plan_markdown
        : "";
    if (md.trim()) {
      next.planCaptureActive = true;
      next.planCapturePhase = "body";
      next.segments = upsertGeneratingSegment(next.segments, LIVE_GENERATING_PLAN_ID, "plan");
    }
    return next;
  }

  if (cType === "plan_phase") {
    const phase = String((chunk as { phase?: unknown }).phase || "");
    next.planPhase = phase || null;
    const msg =
      typeof (chunk as { message?: unknown }).message === "string"
        ? (chunk as { message: string }).message
        : "";
    const label = msg.trim() || (phase ? `Plan: ${phase}` : "");
    if (label) {
      next.segments = upsertStatusSegment(next.segments, label, "info");
    }
    if (phase === "registered") {
      next.segments = removeGeneratingSegment(next.segments, LIVE_GENERATING_PLAN_ID);
    }
    return next;
  }

  if (cType === "plan_error") {
    const rawMsg = (chunk as { message?: unknown }).message;
    const msg = typeof rawMsg === "string" ? rawMsg : "Could not structure the execution plan.";
    next.segments = upsertStatusSegment(next.segments, msg.trim(), "warning");
    return next;
  }

  if (cType === "turn_status") {
    const msg =
      typeof (chunk as { message?: unknown }).message === "string"
        ? (chunk as { message: string }).message
        : "";
    if (msg.trim()) {
      next.segments = upsertStatusSegment(next.segments, msg.trim(), "info");
    }
    return next;
  }

  if (cType === "turn_outcome") {
    const msg =
      typeof (chunk as { message?: unknown }).message === "string"
        ? (chunk as { message: string }).message
        : "";
    if (msg.trim()) {
      next.segments = upsertStatusSegment(next.segments, msg.trim(), "warning");
      if (!next.assistantContent.trim() && !next.error) {
        next.assistantContent = msg.trim();
      }
    }
    return next;
  }

  if (cType === "final") {
    next.finalReceived = true;
    const text =
      typeof (chunk as { text?: unknown }).text === "string"
        ? (chunk as { text: string }).text
        : "";
    if (text.trim() && !next.assistantContent.trim()) {
      next.assistantContent = text;
      const visible = PLAN_TEXT_PARSER_ENABLED
        ? stripPlanBlocksForChatDisplay(text)
        : text;
      if (visible) next.segments = appendTextSegment(next.segments, visible);
    }
    return next;
  }

  return next;
}

export function newTurn(): TurnState {
  return initialTurnState();
}

/** Build timeline segments from persisted assistant message fields (history reload). */
/** Rebuild live turn UI from a partially persisted assistant message (stream recovery). */
export function turnStateFromHistoryMessage(msg: {
  reasoning?: string | null;
  content?: string | null;
  timeline?: TurnSegment[] | null;
  steps?: Array<{
    id: string;
    name: string;
    input?: string | null;
    output?: string | null;
    is_error?: boolean;
    metadata_json?: string | null;
  }>;
  artifacts?: Array<{
    id: string;
    title?: string;
    artType?: string;
    buffer?: string;
    storage_key?: string;
    mime?: string;
  }>;
}): TurnState {
  const segments = segmentsForMessage(msg);
  return {
    ...initialTurnState(),
    segments,
    reasoning: (msg.reasoning || "").trim(),
    assistantContent: msg.content || "",
  };
}

export function segmentsForMessage(msg: {
  segments?: TurnSegment[] | null;
  timeline?: TurnSegment[] | null;
  reasoning?: string | null;
  content?: string | null;
  steps?: Array<{
    id: string;
    name: string;
    input?: string | null;
    output?: string | null;
    is_error?: boolean;
    metadata_json?: string | null;
  }>;
  artifacts?: Array<{
    id: string;
    title?: string;
    artType?: string;
    buffer?: string;
    storage_key?: string;
    mime?: string;
  }>;
}): TurnSegment[] {
  const saved = msg.segments ?? msg.timeline;
  if (saved && saved.length > 0) return saved;
  return segmentsFromHistoryMessage(msg);
}

export function segmentsFromHistoryMessage(msg: {
  reasoning?: string | null;
  content?: string | null;
  steps?: Array<{
    id: string;
    name: string;
    input?: string | null;
    output?: string | null;
    is_error?: boolean;
    metadata_json?: string | null;
  }>;
  artifacts?: Array<{
    id: string;
    title?: string;
    artType?: string;
    buffer?: string;
    storage_key?: string;
    mime?: string;
  }>;
}): TurnSegment[] {
  const segs: TurnSegment[] = [];
  if (msg.reasoning?.trim()) {
    segs.push({ kind: "reasoning", id: "reasoning_0", content: msg.reasoning });
  }
  for (const s of msg.steps || []) {
    let meta: Record<string, any> = {};
    if (s.metadata_json) {
      try {
        meta = JSON.parse(s.metadata_json);
      } catch {}
    }
    segs.push({
      kind: "tool",
      id: s.id,
      name: s.name,
      input: tryParseJson(s.input),
      output: s.output ?? undefined,
      status: s.is_error ? "error" : "done",
      isError: Boolean(s.is_error),
      tokens_in: typeof meta.tokens_in === "number" ? meta.tokens_in : undefined,
      tokens_out: typeof meta.tokens_out === "number" ? meta.tokens_out : undefined,
      masked: (s as any).masked,
    } as any);
  }
  for (const a of msg.artifacts || []) {
    segs.push({
      kind: "artifact",
      id: a.id,
      title: a.title || a.id,
      artType: a.artType || a.mime || "text",
      buffer: a.buffer || "",
      savedPath: a.storage_key,
    });
  }
  if (msg.content?.trim()) {
    const visible = PLAN_TEXT_PARSER_ENABLED
      ? stripPlanBlocksForChatDisplay(msg.content)
      : msg.content;
    if (visible) segs.push({ kind: "text", id: "text_0", content: visible });
  }
  return segs;
}

/** Normalize live segments before persisting to API (no running tools, no large buffers). */
export function segmentsForPersist(segments: TurnSegment[]): TurnSegment[] {
  return segments
    .filter(
      (seg) =>
        seg.kind !== "generating" &&
        (seg.kind !== "status" || seg.id.startsWith("plan_")),
    )
    .map((seg) => {
      if (seg.kind === "tool") {
        return {
          ...seg,
          status: seg.status === "running" ? "done" : seg.status,
        };
      }
      if (seg.kind === "artifact") {
        if (seg.savedPath || seg.buffer.trim()) {
          return seg;
        }
        return { ...seg, buffer: "" };
      }
      return seg;
    });
}

function tryParseJson(raw: string | null | undefined): unknown {
  if (!raw) return {};
  try {
    return JSON.parse(raw);
  } catch {
    return raw;
  }
}
