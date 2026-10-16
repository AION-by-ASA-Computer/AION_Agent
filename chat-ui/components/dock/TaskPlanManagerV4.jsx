"use client";
import React, { useState, useEffect, useMemo, useRef, useCallback } from "react";
import { useT } from "@/lib/i18n/use-t";
import { resolvePlanEditorMarkdown, orchestrationPlanToMarkdown } from "@/lib/sse/planDisplay";
import {
  fetchPlanExecutionResult,
  subscribePlanExecutionStream,
  resumePlanExecution,
  startPlanExecution,
} from "@/lib/api/plan-execution";
import {
  Target,
  BookOpen,
  FileCode,
  CheckCircle2,
  Circle,
  Loader2,
  PauseCircle,
  Check,
  X,
  Plus,
  ArrowRight,
  ExternalLink,
  Workflow,
  Sparkles,
  FileText,
  ListTodo,
  Type,
  Heading1,
  Heading2,
  Heading3,
  CheckSquare,
  Code as CodeIcon,
  List as ListIcon,
  Clock,
  Play,
  RotateCw,
} from "lucide-react";
import { cn } from "@/lib/cn";

function formatDuration(sec) {
  if (sec == null || sec <= 0) return "0s";
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  if (m === 0) return `${s}s`;
  return `${m}m ${s}s`;
}

