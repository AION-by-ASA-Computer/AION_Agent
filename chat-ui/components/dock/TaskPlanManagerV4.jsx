"use client";
import React from "react";
import { useT } from "@/lib/i18n/use-t";
import { resolvePlanEditorMarkdown, orchestrationPlanToMarkdown } from "@/lib/sse/planDisplay";
import {
  fetchPlanExecutionResult,
  subscribePlanExecutionStream,
} from "@/lib/api/plan-execution";
import {
  Type,
  Heading1,
  Heading2,
  Heading3,
  CheckSquare,
  Code as CodeIcon,
  List as ListIcon,
  Loader2,
} from "lucide-react";
/**
 * Task plan sidebar V4: editor markdown a blocchi come superficie primaria (goal/contesto/avanzamento);
 * anteprima Goal/Task collassabile solo lettura; post-decisione e polling come V3.
 */
/* eslint-disable react-hooks/set-state-in-effect -- sync props/revision/markdown: refactor tracked separately */

function escapeHtml(s) {
  return String(s || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function renderInlineMd(raw) {
  let t = escapeHtml(raw || "");
  t = t.replace(/`([^`]+)`/g, '<code style="font-family:ui-monospace,monospace;font-size:0.9em;padding:0 4px;border-radius:4px;background:hsl(var(--muted)/0.6)">$1</code>');
  // Global passes so multiple **segments** on one line render correctly.
  let prev = "";
  while (prev !== t) {
    prev = t;
    t = t.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  }
  t = t.replace(/(?<!\*)\*([^*]+)\*(?!\*)/g, "<em>$1</em>");
  t = t.replace(
    /\[([^\]]+)\]\((https?:[^)\s]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener noreferrer" style="color:hsl(var(--primary));text-decoration:underline">$1</a>'
  );
  return t;
}

function MdSpan({ text, ...rest }) {
  return <span dangerouslySetInnerHTML={{ __html: renderInlineMd(text || "") }} {...rest} />;
}




const generateId = () => Math.random().toString(36).substr(2, 9);

/** Stable React keys across markdown re-parses (avoids editor flicker on poll/SSE refresh). */
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
  const title = tm ? tm[1].trim() : (normalized || "").trim();
  const dm = /\(deps:\s*([^)]+)\)/.exec(normalized || "");
  const depsRaw = dm ? dm[1].trim() : "";
  const deps =
    depsRaw && !/^none$/i.test(depsRaw) && depsRaw !== "-"
      ? depsRaw.split(",").map((s) => s.trim()).filter(Boolean)
      : [];
  return { id, title, deps, checked, normalized };
};

/** Canonical checkbox body for backend SSOT (`task_01` + bold title + deps). */
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
        case "task":
          taskIndex += 1;
          inTasksSection = true;
          return `- [${b.checked ? "x" : " "}] ${formatCanonicalTaskContent(b.content, taskIndex)}`;
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
      description: "",
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
    onFinalSummary,
    onExecutionAdoptHandled,
    onTaskSelect,
  } = props || {};

  const planId = (rawPlanId || "").trim();
  const sessionId = (rawSessionId || "").trim();

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

    const pushBlock = (block) => {
      const prev = prevBlocks[blockIndex];
      const stable =
        prev &&
        prev.type === block.type &&
        String(prev.content || "") === String(block.content || "") &&
        Boolean(prev.checked) === Boolean(block.checked)
          ? prev.id
          : blockStableId(block, blockIndex);
      newBlocks.push({ ...block, id: stable });
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

      if (line.startsWith("# ")) {
        pushBlock({ type: "h1", content: line.slice(2) });
      } else if (line.startsWith("## ")) {
        pushBlock({ type: "h2", content: line.slice(3) });
      } else if (line.startsWith("### ")) {
        pushBlock({ type: "h3", content: line.slice(4) });
      } else if (/^\s*-\s*\[[ xX]\]\s/.test(line)) {
        const checked = /^\s*-\s*\[[xX]\]/.test(line);
        const content = stripLegacyTaskMeta(line.replace(/^\s*-\s*\[[ xX]\]\s*/, ""));
        pushBlock({ type: "task", content, checked });
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
          case "task":
            return `- [${b.checked ? "x" : " "}] ${b.content}`;
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
    const descLine = /^\s*-\s*Description:\s*(.+)$/;
    for (const line of lines) {
      const tm = taskLine.exec(line);
      if (tm) {
        lastId = tm[1].trim();
        continue;
      }
      const dm = descLine.exec(line);
      if (dm && lastId) map[lastId] = dm[1].trim();
    }
    return map;
  };

  const [blocks, setBlocks] = React.useState([]);
  const [focusedId, setFocusedId] = React.useState(null);
  const [statusMsg, setStatusMsg] = React.useState("");
  const [isSubmitting, setIsSubmitting] = React.useState(false);
  const [showSlashMenu, setShowSlashMenu] = React.useState(null);
  const [baseMarkdown, setBaseMarkdown] = React.useState("");
  const [lastAppliedRevision, setLastAppliedRevision] = React.useState(0);
  const [revisionNotice, setRevisionNotice] = React.useState("");
  const [isLocked, setIsLocked] = React.useState(false);
  const [userDecision, setUserDecision] = React.useState(null);
  const [previewExpanded, setPreviewExpanded] = React.useState(false);
  const [showCompleted, setShowCompleted] = React.useState(false);
  const [planSnapshot, setPlanSnapshot] = React.useState(initialPlan || {});
  const [hlTask, setHlTask] = React.useState((hlProp || "").trim());
  const [executionLabel, setExecutionLabel] = React.useState("");
  const [executionActivities, setExecutionActivities] = React.useState([]);
  const [executionStatus, setExecutionStatus] = React.useState("");
  const [executionDeliverablePath, setExecutionDeliverablePath] = React.useState("");

  // Undo/Redo history stack refs
  const historyRef = React.useRef([]);
  const historyPointerRef = React.useRef(-1);
  const isUndoRedoActionRef = React.useRef(false);
  const executionFinalHandledRef = React.useRef(false);
  const onFinalSummaryRef = React.useRef(onFinalSummary);
  const onExecutionAdoptHandledRef = React.useRef(onExecutionAdoptHandled);

  React.useEffect(() => {
    onFinalSummaryRef.current = onFinalSummary;
  }, [onFinalSummary]);

  React.useEffect(() => {
    onExecutionAdoptHandledRef.current = onExecutionAdoptHandled;
  }, [onExecutionAdoptHandled]);

  const emitExecutionFinalOnce = React.useCallback(
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

  React.useEffect(() => {
    const h = (hlProp || "").trim();
    if (h) setHlTask(h);
  }, [hlProp]);

  React.useEffect(() => {
    if (initialPlan && typeof initialPlan === "object") setPlanSnapshot(initialPlan);
  }, [initialPlan, revision]);

  const fallbackFromPlan = React.useMemo(
    () => planJsonToMarkdown(initialPlan, t),
    [initialPlan, t]
  );

  const resolvedInitialMarkdown = React.useMemo(
    () =>
      resolvePlanEditorMarkdown(initialMarkdown, initialPlan, planLabels(t)) ||
      fallbackFromPlan ||
      `# ${t("plan.fallback.title")}\n\n## ${t("plan.fallback.goal")}\n${t("plan.fallback.goal")}\n\n## ${t("plan.fallback.tasks")}\n`,
    [initialMarkdown, initialPlan, fallbackFromPlan, t]
  );

  React.useEffect(() => {
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
      const parsed = parseMarkdownToBlocks(nextMarkdown, prev);
      return parsed;
    });
    setBaseMarkdown(nextMarkdown);
    setLastAppliedRevision(incomingRev);
    setRevisionNotice(incomingRev > 1 ? t("plan.notice.updated", { rev: incomingRev }) : "");
  }, [resolvedInitialMarkdown, revision, t]);

  React.useEffect(() => {
    if (executionProgress) {
      setIsLocked(true);
      setPreviewExpanded(true);
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
    setPreviewExpanded(true);
    let cancelled = false;
    const unsub = subscribePlanExecutionStream(
      runId,
      userIdProp,
      authToken,
      (ev) => {
        if (cancelled) return;
        const label = ev.label || ev.message || "";
        if (label) setExecutionLabel(label);
        if (ev.status) setExecutionStatus(ev.status);
        if (ev.task_id) setHlTask(String(ev.task_id));
        if (ev.activities?.length) {
          setExecutionActivities(ev.activities);
        } else if (label) {
          setExecutionActivities((prev) => [
            ...prev,
            {
              label,
              message: ev.message,
              task_id: ev.task_id,
              ts: Date.now() / 1000,
            },
          ].slice(-40));
        }
        if (ev.error) {
          setExecutionLabel(ev.error);
          setExecutionStatus("error");
        }
      },
      () => {
        if (cancelled) return;
        emitExecutionFinalOnce(runId);
      },
    );
    return () => {
      cancelled = true;
      unsub();
    };
  }, [executionRunId, executionProgress, userIdProp, authToken, planId, emitExecutionFinalOnce]);

  React.useEffect(() => {
    executionFinalHandledRef.current = false;
  }, [executionRunId]);

  React.useEffect(() => {
    if (!executionProgress?.done) return undefined;
    const runId = (executionRunId || "").trim();
    if (!runId || !userIdProp) return undefined;
    emitExecutionFinalOnce(runId);
    return undefined;
  }, [executionProgress?.done, executionRunId, userIdProp, emitExecutionFinalOnce]);

  // Track blocks state changes for Undo/Redo history
  React.useEffect(() => {
    if (isUndoRedoActionRef.current) {
      isUndoRedoActionRef.current = false;
      return;
    }

    if (!blocks || blocks.length === 0) return;

    // Prune the future history stack if we had undone some actions and then made a new edit
    const currentHistory = historyRef.current.slice(0, historyPointerRef.current + 1);

    // Check if the current state is identical to the last state in the history stack to avoid duplicate entries
    const lastState = currentHistory[currentHistory.length - 1];
    if (lastState && JSON.stringify(lastState) === JSON.stringify(blocks)) {
      return;
    }

    const nextHistory = [...currentHistory, blocks];
    if (nextHistory.length > 50) {
      nextHistory.shift();
    }
    historyRef.current = nextHistory;
    historyPointerRef.current = nextHistory.length - 1;
  }, [blocks]);

  React.useEffect(() => {
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

  const currentMarkdown = React.useMemo(() => serializeBlocksToMarkdown(blocks), [blocks]);
  const isDirty = currentMarkdown !== baseMarkdown;

  const descById = React.useMemo(() => {
    const fromLegacy = extractLegacyDescriptions(currentMarkdown);
    const m = { ...fromLegacy };
    (planSnapshot.tasks || []).forEach((t) => {
      if (t && t.id) {
        const d = String(t.description || "").trim();
        if (d) m[String(t.id)] = d;
      }
    });
    return m;
  }, [planSnapshot, currentMarkdown]);

  const goalText = React.useMemo(() => extractSection(currentMarkdown, t("plan.fallback.goal")), [currentMarkdown, t]);
  const contextText = React.useMemo(() => extractSection(currentMarkdown, t("plan.fallback.context")), [currentMarkdown, t]);
  const notesText = React.useMemo(() => extractSection(currentMarkdown, t("plan.fallback.notes")), [currentMarkdown, t]);

  const taskBlocks = React.useMemo(() => (blocks || []).filter((b) => b.type === "task"), [blocks]);
  const parsedTasks = React.useMemo(
    () => taskBlocks.map((b) => ({ block: b, meta: parseTaskLine(b.content, b.checked) })),
    [taskBlocks]
  );
  const completedTasks = React.useMemo(() => parsedTasks.filter((p) => p.meta.checked), [parsedTasks]);
  const pendingTasks = React.useMemo(() => parsedTasks.filter((p) => !p.meta.checked), [parsedTasks]);
  const currentTask = pendingTasks[0] || null;

  const taskProgress = React.useMemo(() => {
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
      if (path.endsWith("/approve")) setIsLocked(true);
      setUserDecision(decisionKind);
      setStatusMsg(okText);
      if (
        path.endsWith("/approve") &&
        decisionKind === "approved" &&
        typeof onPlanApproved === "function" &&
        j &&
        j.run_id
      ) {
        const rid = String(j.run_id || "").trim();
        const pid = String(j.plan_id || planId || "").trim();
        if (rid && pid) onPlanApproved(rid, pid);
      }
    } catch (e) {
      setStatusMsg(t("plan.error.network", { msg: e.message }));
    } finally {
      setIsSubmitting(false);
    }
  };

  const performUndo = React.useCallback(() => {
    if (historyPointerRef.current > 0) {
      historyPointerRef.current -= 1;
      const prevState = historyRef.current[historyPointerRef.current];
      isUndoRedoActionRef.current = true;
      setBlocks(prevState);
    }
  }, []);

  const performRedo = React.useCallback(() => {
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

  const onCompleteAllTasks = async () => {
    setIsSubmitting(true);
    setStatusMsg(t("plan.task.completing_all"));
    const base = (apiBase || "").replace(/\/$/, "");
    const headers = {
      "Content-Type": "application/json",
      "X-AION-User-Id": userIdProp || "default",
    };
    if (authToken) headers.Authorization = `Bearer ${authToken}`;
    try {
      const r = await fetch(
        `${base}/internal/orchestration/plans/${encodeURIComponent(planId)}/tasks/complete-all`,
        {
          method: "POST",
          headers,
          body: JSON.stringify({ session_id: sessionId }),
        }
      );
      const j = await r.json().catch(() => null);
      if (!r.ok) {
        setStatusMsg(t("plan.error.server", { code: r.status, msg: (j && j.detail) || "Unknown error" }));
        return;
      }
      const n = Array.isArray(j?.completed) ? j.completed.length : 0;
      setStatusMsg(t("plan.task.complete_all_ok", { count: n }));
    } catch (e) {
      setStatusMsg(t("plan.error.network", { msg: e.message }));
    } finally {
      setIsSubmitting(false);
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

  const onApproveDraft = () => {
    postDecision(
      `/internal/orchestration/plans/${encodeURIComponent(planId)}/approve`,
      {
        session_id: sessionId,
        approve_only: true,
      },
      t("plan.decision.ok_approved_draft"),
      "approved_draft"
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

  const sectionBox = {
    padding: "10px 14px",
    borderBottom: "1px solid hsl(var(--border))",
    fontSize: 13,
    lineHeight: 1.55,
    color: "hsl(var(--foreground))",
  };

  /** Anteprima sola lettura (nessun checkbox: modificare solo nell'editor a blocchi). */
  const renderPreviewTaskCard = (p, { emphasize }) => {
    const { meta, block } = p;
    const desc = descById[meta.id] || "";
    const isHl = hlTask && meta.id === hlTask;
    const isSelected = selectedTaskId && meta.id === selectedTaskId;
    const isCurrent = emphasize && currentTask && block.id === currentTask.block.id;
    const clickable = !!(executionRunId && typeof onTaskSelect === "function" && meta.id);
    const handleTaskClick = () => {
      if (!clickable) return;
      onTaskSelect(isSelected ? null : meta.id);
    };
    return (
      <div
        key={block.id}
        role={clickable ? "button" : undefined}
        tabIndex={clickable ? 0 : undefined}
        title={clickable ? "Apri chat della task" : undefined}
        onClick={clickable ? handleTaskClick : undefined}
        onKeyDown={
          clickable
            ? (e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  handleTaskClick();
                }
              }
            : undefined
        }
        style={{
          marginBottom: 10,
          padding: "10px 12px",
          borderRadius: "calc(var(--radius, 0.875rem) - 2px)",
          border:
            isCurrent || isHl || isSelected
              ? "1px solid hsl(var(--primary))"
              : "1px solid hsl(var(--border))",
          background: isCurrent ? "hsl(var(--muted) / 0.45)" : "hsl(var(--card))",
          boxShadow: isHl || isSelected ? "0 0 0 2px hsl(var(--primary) / 0.25)" : "none",
          transition: "border 0.15s ease, box-shadow 0.15s ease",
          cursor: clickable ? "pointer" : undefined,
        }}
      >
        <div style={{ display: "flex", alignItems: "flex-start", gap: 10 }}>
          <div
            aria-hidden
            style={{
              marginTop: 4,
              fontSize: 11,
              fontWeight: 700,
              fontFamily: "ui-monospace, monospace",
              color: "hsl(var(--muted-foreground))",
              minWidth: 36,
            }}
          >
            {meta.checked ? "[x]" : "[ ]"}
          </div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontWeight: 600, fontSize: 13, letterSpacing: "-0.02em" }}>
              <MdSpan text={meta.title} />
              {meta.id ? (
                <code style={{ fontWeight: 500, color: "hsl(var(--muted-foreground))", marginLeft: 8 }}>
                  {meta.id}
                </code>
              ) : null}
            </div>
            {meta.profile ? (
              <div style={{ fontSize: 11, color: "hsl(var(--muted-foreground))", marginTop: 4 }}>
                {t("plan.meta.profile")}: <MdSpan text={meta.profile} />
              </div>
            ) : null}
            {meta.deps && meta.deps.length ? (
              <div style={{ marginTop: 8, display: "flex", flexWrap: "wrap", gap: 6 }}>
                {meta.deps.map((d) => (
                  <span
                    key={d}
                    style={{
                      fontSize: 10,
                      padding: "2px 8px",
                      borderRadius: 999,
                      background: "hsl(var(--muted))",
                      color: "hsl(var(--muted-foreground))",
                      fontWeight: 600,
                    }}
                  >
                    {t("plan.meta.dep")}: {d}
                  </span>
                ))}
              </div>
            ) : null}
            {desc ? (
              <div style={{ marginTop: 8, fontSize: 12, color: "hsl(var(--muted-foreground))" }}>
                <MdSpan text={desc} />
              </div>
            ) : null}
          </div>
        </div>
      </div>
    );
  };

  if (!planId || !sessionId) {
    return (
      <div
        style={{
          padding: 12,
          fontSize: 13,
          color: "hsl(var(--destructive))",
          background: "hsl(var(--muted))",
          borderRadius: "var(--radius, 0.875rem)",
          border: "1px solid hsl(var(--border))",
        }}
      >
        {t("plan.missing_props")}
      </div>
    );
  }

  const decisionBanner =
    userDecision === "approved"
      ? t("plan.decision.approved")
      : userDecision === "approved_draft"
        ? t("plan.decision.approved_draft")
        : userDecision === "rejected"
          ? t("plan.decision.rejected")
          : null;

  const showFooterActions = userDecision === null && !isLocked;
  const showProgressActions = isLocked;

  return (
    <div style={containerStyle}>
      <div style={headerStyle}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <div style={dotStyle} />
          <div style={{ fontWeight: 600, fontSize: 14, letterSpacing: "-0.02em", color: "hsl(var(--foreground))" }}>
            {t("plan.title")}
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{ fontSize: 11, color: "hsl(var(--muted-foreground))", fontWeight: 500 }}>
            {taskProgress.done}/{taskProgress.total} {t("plan.tasks")} · {taskProgress.percent}%
          </div>
          <div
            style={{
              fontSize: 11,
              color: isDirty ? "hsl(var(--chart-5))" : "hsl(var(--muted-foreground))",
              fontWeight: 600,
            }}
          >
            {(isLocked ? t("plan.status.locked") : isDirty ? t("plan.status.dirty") : t("plan.status.ok"))} · {t("plan.status.revision")} {lastAppliedRevision || revision || 1}
          </div>
        </div>
      </div>

      <div style={progressBarWrapStyle}>
        <div style={{ ...progressBarFillStyle, width: `${taskProgress.percent}%` }} />
      </div>

      {executionRunId ? (
        <div
          style={{
            padding: "10px 14px",
            borderBottom: "1px solid hsl(var(--border))",
            background: "hsl(var(--muted) / 0.35)",
            fontSize: 12,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: executionActivities.length ? 8 : 0 }}>
            {executionStatus !== "done" && executionStatus !== "error" ? (
              <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-primary" />
            ) : null}
            <span style={{ fontWeight: 600, color: "hsl(var(--foreground))" }}>
              {executionLabel || t("plan.execution.running")}
            </span>
          </div>
          {executionDeliverablePath ? (
            <div style={{ marginTop: 6, fontSize: 11, color: "hsl(var(--muted-foreground))" }}>
              <span style={{ fontWeight: 600, color: "hsl(var(--foreground))" }}>
                {t("plan.execution.deliverable")}:
              </span>{" "}
              <code style={{ fontFamily: "ui-monospace, monospace", fontSize: 10 }}>
                {executionDeliverablePath}
              </code>
            </div>
          ) : null}
          {executionActivities.length ? (
            <ul style={{ margin: 0, padding: "0 0 0 16px", color: "hsl(var(--muted-foreground))", lineHeight: 1.45 }}>
              {executionActivities.slice(-6).map((act, i) => (
                <li key={`${act.ts || i}-${act.label || act.message || i}`}>
                  {act.label || act.message || ""}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}

      <div
        style={{
          flex: 1,
          minHeight: 0,
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
        }}
      >
        <div
          style={{
            ...editorContainerStyle,
            flex: 1,
            minHeight: 0,
            overflowY: "auto",
            borderBottom: "1px solid hsl(var(--border))",
          }}
          onBlur={(e) => {
            // Only clear focusedId when focus moves OUTSIDE the editor container.
            // When moving between blocks inside the editor, relatedTarget is still
            // inside this div, so we skip clearing to avoid the race condition.
            if (!e.currentTarget.contains(e.relatedTarget)) {
              setFocusedId(null);
            }
          }}
        >
          {blocks.map((block) => {
            const taskMeta = block.type === "task" ? parseTaskLine(block.content, block.checked) : null;
            const taskDesc = taskMeta?.id ? descById[taskMeta.id] || "" : "";
            return (
            <BlockNode
              key={block.id}
              block={block}
              isFocused={focusedId === block.id}
              isLocked={isLocked}
              hlTask={hlTask}
              taskDescription={taskDesc}
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

        <div style={{ padding: "8px 12px", flexShrink: 0, borderBottom: previewExpanded ? "1px solid hsl(var(--border))" : "none" }}>
          <button
            type="button"
            onClick={() => setPreviewExpanded(!previewExpanded)}
            style={{
              background: "transparent",
              border: "none",
              color: "hsl(var(--primary))",
              cursor: "pointer",
              fontSize: 12,
              fontWeight: 600,
            }}
          >
            {t("plan.preview.title")} {previewExpanded ? "▼" : "▶"}
          </button>
        </div>

        {previewExpanded ? (
          <div
            style={{
              maxHeight: "38vh",
              overflowY: "auto",
              flexShrink: 0,
              display: "flex",
              flexDirection: "column",
            }}
          >
            <div style={{ fontSize: 10, color: "hsl(var(--muted-foreground))", padding: "6px 14px 0", fontStyle: "italic" }}>
              {t("plan.preview.edit_hint")}
            </div>
            {goalText ? (
              <div style={sectionBox}>
                <div style={{ fontWeight: 700, fontSize: 11, textTransform: "uppercase", marginBottom: 6, opacity: 0.85 }}>
                  {t("plan.fallback.goal")}
                </div>
                <div style={{ whiteSpace: "pre-wrap" }}>
                  <MdSpan text={goalText} />
                </div>
              </div>
            ) : null}

            {contextText ? (
              <div style={sectionBox}>
                <div style={{ fontWeight: 700, fontSize: 11, textTransform: "uppercase", marginBottom: 6, opacity: 0.85 }}>
                  {t("plan.fallback.context")}
                </div>
                <div style={{ whiteSpace: "pre-wrap" }}>
                  <MdSpan text={contextText} />
                </div>
              </div>
            ) : null}

            <div style={{ ...sectionBox, borderBottom: notesText ? undefined : "none" }}>
              <div style={{ fontWeight: 700, fontSize: 11, textTransform: "uppercase", marginBottom: 10, opacity: 0.85 }}>
                {t("plan.fallback.tasks")}
              </div>

              {completedTasks.length ? (
                <div style={{ marginBottom: 12 }}>
                  <button
                    type="button"
                    onClick={() => setShowCompleted(!showCompleted)}
                    style={{
                      background: "transparent",
                      border: "none",
                      color: "hsl(var(--primary))",
                      cursor: "pointer",
                      fontSize: 12,
                      fontWeight: 600,
                      padding: 0,
                      marginBottom: 8,
                    }}
                  >
                    {t("plan.preview.completed")} ({completedTasks.length}) {showCompleted ? "▼" : "▶"}
                  </button>
                  {showCompleted ? completedTasks.map((p) => renderPreviewTaskCard(p, { emphasize: false })) : null}
                </div>
              ) : null}

              {currentTask ? (
                <div style={{ marginBottom: 8 }}>
                  <div style={{ fontSize: 11, color: "hsl(var(--muted-foreground))", marginBottom: 8, fontWeight: 600 }}>
                    {t("plan.preview.active")}
                  </div>
                  {renderPreviewTaskCard(currentTask, { emphasize: true })}
                </div>
              ) : null}

              {pendingTasks.length > 1 ? (
                <div>
                  <div style={{ fontSize: 11, color: "hsl(var(--muted-foreground))", marginBottom: 8, fontWeight: 600 }}>
                    {t("plan.preview.next")}
                  </div>
                  {pendingTasks.slice(1).map((p) => renderPreviewTaskCard(p, { emphasize: false }))}
                </div>
              ) : null}

              {!pendingTasks.length && !completedTasks.length ? (
                <div style={{ fontSize: 12, color: "hsl(var(--muted-foreground))" }}>{t("plan.preview.no_tasks")}</div>
              ) : null}
            </div>

            {notesText ? (
              <div style={{ ...sectionBox, borderTop: "1px solid hsl(var(--border))" }}>
                <div style={{ fontWeight: 700, fontSize: 11, textTransform: "uppercase", marginBottom: 6, opacity: 0.85 }}>
                  {t("plan.fallback.notes")}
                </div>
                <div style={{ whiteSpace: "pre-wrap" }}>
                  <MdSpan text={notesText} />
                </div>
              </div>
            ) : null}
          </div>
        ) : null}
      </div>

      {decisionBanner ? (
        <div style={{ ...statusBannerStyle, background: "hsl(var(--muted) / 0.5)", fontWeight: 600 }}>
          {decisionBanner}
        </div>
      ) : null}

      {showFooterActions ? (
        <div style={footerStyle}>
          <button onClick={onApprove} disabled={isSubmitting} style={btnPrimaryStyle}>
            {isSubmitting ? t("plan.actions.sending") : t("plan.actions.approve")}
          </button>
          <button onClick={onApproveDraft} disabled={isSubmitting} style={btnSecondaryStyle}>
            {t("plan.actions.original")}
          </button>
          <button onClick={onReject} disabled={isSubmitting} style={btnDangerStyle}>
            {t("plan.actions.reject")}
          </button>
          <div style={{ marginLeft: "auto", fontSize: 10, color: "hsl(var(--muted-foreground))", fontWeight: 500 }}>
            {blocks.length} {t("plan.blocks")} · {currentMarkdown.length} {t("plan.chars")}
          </div>
        </div>
      ) : null}

      {showProgressActions && pendingTasks.length > 0 ? (
        <div style={footerStyle}>
          <button
            type="button"
            onClick={() => void onCompleteAllTasks()}
            disabled={isSubmitting}
            style={btnPrimaryStyle}
          >
            {isSubmitting ? t("plan.actions.sending") : t("plan.actions.complete_all")}
          </button>
          <div style={{ marginLeft: "auto", fontSize: 10, color: "hsl(var(--muted-foreground))", fontWeight: 500 }}>
            {taskProgress.done}/{taskProgress.total} {t("plan.task.progress")}
          </div>
        </div>
      ) : null}

      {statusMsg ? <div style={statusBannerStyle}>{statusMsg}</div> : null}
      {!statusMsg && revisionNotice ? <div style={statusBannerStyle}>{revisionNotice}</div> : null}
    </div>
  );
}

const containerStyle = {
  display: "flex",
  flexDirection: "column",
  height: "100%",
  maxHeight: "100%",
  background: "hsl(var(--card))",
  color: "hsl(var(--card-foreground))",
  fontFamily: "var(--font-sans, 'Inter', ui-sans-serif, system-ui, sans-serif)",
  borderRadius: "0",
  border: "0px solid hsl(var(--border))",
  overflow: "hidden",
};

const headerStyle = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "center",
  padding: "12px 16px",
  borderBottom: "1px solid hsl(var(--border))",
  background: "hsl(var(--card))",
};

const progressBarWrapStyle = {
  height: 4,
  width: "100%",
  background: "hsl(var(--muted))",
  borderBottom: "1px solid hsl(var(--border))",
};

const progressBarFillStyle = {
  height: "100%",
  background: "hsl(var(--primary))",
  transition: "width 0.25s ease",
};

const dotStyle = {
  width: 8,
  height: 8,
  borderRadius: "50%",
  background: "hsl(var(--primary))",
};

const editorContainerStyle = {
  flex: 1,
  padding: "16px 8px",
  overflowY: "auto",
  overflowX: "hidden",
  display: "flex",
  flexDirection: "column",
  gap: 2,
  background: "transparent",
};

const footerStyle = {
  display: "flex",
  alignItems: "center",
  gap: 10,
  padding: "12px 16px",
  background: "hsl(var(--muted) / 0.25)",
  borderTop: "1px solid hsl(var(--border))",
};

const btnPrimaryStyle = {
  background: "hsl(var(--primary))",
  color: "hsl(var(--primary-foreground))",
  border: "none",
  padding: "8px 14px",
  borderRadius: "calc(var(--radius, 0.875rem) - 2px)",
  fontWeight: 600,
  fontSize: 12,
  cursor: "pointer",
};

const btnSecondaryStyle = {
  background: "hsl(var(--secondary))",
  color: "hsl(var(--secondary-foreground))",
  border: "1px solid hsl(var(--border))",
  padding: "8px 14px",
  borderRadius: "calc(var(--radius, 0.875rem) - 2px)",
  fontWeight: 600,
  fontSize: 12,
  cursor: "pointer",
};

const btnDangerStyle = {
  background: "transparent",
  color: "hsl(var(--destructive))",
  border: "1px solid hsl(var(--destructive) / 0.35)",
  padding: "8px 14px",
  borderRadius: "calc(var(--radius, 0.875rem) - 2px)",
  fontWeight: 600,
  fontSize: 12,
  cursor: "pointer",
};

const statusBannerStyle = {
  padding: "10px 16px",
  background: "hsl(var(--muted) / 0.35)",
  borderTop: "1px solid hsl(var(--border))",
  fontSize: 12,
  color: "hsl(var(--muted-foreground))",
  fontWeight: 500,
};

const slashMenuStyles = {
  position: "absolute",
  top: "100%",
  left: 0,
  zIndex: 100,
  background: "hsl(var(--popover))",
  border: "1px solid hsl(var(--border))",
  borderRadius: "calc(var(--radius, 0.875rem) - 4px)",
  padding: 4,
  minWidth: 160,
  boxShadow: "0 8px 24px rgba(0, 0, 0, 0.12)",
};

const slashItemStyle = {
  padding: "8px 12px",
  fontSize: 13,
  borderRadius: 4,
  cursor: "pointer",
  color: "hsl(var(--popover-foreground))",
};

const BlockNode = React.memo(({
  block,
  isFocused,
  isLocked,
  hlTask,
  taskDescription,
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
    // rAF ensures DOM is ready before focusing
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
    lineHeight: 1.6,
    fontFamily: block.type === "code" ? "ui-monospace, monospace" : "inherit",
    fontSize: block.type === "h1" ? "1.875rem" : block.type === "h2" ? "1.5rem" : block.type === "h3" ? "1.25rem" : "1rem",
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
      className={`group flex items-start gap-3 px-3 py-1.5 rounded-lg transition-colors relative cursor-text ${isFocused ? "bg-black/5 dark:bg-white/5" : "hover:bg-black/5 dark:hover:bg-white/5"} ${isHlBlock ? "ring-2 ring-blue-500/35" : ""}`}
      onClick={(e) => {
        const target = e.target;
        // Don't intercept checkbox clicks
        if (target.tagName === "INPUT" && target.type === "checkbox") return;
        // Don't intercept slash-menu clicks
        if (target.closest && target.closest(".slash-menu-container")) return;
        // Trigger focus: onFocus() updates state, then rAF focuses the textarea
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
          className="mt-1.5 w-4 h-4 rounded border-gray-300 dark:border-white/20 bg-white dark:bg-black/40 text-blue-500 focus:ring-blue-500/20 cursor-pointer disabled:opacity-50"
        />
      )}
      {block.type === "list" && (
        <div className="mt-1.5 text-gray-500">•</div>
      )}

      <div className="flex-1 relative min-w-0">
        {useMdMirror && (
          <div
            aria-hidden="true"
            className="absolute inset-0 pointer-events-none select-none text-gray-900 dark:text-gray-100"
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
          placeholder={isLocked ? "" : (isFocused ? (t("plan.menu.placeholder") || "Type '/' for commands...") : "")}
          style={{
            ...inputStyles,
            ...(useMdMirror ? { color: "transparent", caretColor: "hsl(var(--foreground))", WebkitTextFillColor: "transparent" } : {})
          }}
          className={`relative z-10 placeholder:text-gray-400 dark:placeholder:text-gray-600`}
          spellCheck={false}
        />

        {block.type === "task" && taskDescription && !isFocused ? (
          <div
            style={{
              marginTop: 6,
              fontSize: 12,
              lineHeight: 1.45,
              color: "hsl(var(--muted-foreground))",
            }}
          >
            <MdSpan text={taskDescription} />
          </div>
        ) : null}

        {showSlashMenu && (
          <div className="absolute top-full left-0 z-50 mt-1 w-56 bg-white dark:bg-[#1a1a1a] border border-gray-200 dark:border-white/10 rounded-xl shadow-2xl p-1 animate-in fade-in zoom-in-95 duration-100">
            {menuOptions.map((item, idx) => (
              <button
                key={item.id}
                onMouseDown={(e) => {
                  e.preventDefault(); // Prevents textarea from losing focus and closing the menu
                  changeBlockType(block.id, item.id);
                }}
                onMouseEnter={() => setMenuIndex(idx)}
                className={`w-full flex items-center gap-3 px-3 py-2 text-sm rounded-lg transition-colors ${idx === menuIndex ? "text-gray-900 dark:text-white bg-gray-100 dark:bg-white/10" : "text-gray-600 dark:text-gray-300 hover:text-gray-900 dark:hover:text-white hover:bg-gray-50 dark:hover:bg-white/5"
                  }`}
              >
                <div className={`p-1.5 rounded-md transition-colors ${idx === menuIndex ? "bg-blue-100 dark:bg-blue-500/20 text-blue-600 dark:text-blue-400" : "bg-gray-100 dark:bg-white/5 text-gray-500 dark:text-gray-400"
                  }`}>
                  {item.icon}
                </div>
                {item.label}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
});
BlockNode.displayName = "BlockNode";