function escapeHtml(s) {
  return String(s || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function renderInlineMd(raw) {
  let t = escapeHtml(raw || "");
  t = t.replace(/`([^`]+)`/g, '<code class="font-mono text-[0.88em] px-1.5 py-0.5 rounded bg-muted/60 text-foreground">$1</code>');
  let prev = "";
  while (prev !== t) {
    prev = t;
    t = t.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  }
  t = t.replace(/(?<!\*)\*([^*]+)\*(?!\*)/g, "<em>$1</em>");
  t = t.replace(
    /\[([^\]]+)\]\((https?:[^)\s]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener noreferrer" class="text-primary underline underline-offset-2">$1</a>'
  );
  return t;
}

function MdSpan({ text, className = "", ...rest }) {
  return (
    <span
      className={className}
      dangerouslySetInnerHTML={{ __html: renderInlineMd(text || "") }}
      {...rest}
    />
  );
}

const generateId = () => Math.random().toString(36).substr(2, 9);

function blockStableId(block, index) {
  const head = String(block.content || "").slice(0, 80);
  return `b-${index}-${block.type}-${head.length}-${head.replace(/\s+/g, " ").trim()}`;
}

const stripLegacyTaskMeta = (content) =>
  String(content || "")
    .replace(/\s*\(profile:\s*[^)]+\)/gi, "")
    .trim();

const parseTaskLine = (content, checked) => {
  const normalized = stripLegacyTaskMeta(content);
  const idm = /`([^`]+)`/.exec(normalized || "");
  const id = idm ? idm[1].trim() : "";
  const tm = /\*\*([^*]+)\*\*/.exec(normalized || "");
  const title = tm ? tm[1].trim() : (normalized || "").replace(/^`[^`]+`\s*/, "").trim();
  const dm = /\(deps:\s*([^)]+)\)/.exec(normalized || "");
  const depsRaw = dm ? dm[1].trim() : "";
  const deps =
    depsRaw && !/^none$/i.test(depsRaw) && depsRaw !== "-"
      ? depsRaw.split(",").map((s) => s.trim()).filter(Boolean)
      : [];
  return { id, title, deps, checked, normalized };
};

const formatCanonicalTaskContent = (content, taskIndex, depsOverride) => {
  const meta = parseTaskLine(content, false);
  const id =
    meta.id && /^task_\d+$/i.test(meta.id)
      ? meta.id
      : `task_${String(taskIndex).padStart(2, "0")}`;
  const title = (meta.title || stripLegacyTaskMeta(content) || `Task ${taskIndex}`).trim();
  const deps = depsOverride ?? meta.deps;
  const depsLabel = deps.length ? deps.join(", ") : "none";
  return `\`${id}\` **${title}** (deps: ${depsLabel})`;
};

const isTasksSectionHeading = (content) => {
  const h = String(content || "").trim().toLowerCase();
  return /^(tasks?|compiti|passi|steps?|tareas|aufgaben|tâches)$/.test(h);
};

const serializeBlocksToCanonicalMarkdown = (blks) => {
  let taskIndex = 0;
  let inTasksSection = false;
  return (blks || [])
    .map((b) => {
      switch (b.type) {
        case "h1":
          inTasksSection = false;
          return `# ${b.content}`;
        case "h2":
          inTasksSection = isTasksSectionHeading(b.content);
          return `## ${b.content}`;
        case "h3":
          inTasksSection = false;
          return `### ${b.content}`;
        case "task": {
          taskIndex += 1;
          inTasksSection = true;
          const main = `- [${b.checked ? "x" : " "}] ${formatCanonicalTaskContent(b.content, taskIndex)}`;
          if (b.description && b.description.trim()) {
            return `${main}\n  - Description: ${b.description.trim()}`;
          }
          return main;
        }
        case "list":
          if (inTasksSection) {
            taskIndex += 1;
            return `- [ ] ${formatCanonicalTaskContent(b.content, taskIndex)}`;
          }
          return `- ${b.content}`;
        case "code":
          inTasksSection = false;
          return `\`\`\`\n${b.content}\n\`\`\``;
        default:
          return b.content;
      }
    })
    .join("\n");
};

const planLabels = (t) => ({
  title: t("plan.fallback.title"),
  goal: t("plan.fallback.goal"),
  context: t("plan.fallback.context"),
  tasks: t("plan.fallback.tasks"),
  notes: t("plan.fallback.notes"),
});

const planJsonToMarkdown = (initialPlan, t) => {
  if (!initialPlan || !initialPlan.tasks) return "";
  return orchestrationPlanToMarkdown(initialPlan, planLabels(t));
};

const todosFromBlocks = (blks) => {
  const todos = [];
  let taskIndex = 0;
  let inTasksSection = false;
  for (const b of blks || []) {
    if (b.type === "h2") {
      inTasksSection = isTasksSectionHeading(b.content);
      continue;
    }
    if (b.type === "h1" || b.type === "h3" || b.type === "code") {
      inTasksSection = false;
      continue;
    }
    const isTaskLike = b.type === "task" || (b.type === "list" && inTasksSection);
    if (!isTaskLike) continue;
    taskIndex += 1;
    const checked = b.type === "task" ? Boolean(b.checked) : false;
    const meta = parseTaskLine(b.content, checked);
    const id =
      meta.id && /^task_\d+$/i.test(meta.id)
        ? meta.id
        : `task_${String(taskIndex).padStart(2, "0")}`;
    todos.push({
      id,
      title: meta.title || stripLegacyTaskMeta(b.content) || `Task ${taskIndex}`,
      description: (b.description || "").trim(),
      status: checked ? "done" : "pending",
      depends_on: meta.deps,
      target_profile: "",
      comment: "",
    });
  }
  return todos;
};

export default function TaskPlanManagerV4(props) {
  const t = useT();
  const {
    apiBase,
    planId: rawPlanId,
    sessionId: rawSessionId,
    initialPlan,
    initialMarkdown,
    revision,
    authToken,
    highlightTaskId: hlProp,
    userId: userIdProp,
    profileName: profileNameProp,
    executionRunId,
    executionProgress,
    selectedTaskId,
    onPlanApproved,
    onPlanRejected,
    onFinalSummary,
    onExecutionAdoptHandled,
    onTaskSelect,
  } = props || {};

  const planId = (rawPlanId || "").trim();
  const sessionId = (rawSessionId || "").trim();

  const [planViewTab, setPlanViewTab] = useState("overview"); // "overview" | "document"

  const extractSection = (md, header) => {
    const lines = (md || "").split("\n");
    let mode = false;
    const buf = [];
    const h = header.trim().toLowerCase();
    for (const raw of lines) {
      const line = raw.trimEnd();
      const sl = line.trim().toLowerCase();
      if (sl === `## ${h}`) {
        mode = true;
        continue;
      }
      if (line.trim().startsWith("## ") && sl !== `## ${h}`) {
        mode = false;
        continue;
      }
      if (mode) buf.push(line);
    }
    return buf.join("\n").trim();
  };

  const parseMarkdownToBlocks = (md, prevBlocks = []) => {
    if (!md) return [];
    const lines = md.split("\n");
    const newBlocks = [];
    let currentCodeBlock = null;
    let blockIndex = 0;

    const snapshotDescMap = {};
    (planSnapshot?.tasks || []).forEach((t) => {
      if (t?.id && t?.description) {
        snapshotDescMap[String(t.id)] = String(t.description).trim();
      }
    });

    const pushBlock = (block) => {
      const prev = prevBlocks[blockIndex];
      const stable =
        prev &&
        prev.type === block.type &&
        String(prev.content || "") === String(block.content || "") &&
        Boolean(prev.checked) === Boolean(block.checked)
          ? prev.id
          : blockStableId(block, blockIndex);
      const description =
        prev && prev.id === stable && prev.description !== undefined
          ? prev.description
          : (block.description !== undefined ? block.description : "");
      newBlocks.push({ ...block, id: stable, description });
      blockIndex += 1;
    };

    lines.forEach((line) => {
      const trimmed = line.trim();

      if (trimmed.startsWith("```")) {
        if (currentCodeBlock) {
          pushBlock(currentCodeBlock);
          currentCodeBlock = null;
        } else {
          currentCodeBlock = { type: "code", content: "" };
        }
        return;
      }

      if (currentCodeBlock) {
        currentCodeBlock.content += (currentCodeBlock.content ? "\n" : "") + line;
        return;
      }

      // Check if line is a description of the previous task block
      if (/^\s*-\s*Description:/i.test(line) || /^\s*Description:/i.test(line) || (/^\s{2,}-\s*/.test(line) && newBlocks.length > 0 && newBlocks[newBlocks.length - 1]?.type === "task")) {
        const cleanDesc = line
          .replace(/^\s*-\s*Description:\s*/i, "")
          .replace(/^\s*Description:\s*/i, "")
          .replace(/^\s{2,}-\s*(?:Description:\s*)?/i, "")
          .trim();
        if (newBlocks.length > 0 && newBlocks[newBlocks.length - 1]?.type === "task") {
          const last = newBlocks[newBlocks.length - 1];
          last.description = last.description ? `${last.description}\n${cleanDesc}` : cleanDesc;
        }
        return;
      }

      if (line.startsWith("# ")) {
        pushBlock({ type: "h1", content: line.slice(2) });
      } else if (line.startsWith("## ")) {
        pushBlock({ type: "h2", content: line.slice(3) });
      } else if (line.startsWith("### ")) {
        pushBlock({ type: "h3", content: line.slice(4) });
      } else if (/^\s*-\s*\[[ xX]\]\s/.test(line)) {
        const checked = /^\s*-\s*\[[xX]\]/.test(line);
        let content = stripLegacyTaskMeta(line.replace(/^\s*-\s*\[[ xX]\]\s*/, ""));
        content = content.replace(/\s*-\s*Description:.*$/i, "").trim();
        const meta = parseTaskLine(content, checked);
        const initialDesc = meta?.id && snapshotDescMap[meta.id] ? snapshotDescMap[meta.id] : "";
        pushBlock({ type: "task", content, checked, description: initialDesc });
      } else if (line.startsWith("- ")) {
        pushBlock({ type: "list", content: line.slice(2) });
      } else if (trimmed !== "") {
        pushBlock({ type: "text", content: line });
      }
    });

    if (currentCodeBlock) pushBlock(currentCodeBlock);
    return newBlocks;
  };

  const serializeBlocksToMarkdown = (blks) => {
    return blks
      .map((b) => {
        switch (b.type) {
          case "h1":
            return `# ${b.content}`;
          case "h2":
            return `## ${b.content}`;
          case "h3":
            return `### ${b.content}`;
          case "task": {
            const main = `- [${b.checked ? "x" : " "}] ${b.content}`;
            if (b.description && b.description.trim()) {
              return `${main}\n  - Description: ${b.description.trim()}`;
            }
            return main;
          }
          case "list":
            return `- ${b.content}`;
          case "code":
            return `\`\`\`\n${b.content}\n\`\`\``;
          default:
            return b.content;
        }
      })
      .join("\n");
  };

  const extractLegacyDescriptions = (md) => {
    const map = {};
    let lastId = null;
    const lines = (md || "").split("\n");
    const taskLine = /^\s*-\s*\[[ xX]\]\s*`([^`]+)`/;
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      const tm = taskLine.exec(line);
      if (tm) {
        lastId = tm[1].trim();
        continue;
      }
      if (lastId && (/^\s*-\s*Description:\s*/i.test(line) || /^\s*Description:\s*/i.test(line))) {
        const clean = line.replace(/^\s*-\s*Description:\s*/i, "").replace(/^\s*Description:\s*/i, "").trim();
        if (clean) {
          map[lastId] = clean;
          lastId = null;
        }
      } else if (lastId && /^\s{2,}-\s*(.+)/.test(line)) {
        const clean = line.replace(/^\s{2,}-\s*(?:Description:\s*)?/i, "").trim();
        if (clean) {
          map[lastId] = clean;
          lastId = null;
        }
      }
    }
    return map;
  };

  const [blocks, setBlocks] = useState([]);
  const [focusedId, setFocusedId] = useState(null);
  const [statusMsg, setStatusMsg] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [showSlashMenu, setShowSlashMenu] = useState(null);
  const [baseMarkdown, setBaseMarkdown] = useState("");
  const [lastAppliedRevision, setLastAppliedRevision] = useState(0);
  const [revisionNotice, setRevisionNotice] = useState("");
  const [isLocked, setIsLocked] = useState(false);
  const [userDecision, setUserDecision] = useState(null);
  const [planSnapshot, setPlanSnapshot] = useState(initialPlan || {});
  const [hlTask, setHlTask] = useState((hlProp || "").trim());
  const [executionLabel, setExecutionLabel] = useState("");
  const [executionActivities, setExecutionActivities] = useState([]);
  const [executionStatus, setExecutionStatus] = useState("");
  const [executionDeliverablePath, setExecutionDeliverablePath] = useState("");
  const [expandedTasks, setExpandedTasks] = useState({});

  const toggleTaskExpand = useCallback((taskId) => {
    setExpandedTasks((prev) => ({
      ...prev,
      [taskId]: !prev[taskId],
    }));
  }, []);

  const historyRef = useRef([]);
  const historyPointerRef = useRef(-1);
  const isUndoRedoActionRef = useRef(false);
  const executionFinalHandledRef = useRef(false);
  const onFinalSummaryRef = useRef(onFinalSummary);
  const onExecutionAdoptHandledRef = useRef(onExecutionAdoptHandled);

  useEffect(() => {
    onFinalSummaryRef.current = onFinalSummary;
  }, [onFinalSummary]);

  useEffect(() => {
    onExecutionAdoptHandledRef.current = onExecutionAdoptHandled;
  }, [onExecutionAdoptHandled]);

  const emitExecutionFinalOnce = useCallback(
    (runId) => {
      const rid = (runId || "").trim();
      if (!rid || !userIdProp || executionFinalHandledRef.current) return;
      executionFinalHandledRef.current = true;
      void (async () => {
        const result = await fetchPlanExecutionResult(rid, userIdProp, authToken);
        if (result?.deliverable_path) setExecutionDeliverablePath(result.deliverable_path);
        if (result?.summary && typeof onFinalSummaryRef.current === "function") {
          onFinalSummaryRef.current(result.summary, result.plan_id || planId, rid);
        }
        if (typeof onExecutionAdoptHandledRef.current === "function") {
          onExecutionAdoptHandledRef.current();
        }
      })();
    },
    [userIdProp, authToken, planId],
  );

  useEffect(() => {
    const h = (hlProp || "").trim();
    if (h) setHlTask(h);
  }, [hlProp]);

  useEffect(() => {
    if (initialPlan && typeof initialPlan === "object") setPlanSnapshot(initialPlan);
  }, [initialPlan, revision]);

  const fallbackFromPlan = useMemo(
    () => planJsonToMarkdown(initialPlan, t),
    [initialPlan, t]
  );

  const resolvedInitialMarkdown = useMemo(
    () =>
      resolvePlanEditorMarkdown(initialMarkdown, initialPlan, planLabels(t)) ||
      fallbackFromPlan ||
      `# ${t("plan.fallback.title")}\n\n## ${t("plan.fallback.goal")}\n${t("plan.fallback.goal")}\n\n## ${t("plan.fallback.tasks")}\n`,
    [initialMarkdown, initialPlan, fallbackFromPlan, t]
  );

  useEffect(() => {
    const source = resolvedInitialMarkdown;
    const incomingRev = Number(revision || 1);
    if (incomingRev <= lastAppliedRevision) return;
    const nextMarkdown = source;
    const currentMd = serializeBlocksToMarkdown(blocks);
    const dirty = currentMd !== baseMarkdown;
    if (dirty && lastAppliedRevision > 0) {
      setRevisionNotice(t("plan.notice.revision_available", { rev: incomingRev }));
      return;
    }
    setBlocks((prev) => {
      return parseMarkdownToBlocks(nextMarkdown, prev);
    });
    setBaseMarkdown(nextMarkdown);
    setLastAppliedRevision(incomingRev);
    setRevisionNotice(incomingRev > 1 ? t("plan.notice.updated", { rev: incomingRev }) : "");
  }, [resolvedInitialMarkdown, revision, t]);

  useEffect(() => {
    if (executionProgress) {
      setIsLocked(true);
      const label = executionProgress.label || "";
      if (label) setExecutionLabel(label);
      if (executionProgress.status) setExecutionStatus(executionProgress.status);
      const curTask = executionProgress.progress?.task_id;
      if (curTask) setHlTask(String(curTask));
      if (executionProgress.activities?.length) {
        setExecutionActivities(executionProgress.activities);
      }
      if (executionProgress.error) {
        setExecutionLabel(executionProgress.error);
        setExecutionStatus("error");
      }
      return undefined;
    }

    const runId = (executionRunId || "").trim();
    if (!runId || !userIdProp) return undefined;
    setIsLocked(true);

    const unsub = subscribePlanExecutionStream(
      runId,
      userIdProp,
      authToken,
      (ev) => {
        if (ev.type === "plan_execution_progress") {
          const l = ev.label || "";
          if (l) setExecutionLabel(l);
          if (ev.status) setExecutionStatus(ev.status);
          const tid = ev.progress?.task_id;
          if (tid) setHlTask(String(tid));
          if (Array.isArray(ev.activities)) setExecutionActivities(ev.activities);
          if (ev.done) {
            emitExecutionFinalOnce(runId);
          }
        } else if (ev.type === "plan_execution_final") {
          if (ev.deliverable_path) setExecutionDeliverablePath(ev.deliverable_path);
          if (ev.summary && typeof onFinalSummaryRef.current === "function") {
            onFinalSummaryRef.current(ev.summary, ev.plan_id || planId, runId);
          }
          if (typeof onExecutionAdoptHandledRef.current === "function") {
            onExecutionAdoptHandledRef.current();
          }
        }
      },
      () => {},
      {
        onRunNotFound: () => {
          setIsLocked(false);
        },
      }
    );

    return () => unsub();
  }, [executionProgress, executionRunId, userIdProp, authToken, planId, emitExecutionFinalOnce]);

  useEffect(() => {
    if (!executionProgress?.done || !executionRunId || !userIdProp) return undefined;
    emitExecutionFinalOnce(executionRunId);
    return undefined;
  }, [executionProgress?.done, executionRunId, userIdProp, emitExecutionFinalOnce]);

  // Track blocks state changes for Undo/Redo history
  useEffect(() => {
    if (isUndoRedoActionRef.current) {
      isUndoRedoActionRef.current = false;
      return;
    }
    if (!blocks || blocks.length === 0) return;
    const currentHistory = historyRef.current.slice(0, historyPointerRef.current + 1);
    const lastState = currentHistory[currentHistory.length - 1];
    if (lastState && JSON.stringify(lastState) === JSON.stringify(blocks)) return;

    const nextHistory = [...currentHistory, blocks];
    if (nextHistory.length > 50) nextHistory.shift();
    historyRef.current = nextHistory;
    historyPointerRef.current = nextHistory.length - 1;
  }, [blocks]);

  useEffect(() => {
    if (!planId || !sessionId || !apiBase) return undefined;
    let cancelled = false;
    const base = (apiBase || "").replace(/\/$/, "");
    const headers = {
      "Content-Type": "application/json",
      "X-AION-User-Id": userIdProp || "default",
    };
    if (authToken) headers.Authorization = `Bearer ${authToken}`;

    const poll = async () => {
      try {
        const r = await fetch(
          `${base}/internal/orchestration/plans/${encodeURIComponent(planId)}?session_id=${encodeURIComponent(sessionId)}`,
          { method: "GET", headers }
        );
        if (!r.ok) return;
        const j = await r.json();
        if (cancelled || !j) return;
        const rev = Number(j.revision || 1);
        const md = String(j.markdown || "").trim();
        const planJson = j.plan && typeof j.plan === "object" ? j.plan : null;
        const locked = !!j.locked;
        if (locked !== isLocked) setIsLocked(locked);
        if (rev <= lastAppliedRevision) return;
        const hasStructured =
          planJson && Array.isArray(planJson.tasks) && planJson.tasks.length > 0;
        if (!hasStructured && !md) return;
        const currentMd = serializeBlocksToMarkdown(blocks);
        const dirty = currentMd !== baseMarkdown;
        if (dirty && !locked) {
          setRevisionNotice(t("plan.notice.revision_available", { rev }));
          return;
        }
        if (hasStructured) {
          setPlanSnapshot(planJson);
          const fromJson = resolvePlanEditorMarkdown(md, planJson, planLabels(t)) || planJsonToMarkdown(planJson, t);
          setBlocks((prev) => parseMarkdownToBlocks(fromJson, prev));
          setBaseMarkdown(fromJson);
        } else if (md) {
          const fixed = resolvePlanEditorMarkdown(md, planSnapshot, planLabels(t));
          setBlocks((prev) => parseMarkdownToBlocks(fixed, prev));
          setBaseMarkdown(fixed);
        }
        setLastAppliedRevision(rev);
        setRevisionNotice(rev > 1 ? t("plan.notice.updated", { rev }) : "");
      } catch {
        /* polling silenzioso */
      }
    };

    poll();
    const id = setInterval(poll, 2500);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [planId, sessionId, apiBase, authToken, userIdProp, lastAppliedRevision, baseMarkdown, isLocked, t]);

  const currentMarkdown = useMemo(() => serializeBlocksToMarkdown(blocks), [blocks]);
  const isDirty = currentMarkdown !== baseMarkdown;

  const descById = useMemo(() => {
    const m = {};
    (planSnapshot.tasks || []).forEach((t) => {
      if (t && t.id) {
        const d = String(t.description || "").trim();
        if (d) m[String(t.id)] = d;
      }
    });
    const fromLegacy = extractLegacyDescriptions(currentMarkdown);
    Object.assign(m, fromLegacy);
    (blocks || []).forEach((b) => {
      if (b.type === "task") {
        const meta = parseTaskLine(b.content, b.checked);
        if (meta?.id && b.description !== undefined) {
          m[meta.id] = b.description;
        }
      }
    });
    return m;
  }, [planSnapshot, currentMarkdown, blocks]);

  const goalText = useMemo(() => extractSection(currentMarkdown, t("plan.fallback.goal")) || extractSection(currentMarkdown, "Goal") || extractSection(currentMarkdown, "Obiettivo"), [currentMarkdown, t]);
  const contextText = useMemo(() => extractSection(currentMarkdown, t("plan.fallback.context")) || extractSection(currentMarkdown, "Context") || extractSection(currentMarkdown, "Contesto"), [currentMarkdown, t]);
  const deliverableText = useMemo(() => {
    const raw = extractSection(currentMarkdown, "Deliverable") || extractSection(currentMarkdown, "Deliverables") || "";
    return raw.replace(/^`+|`+$/g, "").trim();
  }, [currentMarkdown]);

  const taskBlocks = useMemo(() => (blocks || []).filter((b) => b.type === "task"), [blocks]);
  const parsedTasks = useMemo(
    () => taskBlocks.map((b) => ({ block: b, meta: parseTaskLine(b.content, b.checked) })),
    [taskBlocks]
  );
  const completedTasks = useMemo(() => parsedTasks.filter((p) => p.meta.checked), [parsedTasks]);
  const pendingTasks = useMemo(() => parsedTasks.filter((p) => !p.meta.checked), [parsedTasks]);
  const currentTask = pendingTasks[0] || null;

  const taskProgress = useMemo(() => {
    const total = taskBlocks.length;
    const done = completedTasks.length;
    const percent = total > 0 ? Math.round((done / total) * 100) : 0;
    return { done, total, percent };
  }, [taskBlocks.length, completedTasks.length]);

  const postDecision = async (path, body, okText, decisionKind) => {
    setIsSubmitting(true);
    setStatusMsg(t("plan.decision.sending"));
    const base = (apiBase || "").replace(/\/$/, "");
    const headers = {
      "Content-Type": "application/json",
      "X-AION-User-Id": userIdProp || "default",
    };
    if (authToken) headers.Authorization = `Bearer ${authToken}`;

    try {
      const r = await fetch(`${base}${path}`, {
        method: "POST",
        headers,
        body: JSON.stringify(body),
      });

      const j = await r.json().catch(() => null);
      if (!r.ok) {
        setStatusMsg(t("plan.error.server", { code: r.status, msg: (j && j.detail) || "Unknown error" }));
        return;
      }
      setBaseMarkdown(currentMarkdown);
      if (decisionKind === "approved") setIsLocked(true);
      setUserDecision(decisionKind);
      setStatusMsg(okText);
      if (
        decisionKind === "approved" &&
        typeof onPlanApproved === "function" &&
        j &&
        j.run_id
      ) {
        const rid = String(j.run_id || "").trim();
        const pid = String(j.plan_id || planId || "").trim();
        if (rid && pid) onPlanApproved(rid, pid);
      }
      if (
        decisionKind === "rejected" &&
        typeof onPlanRejected === "function"
      ) {
        onPlanRejected(planId);
      }
    } catch (e) {
      setStatusMsg(t("plan.error.network", { msg: e.message }));
    } finally {
      setIsSubmitting(false);
    }
  };

  const performUndo = useCallback(() => {
    if (historyPointerRef.current > 0) {
      historyPointerRef.current -= 1;
      const prevState = historyRef.current[historyPointerRef.current];
      isUndoRedoActionRef.current = true;
      setBlocks(prevState);
    }
  }, []);

  const performRedo = useCallback(() => {
    if (historyPointerRef.current < historyRef.current.length - 1) {
      historyPointerRef.current += 1;
      const nextState = historyRef.current[historyPointerRef.current];
      isUndoRedoActionRef.current = true;
      setBlocks(nextState);
    }
  }, []);

  const postTaskComplete = async (taskId) => {
    const base = (apiBase || "").replace(/\/$/, "");
    const headers = {
      "Content-Type": "application/json",
      "X-AION-User-Id": userIdProp || "default",
    };
    if (authToken) headers.Authorization = `Bearer ${authToken}`;
    try {
      const r = await fetch(
        `${base}/internal/orchestration/plans/${encodeURIComponent(planId)}/tasks/${encodeURIComponent(taskId)}/complete`,
        {
          method: "POST",
          headers,
          body: JSON.stringify({ session_id: sessionId }),
        }
      );
      const j = await r.json().catch(() => null);
      if (!r.ok) {
        setStatusMsg(t("plan.error.server", { code: r.status, msg: (j && j.detail) || "Unknown error" }));
        return false;
      }
      setStatusMsg(t("plan.task.complete_ok", { id: taskId }));
      return true;
    } catch (e) {
      setStatusMsg(t("plan.error.network", { msg: e.message }));
      return false;
    }
  };

  const getNextTaskId = (currentBlocks) => {
    let maxNum = 0;
    let template = { prefix: "task_", length: 2 };
    let hasTemplate = false;

    currentBlocks.forEach(b => {
      if (b.type === "task") {
        const match = /`([^`]+)`/.exec(b.content || "");
        if (match) {
          const id = match[1];
          const numMatch = id.match(/^(.*?)(\d+)$/);
          if (numMatch) {
            const prefix = numMatch[1];
            const numStr = numMatch[2];
            const num = parseInt(numStr, 10);
            if (num > maxNum) {
              maxNum = num;
              template = { prefix, length: numStr.length };
              hasTemplate = true;
            }
          }
        }
      }
    });

    if (maxNum > 0 || hasTemplate) {
      const nextNumStr = String(maxNum + 1).padStart(template.length, '0');
      return `${template.prefix}${nextNumStr}`;
    }
    return `task_01`;
  };

  const updateBlock = (id, updates) => {
    if (isLocked) {
      if (updates.checked === true) {
        const block = blocks.find((b) => b.id === id);
        if (block?.type === "task") {
          const meta = parseTaskLine(block.content, block.checked);
          if (meta?.id) {
            setBlocks((prev) => prev.map((b) => (b.id === id ? { ...b, checked: true } : b)));
            void postTaskComplete(meta.id);
          }
        }
      }
      return;
    }
    setBlocks((prev) => prev.map((b) => (b.id === id ? { ...b, ...updates } : b)));
  };

  const addBlock = (afterId, type = "text", content = "") => {
    if (isLocked) return;

    let finalContent = content;
    if (type === "task" && !finalContent.trim()) {
      const nextId = getNextTaskId(blocks);
      finalContent = `\`${nextId}\` `;
    }

    const newBlock = { id: generateId(), type, content: finalContent };
    const index = blocks.findIndex((b) => b.id === afterId);
    const newBlocks = [...blocks];
    newBlocks.splice(index + 1, 0, newBlock);
    setBlocks(newBlocks);
    setFocusedId(newBlock.id);
  };

  const removeBlock = (id) => {
    if (isLocked) return;
    if (blocks.length <= 1) return;
    const index = blocks.findIndex((b) => b.id === id);
    const prevBlock = blocks[index - 1];
    const newBlocks = blocks.filter((b) => b.id !== id);
    setBlocks(newBlocks);
    if (prevBlock) setFocusedId(prevBlock.id);
  };

  const moveFocus = (id, direction) => {
    const index = blocks.findIndex((b) => b.id === id);
    const nextIndex = index + direction;
    if (nextIndex >= 0 && nextIndex < blocks.length) {
      setFocusedId(blocks[nextIndex].id);
    }
  };

  const changeBlockType = (id, type) => {
    if (isLocked) return;
    setBlocks((prev) => {
      let nextId = null;
      if (type === "task") {
        nextId = getNextTaskId(prev);
      }

      return prev.map((b) => {
        if (b.id === id) {
          let newContent = (b.content || "").endsWith("/") ? b.content.slice(0, -1) : b.content;
          if (type === "task" && !/`[^`]+`/.test(newContent)) {
            newContent = `\`${nextId}\` ${newContent}`.trim();
          }
          return { ...b, type, content: newContent };
        }
        return b;
      });
    });
    setShowSlashMenu(null);
  };

  const onApprove = () => {
    const approvedMarkdown = serializeBlocksToCanonicalMarkdown(blocks);
    const todos = todosFromBlocks(blocks);
    postDecision(
      `/internal/orchestration/plans/${encodeURIComponent(planId)}/approve`,
      {
        session_id: sessionId,
        approved_markdown: approvedMarkdown,
        todos,
        annotations: {},
        approve_only: false,
        user_id: userIdProp || undefined,
        profile_name: profileNameProp || undefined,
      },
      t("plan.decision.ok_approved"),
      "approved"
    );
  };

  const onReject = () => {
    postDecision(
      `/internal/orchestration/plans/${encodeURIComponent(planId)}/reject`,
      {
        session_id: sessionId,
        reason: "rejected_from_ui",
      },
      t("plan.decision.ok_rejected"),
      "rejected"
    );
  };

  if (!planId || !sessionId) {
    return (
      <div className="p-4 text-xs text-destructive bg-destructive/10 rounded-2xl border border-destructive/30 m-4">
        {t("plan.missing_props")}
      </div>
    );
  }

  const isExecutingPhase = Boolean(executionRunId || executionProgress);
  const showFooterActions = userDecision === null && !isLocked && !isExecutingPhase;

  const isInterruptedOrPaused =
    isExecutingPhase &&
    executionStatus !== "done" &&
    executionStatus !== "running" &&
    pendingTasks.length > 0;

  const isPartialReview =
    !isExecutingPhase &&
    completedTasks.length > 0 &&
    pendingTasks.length > 0;

  const handleResume = async () => {
    if (isSubmitting) return;
    setIsSubmitting(true);
    setStatusMsg("Ripresa dell'esecuzione del piano in corso...");
    try {
      if (executionRunId) {
        const res = await resumePlanExecution(executionRunId, userIdProp || "default", authToken);
        if (res && res.status !== "error") {
          setIsLocked(true);
          setExecutionStatus("running");
          setStatusMsg("Esecuzione ripresa con successo.");
          setIsSubmitting(false);
          return;
        }
      }
      // Try direct startPlanExecution for approved plan
      const started = await startPlanExecution(
        planId,
        sessionId,
        profileNameProp,
        userIdProp || "default",
        authToken
      );
      if (started && started.run_id) {
        setIsLocked(true);
        setExecutionStatus("running");
        setStatusMsg("Esecuzione avviata con successo.");
        setIsSubmitting(false);
        if (typeof onPlanApproved === "function") {
          onPlanApproved(started.run_id, planId);
        }
        return;
      }
      onApprove();
    } catch (err) {
      console.error("Error resuming plan execution:", err);
      onApprove();
    } finally {
      setIsSubmitting(false);
    }
  };

  const [totalElapsed, setTotalElapsed] = useState(0);
  const executionStartTimeRef = useRef(null);
  const taskTimingsRef = useRef({});
  const [taskTimings, setTaskTimings] = useState({});

  useEffect(() => {
    if (!isExecutingPhase) return;
    if (!executionStartTimeRef.current) {
      executionStartTimeRef.current = Date.now();
    }
    if (executionStatus === "done" || executionStatus === "error") {
      return;
    }
    const timer = setInterval(() => {
      if (executionStartTimeRef.current) {
        setTotalElapsed(Math.max(1, Math.round((Date.now() - executionStartTimeRef.current) / 1000)));
      }
    }, 1000);
    return () => clearInterval(timer);
  }, [isExecutingPhase, executionStatus]);

  useEffect(() => {
    if (!isExecutingPhase) return;

    parsedTasks.forEach((p) => {
      const { meta, block } = p;
      const tid = meta.id;
      if (!tid) return;
      const isDone = Boolean(block.checked || meta.checked);
      const isCurRunning = !isDone && (hlTask === tid || (!hlTask && currentTask?.block.id === block.id));

      const entry = taskTimingsRef.current[tid];

      if (isCurRunning) {
        if (!entry) {
          taskTimingsRef.current[tid] = { start: Date.now(), done: false };
        }
      } else if (isDone) {
        if (entry && !entry.done) {
          const duration = Math.max(1, Math.round((Date.now() - entry.start) / 1000));
          taskTimingsRef.current[tid] = { ...entry, duration, done: true };
          setTaskTimings((prev) => ({ ...prev, [tid]: duration }));
        }
      }
    });

    const taskInterval = setInterval(() => {
      const nextTimings = { ...taskTimingsRef.current };
      const out = {};

      Object.entries(nextTimings).forEach(([tid, timing]) => {
        if (!timing) return;
        if (timing.done) {
          out[tid] = timing.duration;
        } else if (timing.start) {
          out[tid] = Math.max(1, Math.round((Date.now() - timing.start) / 1000));
        }
      });

      setTaskTimings(out);
    }, 1000);

    return () => clearInterval(taskInterval);
  }, [isExecutingPhase, parsedTasks, hlTask, currentTask]);

  return (
    <div className="flex flex-col h-full max-h-full bg-card/60 text-card-foreground overflow-hidden select-text">
      {/* Top Header Section */}
      <div className="flex flex-col gap-2 p-3.5 border-b border-black/[0.06] dark:border-white/[0.08] bg-card/70 backdrop-blur-xl shrink-0">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 min-w-0">
            <span
              className={cn(
                "size-2.5 rounded-full shrink-0",
                isExecutingPhase
                  ? executionStatus === "done"
                    ? "bg-emerald-500"
                    : "bg-orange-500 animate-pulse"
                  : "bg-orange-500"
              )}
            />
            <h3 className="font-bold text-sm text-foreground truncate">
              {isExecutingPhase ? "Esecuzione Piano" : "Piano di Esecuzione"}
            </h3>
          </div>

          <div className="flex items-center gap-2 shrink-0">
            <span className="text-[11px] font-semibold text-muted-foreground">
              {taskProgress.done}/{taskProgress.total} task · {taskProgress.percent}%
            </span>
          </div>
        </div>

        {/* View Switcher Tabs (Panoramica / Avanzamento vs Documento MD) */}
        <div className="flex items-center gap-1 p-0.5 rounded-xl bg-muted/50 border border-black/[0.04] dark:border-white/[0.04]">
          <button
            type="button"
            onClick={() => setPlanViewTab("overview")}
            className={cn(
              "flex-1 flex items-center justify-center gap-1.5 py-1 px-2.5 rounded-lg text-xs font-semibold transition-all",
              planViewTab === "overview"
                ? "bg-background text-foreground shadow-2xs"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            <Workflow size={12} className={planViewTab === "overview" ? "text-orange-500" : ""} />
            <span>{isExecutingPhase ? "Stato Avanzamento" : "Panoramica Piano"}</span>
          </button>
          <button
            type="button"
            onClick={() => setPlanViewTab("document")}
            className={cn(
              "flex-1 flex items-center justify-center gap-1.5 py-1 px-2.5 rounded-lg text-xs font-semibold transition-all",
              planViewTab === "document"
                ? "bg-background text-foreground shadow-2xs"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            <FileText size={12} className={planViewTab === "document" ? "text-orange-500" : ""} />
            <span>Documento MD</span>
          </button>
        </div>
      </div>

      {/* Progress Line */}
      <div className="h-1 w-full bg-muted/60 shrink-0">
        <div
          className={cn(
            "h-full transition-all duration-300",
            taskProgress.percent === 100
              ? "bg-emerald-500"
              : "bg-gradient-to-r from-orange-500 to-amber-500"
          )}
          style={{ width: `${taskProgress.percent}%` }}
        />
      </div>

      {/* Main Body Content */}
      <div className="flex-1 min-h-0 overflow-y-auto custom-scrollbar p-3.5 space-y-3.5">
        {planViewTab === "overview" ? (
          /* ============================================================ */
          /* UNIFIED OVERVIEW / PROGRESS VIEW (ALWAYS IMAGE 2 STYLING)   */
          /* ============================================================ */
          <div className="space-y-3 animate-in fade-in-0 duration-200">
            {/* Execution / Plan Status Banner */}
            <div className="rounded-2xl border border-orange-500/25 bg-orange-500/5 dark:bg-orange-500/10 p-3.5 backdrop-blur-md">
              <div className="flex items-start justify-between gap-2">
                <div className="flex items-center gap-2">
                  {executionStatus === "running" ? (
                    <Loader2 className="size-4 animate-spin text-orange-500 shrink-0" />
                  ) : executionStatus === "done" ? (
                    <CheckCircle2 className="size-4 text-emerald-500 shrink-0" />
                  ) : executionStatus === "error" || userDecision === "rejected" ? (
                    <X className="size-4 text-destructive shrink-0" />
                  ) : (isInterruptedOrPaused || isPartialReview || completedTasks.length > 0) ? (
                    <PauseCircle className="size-4 text-amber-500 shrink-0" />
                  ) : (
                    <Workflow className="size-4 text-orange-500 shrink-0" />
                  )}
                  <span className="font-bold text-xs sm:text-sm text-foreground">
                    {userDecision === "rejected"
                      ? "Piano rifiutato dall'utente"
                      : executionLabel ||
                        (executionStatus === "done"
                          ? "Piano completato con successo"
                          : executionStatus === "running"
                          ? "Esecuzione piano in corso..."
                          : completedTasks.length > 0
                          ? `Piano in pausa (${completedTasks.length}/${parsedTasks.length} completate)`
                          : goalText || "Piano di esecuzione pronto")}
                  </span>
                </div>
                <span
                  className={cn(
                    "text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full shrink-0",
                    userDecision === "rejected"
                      ? "bg-destructive/15 text-destructive border border-destructive/30"
                      : executionStatus === "done"
                      ? "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400"
                      : executionStatus === "running"
                      ? "bg-orange-500/20 text-orange-600 dark:text-orange-400 animate-pulse"
                      : (isInterruptedOrPaused || isPartialReview || completedTasks.length > 0)
                      ? "bg-amber-500/20 text-amber-600 dark:text-amber-400"
                      : "bg-muted text-muted-foreground"
                  )}
                >
                  {userDecision === "rejected"
                    ? "Rifiutato"
                    : executionStatus === "running"
                    ? "In corso"
                    : executionStatus === "done"
                    ? "Completato"
                    : executionStatus === "error"
                    ? "Errore"
                    : (isInterruptedOrPaused || isPartialReview || completedTasks.length > 0)
                    ? "In pausa"
                    : "In attesa"}
                </span>
              </div>

              {/* Goal or Context preview if before start */}
              {goalText && !executionDeliverablePath && completedTasks.length === 0 ? (
                <div className="mt-2.5 pt-2 border-t border-orange-500/15 text-xs text-muted-foreground leading-relaxed">
                  <MdSpan text={goalText} />
                </div>
              ) : null}

              {(executionDeliverablePath || deliverableText) ? (
                <div className="mt-2.5 pt-2 border-t border-orange-500/15 flex items-center justify-between gap-2 text-xs">
                  <span className="font-semibold text-muted-foreground flex items-center gap-1.5">
                    <FileCode size={13} className="text-orange-500" />
                    Deliverable:
                  </span>
                  <code className="font-mono text-[11px] bg-background/80 px-2 py-0.5 rounded border border-border/50 text-foreground truncate max-w-[200px]">
                    {executionDeliverablePath || deliverableText}
                  </code>
                </div>
              ) : null}

              {/* Compact Live Tool Activity Log */}
              {executionActivities.length > 0 && executionStatus !== "done" ? (
                <div className="mt-3 pt-2.5 border-t border-orange-500/15 space-y-1.5">
                  <span className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
                    Attività in tempo reale
                  </span>
                  <ul className="space-y-1 text-xs text-muted-foreground">
                    {executionActivities.slice(-3).map((act, i) => (
                      <li key={`${act.ts || i}-${i}`} className="flex items-center gap-1.5 truncate">
                        <span className="size-1.5 rounded-full bg-orange-500 animate-pulse shrink-0" />
                        <span className="truncate">{act.label || act.message || "Operazione in corso..."}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}

              {/* Quick Resume button inside banner when paused/interrupted */}
              {((isInterruptedOrPaused || isPartialReview) && executionStatus !== "running" && pendingTasks.length > 0) && (
                <div className="mt-3 pt-2.5 border-t border-orange-500/20 flex items-center justify-between gap-2">
                  <span className="text-xs text-muted-foreground font-medium">
                    Piano interrotto ({pendingTasks.length} task da completare)
                  </span>
                  <button
                    type="button"
                    onClick={handleResume}
                    disabled={isSubmitting}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-orange-500 hover:bg-orange-600 active:scale-[0.98] text-white font-semibold text-xs shadow-sm shadow-orange-500/20 transition-all cursor-pointer disabled:opacity-50"
                  >
                    {isSubmitting ? (
                      <Loader2 className="animate-spin size-3.5" />
                    ) : (
                      <Play size={12} className="fill-current" />
                    )}
                    <span>Riprendi</span>
                  </button>
                </div>
              )}
            </div>

            {/* Structured Task List in Execution Style */}
            <div className="space-y-2">
              <div className="flex items-center justify-between px-1">
                <div className="flex items-center gap-2">
                  <span className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground">
                    Avanzamento Task ({parsedTasks.length})
                  </span>
                  {totalElapsed > 0 ? (
                    <span className="inline-flex items-center gap-1 font-mono text-[10.5px] font-semibold px-2 py-0.5 rounded-full bg-muted/80 text-foreground border border-black/[0.06] dark:border-white/[0.08]">
                      <Clock size={10} className="text-orange-500" />
                      {formatDuration(totalElapsed)}
                    </span>
                  ) : null}
                </div>
                <span className="text-[11px] text-muted-foreground font-medium">
                  {completedTasks.length} completate
                </span>
              </div>

              {parsedTasks.map((p, idx) => {
                const { meta, block } = p;
                const isDone = Boolean(block.checked || meta.checked);
                const isCurTarget = !isDone && (hlTask === meta.id || (!hlTask && currentTask?.block.id === block.id));
                const isActivelyRunning = isCurTarget && executionStatus === "running";
                const isPausedTarget = isCurTarget && !isActivelyRunning && (isInterruptedOrPaused || isPartialReview || executionStatus === "paused" || executionStatus === "interrupted" || (completedTasks.length > 0 && executionStatus !== "done"));
                const isPending = !isDone && !isActivelyRunning && !isPausedTarget;
                const desc = descById[meta.id] || "";
                const isSelected = selectedTaskId && meta.id === selectedTaskId;
                const isClickable = typeof onTaskSelect === "function";
                const taskDuration = taskTimings[meta.id];
                const isExpanded = Boolean(expandedTasks[meta.id]);
                const isLongDesc = desc.length > 140;
                const displayDesc = !isExpanded && isLongDesc ? desc.slice(0, 140).trim() + "…" : desc;

                return (
                  <div
                    key={block.id}
                    role={isClickable ? "button" : undefined}
                    tabIndex={isClickable ? 0 : undefined}
                    onClick={isClickable ? () => onTaskSelect(isSelected ? null : meta.id) : undefined}
                    className={cn(
                      "rounded-2xl p-3.5 transition-all duration-200 text-left relative",
                      isActivelyRunning
                        ? "border-2 border-orange-500 bg-orange-500/10 dark:bg-orange-500/15 shadow-md shadow-orange-500/15 ring-2 ring-orange-500/20"
                        : isPausedTarget
                        ? "border-2 border-amber-500/60 bg-amber-500/10 dark:bg-amber-500/15 shadow-sm"
                        : isDone
                        ? "border border-emerald-500/40 bg-emerald-500/5 dark:bg-emerald-500/10"
                        : "border border-black/[0.08] dark:border-white/[0.08] bg-card/40 opacity-75 hover:opacity-100",
                      isClickable && "cursor-pointer hover:-translate-y-0.5 hover:shadow-sm"
                    )}
                  >
                    <div className="flex items-start gap-3">
                      {isDone ? (
                        <CheckCircle2 className="size-5 text-emerald-500 shrink-0 mt-0.5" />
                      ) : isActivelyRunning ? (
                        <Loader2 className="size-5 animate-spin text-orange-500 shrink-0 mt-0.5" />
                      ) : isPausedTarget ? (
                        <PauseCircle className="size-5 text-amber-500 shrink-0 mt-0.5" />
                      ) : (
                        <Circle className="size-5 text-muted-foreground/50 shrink-0 mt-0.5" />
                      )}

                      <div className="flex-1 min-w-0">
                        <div className="flex items-center justify-between gap-2 flex-wrap">
                          <div className="flex items-center gap-1.5 flex-wrap">
                            <span
                              className={cn(
                                "font-mono text-[10px] font-bold px-1.5 py-0.5 rounded",
                                isDone
                                  ? "bg-emerald-500/20 text-emerald-600 dark:text-emerald-400"
                                  : isActivelyRunning
                                  ? "bg-orange-500 text-white"
                                  : isPausedTarget
                                  ? "bg-amber-500 text-white"
                                  : "bg-muted text-muted-foreground"
                              )}
                            >
                              {meta.id || `task_${String(idx + 1).padStart(2, "0")}`}
                            </span>
                            <span
                              className={cn(
                                "text-xs sm:text-sm font-semibold leading-snug",
                                isDone
                                  ? "line-through text-foreground/85"
                                  : isActivelyRunning || isPausedTarget
                                  ? "text-foreground font-bold"
                                  : "text-muted-foreground"
                              )}
                            >
                              <MdSpan text={meta.title} />
                            </span>
                          </div>

                          <div className="flex items-center gap-1.5 shrink-0">
                            {taskDuration != null ? (
                              <span
                                className={cn(
                                  "inline-flex items-center gap-1 font-mono text-[10px] font-semibold px-1.5 py-0.5 rounded-md",
                                  isDone
                                    ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
                                    : isActivelyRunning
                                    ? "bg-orange-500/15 text-orange-600 dark:text-orange-400"
                                    : isPausedTarget
                                    ? "bg-amber-500/15 text-amber-600 dark:text-amber-400"
                                    : "bg-muted text-muted-foreground"
                                )}
                              >
                                <Clock size={9} />
                                {formatDuration(taskDuration)}
                              </span>
                            ) : null}

                            <span
                              className={cn(
                                "text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full",
                                isDone
                                  ? "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border border-emerald-500/30"
                                  : isActivelyRunning
                                  ? "bg-orange-500/20 text-orange-600 dark:text-orange-400 border border-orange-500/30 animate-pulse"
                                  : isPausedTarget
                                  ? "bg-amber-500/20 text-amber-600 dark:text-amber-400 border border-amber-500/30"
                                  : "text-muted-foreground/70 bg-muted/40"
                              )}
                            >
                              {isDone
                                ? "Completata"
                                : isActivelyRunning
                                ? "In corso"
                                : isPausedTarget
                                ? "In pausa"
                                : "In attesa"}
                            </span>
                          </div>
                        </div>

                        {desc ? (
                          <div className="mt-1.5 text-xs text-muted-foreground leading-relaxed">
                            <MdSpan text={displayDesc} />
                            {isLongDesc && (
                              <button
                                type="button"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  toggleTaskExpand(meta.id);
                                }}
                                className="ml-1.5 inline-flex items-center text-[11px] font-semibold text-orange-500 hover:text-orange-600 dark:hover:text-orange-400 underline underline-offset-2 transition-colors cursor-pointer"
                              >
                                {isExpanded ? "Comprimi" : "Espandi"}
                              </button>
                            )}
                          </div>
                        ) : null}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        ) : (
          /* ============================================================ */
          /* DOCUMENT TAB (FULL MARKDOWN VIEW / EDITOR)                   */
          /* ============================================================ */
          <div className="space-y-2 animate-in fade-in-0 duration-200">
            <div className="flex items-center justify-between px-1">
              <span className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground">
                Editor Documento Piano
              </span>
              <span className="text-[10px] text-muted-foreground font-mono">
                {isLocked ? "Sola lettura" : "Modificabile"}
              </span>
            </div>

            <div className="rounded-2xl border border-black/[0.06] dark:border-white/[0.08] bg-card/60 dark:bg-card/40 p-3 space-y-2 shadow-2xs">
              {blocks.map((block) => {
                return (
                  <BlockNode
                    key={block.id}
                    block={block}
                    isFocused={focusedId === block.id}
                    isLocked={isLocked}
                    hlTask={hlTask}
                    showSlashMenu={showSlashMenu === block.id}
                    onFocus={() => setFocusedId(block.id)}
                    updateBlock={updateBlock}
                    addBlock={addBlock}
                    removeBlock={removeBlock}
                    moveFocus={moveFocus}
                    setShowSlashMenu={setShowSlashMenu}
                    changeBlockType={changeBlockType}
                    performUndo={performUndo}
                    performRedo={performRedo}
                    t={t}
                  />
                );
              })}
            </div>
          </div>
        )}
      </div>

      {/* Footer Decisions Banner */}
      {statusMsg ? (
        <div className="p-2.5 text-xs font-medium text-muted-foreground bg-muted/40 border-t border-border/50 text-center">
          {statusMsg}
        </div>
      ) : null}

      {/* Footer Action Buttons */}
      {(showFooterActions || isInterruptedOrPaused || isPartialReview) && pendingTasks.length > 0 && (
        <div className="flex items-center gap-2.5 p-3.5 border-t border-black/[0.06] dark:border-white/[0.08] bg-card/80 backdrop-blur-xl shrink-0 animate-in fade-in-0">
          <button
            type="button"
            onClick={isPartialReview || isInterruptedOrPaused ? handleResume : onApprove}
            disabled={isSubmitting || executionStatus === "running"}
            className={cn(
              "flex-1 flex items-center justify-center gap-2 rounded-xl font-semibold py-2.5 px-4 text-xs sm:text-sm transition-all disabled:opacity-50 shadow-sm cursor-pointer",
              isPartialReview || isInterruptedOrPaused
                ? "bg-orange-500 hover:bg-orange-600 text-white shadow-orange-500/20 active:scale-[0.98]"
                : "bg-emerald-600 hover:bg-emerald-700 text-white shadow-emerald-600/20 active:scale-[0.98]"
            )}
          >
            {isSubmitting ? (
              <>
                <Loader2 className="animate-spin size-4" />
                <span>{isPartialReview || isInterruptedOrPaused ? "Ripresa in corso..." : "Invio..."}</span>
              </>
            ) : isPartialReview || isInterruptedOrPaused ? (
              <>
                <Play size={15} className="fill-current" />
                <span>Riprendi Esecuzione ({pendingTasks.length} rimanenti)</span>
              </>
            ) : (
              <>
                <Check size={16} />
                <span>Approva Piano</span>
              </>
            )}
          </button>
          <button
            type="button"
            onClick={onReject}
            disabled={isSubmitting}
            className="flex-1 flex items-center justify-center gap-2 rounded-xl border border-destructive/40 hover:bg-destructive/10 active:scale-[0.98] text-destructive font-semibold py-2.5 px-4 text-xs sm:text-sm transition-all disabled:opacity-50 cursor-pointer"
          >
            <X size={16} />
            <span>Rifiuta</span>
          </button>
        </div>
      )}
    </div>
  );
}

const BlockNode = React.memo(({
  block,
  isFocused,
  isLocked,
  hlTask,
  showSlashMenu,
  onFocus,
  updateBlock,
  addBlock,
  removeBlock,
  moveFocus,
  setShowSlashMenu,
  changeBlockType,
  performUndo,
  performRedo,
  t,
}) => {
  const textareaRef = React.useRef(null);
  const [menuIndex, setMenuIndex] = React.useState(0);

  const menuOptions = React.useMemo(() => [
    { id: "text", label: t("plan.menu.text") || "Text", icon: <Type className="w-4 h-4" /> },
    { id: "h1", label: t("plan.menu.h1") || "Heading 1", icon: <Heading1 className="w-4 h-4" /> },
    { id: "h2", label: t("plan.menu.h2") || "Heading 2", icon: <Heading2 className="w-4 h-4" /> },
    { id: "h3", label: "Heading 3", icon: <Heading3 className="w-4 h-4" /> },
    { id: "task", label: t("plan.menu.task") || "Task List", icon: <CheckSquare className="w-4 h-4" /> },
    { id: "list", label: "Bullet List", icon: <ListIcon className="w-4 h-4" /> },
    { id: "code", label: t("plan.menu.code") || "Code Block", icon: <CodeIcon className="w-4 h-4" /> },
  ], [t]);

  React.useEffect(() => {
    if (showSlashMenu) setMenuIndex(0);
  }, [showSlashMenu]);

  React.useEffect(() => {
    if (!isFocused) return;
    const raf = requestAnimationFrame(() => {
      if (textareaRef.current && document.activeElement !== textareaRef.current) {
        textareaRef.current.focus();
        const val = textareaRef.current.value;
        textareaRef.current.setSelectionRange(val.length, val.length);
      }
    });
    return () => cancelAnimationFrame(raf);
  }, [isFocused]);

  const adjustHeight = React.useCallback(() => {
    const el = textareaRef.current;
    if (el) {
      el.style.height = "inherit";
      el.style.height = `${el.scrollHeight}px`;
    }
  }, []);

  React.useEffect(() => {
    adjustHeight();
  }, [block.content, adjustHeight]);

  React.useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    const resizeObserver = new ResizeObserver(() => adjustHeight());
    resizeObserver.observe(el);
    return () => resizeObserver.disconnect();
  }, [adjustHeight]);

  const handleKeyDown = (e) => {
    if (isLocked) return;
    const isMod = e.ctrlKey || e.metaKey;
    if (isMod) {
      const lowerKey = e.key.toLowerCase();
      if (lowerKey === "z") {
        e.preventDefault();
        if (e.shiftKey) performRedo();
        else performUndo();
        return;
      } else if (lowerKey === "y") {
        e.preventDefault();
        performRedo();
        return;
      }
    }

    if (showSlashMenu) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setMenuIndex((prev) => (prev + 1) % menuOptions.length);
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setMenuIndex((prev) => (prev - 1 + menuOptions.length) % menuOptions.length);
        return;
      }
      if (e.key === "Enter") {
        e.preventDefault();
        changeBlockType(block.id, menuOptions[menuIndex].id);
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        setShowSlashMenu(null);
        return;
      }
    }

    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      addBlock(block.id, block.type === "task" ? "task" : block.type === "list" ? "list" : "text");
    } else if (e.key === "Backspace" && block.content === "") {
      e.preventDefault();
      removeBlock(block.id);
    } else if (e.key === "ArrowUp") {
      if (textareaRef.current?.selectionStart === 0) {
        e.preventDefault();
        moveFocus(block.id, -1);
      }
    } else if (e.key === "ArrowDown") {
      if (textareaRef.current?.selectionStart === block.content.length) {
        e.preventDefault();
        moveFocus(block.id, 1);
      }
    } else if (e.key === "/") {
      setShowSlashMenu(block.id);
    } else if (e.key === "Escape") {
      setShowSlashMenu(null);
    }
  };

  const handleInput = (e) => {
    if (isLocked) return;
    const val = e.target.value;
    updateBlock(block.id, { content: val });
    if (val === "" && showSlashMenu) {
      setShowSlashMenu(null);
    }
  };

  const inputStyles = {
    width: "100%",
    background: "transparent",
    border: "none",
    outline: "none",
    color: "inherit",
    resize: "none",
    overflow: "hidden",
    padding: 0,
    margin: 0,
    lineHeight: 1.5,
    fontFamily: block.type === "code" ? "ui-monospace, monospace" : "inherit",
    fontSize: block.type === "h1" ? "1.5rem" : block.type === "h2" ? "1.25rem" : block.type === "h3" ? "1.1rem" : "0.875rem",
    fontWeight: block.type.startsWith("h") ? 700 : 400,
    letterSpacing: block.type.startsWith("h") ? "-0.02em" : "normal",
    whiteSpace: "pre-wrap",
    wordBreak: "break-word",
  };

  const taskMeta = block.type === "task" ? parseTaskLine(block.content, block.checked) : null;
  const isHlBlock = !!(taskMeta && hlTask && taskMeta.id === hlTask);
  const useMdMirror = !isFocused && block.type !== "code" && block.type !== "h1" && block.type !== "h2" && block.type !== "h3";

  return (
    <div
      className={cn(
        "group flex items-start gap-2.5 px-2.5 py-1.5 rounded-xl transition-colors relative cursor-text",
        isFocused ? "bg-muted/40 ring-1 ring-primary/20" : "hover:bg-muted/20",
        isHlBlock && "ring-2 ring-orange-500/40 bg-orange-500/5"
      )}
      onClick={(e) => {
        const target = e.target;
        if (target.tagName === "INPUT" && target.type === "checkbox") return;
        if (target.closest && target.closest(".slash-menu-container")) return;
        onFocus();
        if (textareaRef.current && document.activeElement !== textareaRef.current) {
          textareaRef.current.focus();
        }
      }}
    >
      {block.type === "task" && (
        <input
          type="checkbox"
          checked={!!block.checked}
          onChange={(e) => updateBlock(block.id, { checked: e.target.checked })}
          disabled={isLocked && block.checked}
          className="mt-1 size-4 rounded border-gray-300 dark:border-white/20 text-orange-500 focus:ring-orange-500/20 cursor-pointer"
        />
      )}
      {block.type === "list" && (
        <div className="mt-0.5 text-muted-foreground font-bold">•</div>
      )}

      <div className="flex-1 relative min-w-0">
        {useMdMirror && (
          <div
            aria-hidden="true"
            className="absolute inset-0 pointer-events-none select-none text-foreground"
            style={inputStyles}
            dangerouslySetInnerHTML={{ __html: renderInlineMd(block.content) + "\n" }}
          />
        )}
        <textarea
          ref={textareaRef}
          value={block.content}
          onChange={handleInput}
          onKeyDown={handleKeyDown}
          onFocus={onFocus}
          readOnly={isLocked}
          rows={1}
          placeholder={isLocked ? "" : (isFocused ? (t("plan.menu.placeholder") || "Scrivi '/' per comandi...") : "")}
          style={{
            ...inputStyles,
            ...(useMdMirror ? { color: "transparent", caretColor: "hsl(var(--foreground))", WebkitTextFillColor: "transparent" } : {})
          }}
          className="relative z-10 placeholder:text-muted-foreground/50"
          spellCheck={false}
        />

        {showSlashMenu && (
          <div className="absolute top-full left-0 z-50 mt-1 w-52 bg-popover border border-border rounded-xl shadow-2xl p-1 animate-in fade-in zoom-in-95 duration-100">
            {menuOptions.map((item, idx) => (
              <button
                key={item.id}
                onMouseDown={(e) => {
                  e.preventDefault();
                  changeBlockType(block.id, item.id);
                }}
                onMouseEnter={() => setMenuIndex(idx)}
                className={cn(
                  "w-full flex items-center gap-2.5 px-2.5 py-1.5 text-xs rounded-lg transition-colors",
                  idx === menuIndex
                    ? "text-popover-foreground bg-muted font-semibold"
                    : "text-muted-foreground hover:text-popover-foreground hover:bg-muted/50"
                )}
              >
                <div className={cn("p-1 rounded-md", idx === menuIndex ? "bg-primary/15 text-primary" : "text-muted-foreground")}>
                  {item.icon}
                </div>
                <span>{item.label}</span>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
});
BlockNode.displayName = "BlockNode";
