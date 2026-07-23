"use client";

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, memo } from "react";
import { useSearchParams } from "next/navigation";
import dynamic from "next/dynamic";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import { Loader2, Send, Square, Sparkles, Paperclip, Plus, ChevronRight, User, Check, ChevronDown, X, Wrench, Pencil, Globe, GlobeLock, Settings, Download, AlertCircle, FileText, AlertTriangle, MessageSquare, HelpCircle, Bug, Database, BookOpen, Brain, ThumbsDown } from "lucide-react";
import { apiBase } from "@/lib/config";
import {
  AION_CHAT_STREAM_DEBUG_ENABLED,
  AION_PROMPT_DEBUG_UI_ENABLED,
} from "@/lib/dev-flags";
import { ShimmerText } from "@/components/chat/ShimmerText";
import Link from "next/link";
import { AgentModeSelectChip } from "@/components/chat/AgentModeSelectChip";
import { ChatEmptyState } from "@/components/chat/ChatEmptyState";
import { ComposerOptionRow } from "@/components/chat/ComposerOptionRow";
import { ChatDragDrop } from "@/components/chat/ChatDragDrop";
import { mergeAttachmentRefs } from "@/lib/attachments";
import { artifactLanguage } from "@/lib/artifacts";
import {
  baseUserHeaders,
  jsonHeaders,
  chatStop,
  consumeChatStream,
  drainSessionEventsLoop,
  fetchProfiles,
  fetchSessionCharts,
  listSessionFilesSubdir,
  type SessionFileRow,
  openSessionEventsStream,
  postChatStream,
  waitForChatPrepare,
  type ChatPrepareMcpError,
  sessionDownloadUrl,
  uploadSessionFiles,
  listSessionUploads,
  fetchConversationHistory,
  fetchStreamStatus,
  getChatStreamReconnect,
  fetchConversationDetails,
  updateConversationMetadata,
  updateConversationProfile,
  updateConversationTitle,
  patchMessageTimeline,
  rateMessage,
  saveAssistantMessage,
  saveChatMessage,
  fetchKhubFileContent,
  fetchPromptSnapshots,
  type ChatHistoryArtifact,
  type ChatHistoryMessage,
  type ChatHistoryStep,
  type ProfileRow,
  type SessionChart,
} from "@/lib/api/aion";
import { useStoredToken, useStoredUserId } from "@/lib/auth/use-stored-auth";
import { useT } from "@/lib/i18n/use-t";
import {
  extractStreamingPlanMarkdown,
  normalizePlanPendingChunk,
  planFromOrchestrationEvent,
  stripPlanBlocksForChatDisplay,
} from "@/lib/sse/planDisplay";
import {
  reduceChunk,
  newTurn,
  segmentsForMessage,
  segmentsForPersist,
  turnStateFromHistoryMessage,
} from "@/lib/sse/reducer";
import {
  clearActiveStreamMarker,
  readActiveStreamMarker,
  writeActiveStreamMarker,
} from "@/lib/stream-recovery";
import {
  applyHistoryToMessages,
  useConversationTranscriptRefs,
} from "@/lib/use-conversation-transcript";
import type { ChatChunk, TurnSegment, TurnState, WebSourceCard } from "@/lib/sse/types";

import { ChatHeader } from "@/components/layout/ChatHeader";
import { useShellActions, useSidebarOpen } from "@/lib/shell/shell-context";
import { cn } from "@/lib/cn";
import { DeepResearchPanel } from "@/components/research/DeepResearchPanel";
import { PlanExecutionChatBanner } from "@/components/plan/PlanExecutionChatBanner";
import { PlanPanel } from "@/components/plan/PlanPanel";
import { TaskChatView } from "@/components/plan/TaskChatView";
import { cancelPlanExecution, rememberWatchedPlanExecution } from "@/lib/api/plan-execution";
import { usePlanDockState } from "@/hooks/use-plan-dock-state";
import { usePlanExecutionProgress } from "@/hooks/use-plan-execution-progress";
import { usePlanExecutionRehydrate } from "@/hooks/use-plan-execution-rehydrate";
import {
  allPlanExecutionMessageIds,
  findPlanTask,
  isMessageInPlanTask,
  messageIdsForPlanTask,
} from "@/lib/plan-execution-view";
import { rememberWatchedResearch } from "@/lib/api/research";
import { researchLog } from "@/lib/research-debug";
import { ArtifactsPanel, type DockArtifactItem } from "@/components/dock/ArtifactsPanel";
import { PromptDebugPanel, type PromptSnapshot } from "@/components/dock/PromptDebugPanel";
import { MemoryDockPanel } from "@/components/memory/MemoryDockPanel";
import { ProjectMemoryChip } from "@/components/memory/ProjectMemoryChip";
import { readStoredSqlProject } from "@/components/memory/ProjectMemoryToolbar";
import { ProjectCreateModal } from "@/components/memory/ProjectCreateModal";
import { fetchSqlProjects, type SqlProject } from "@/lib/api/query-memory";
import {
  hasMempalaceMcp,
  hasSqlQueryMemory,
  showProjectMemoryUi,
} from "@/lib/memory/profile-capabilities";
import { WebSourcesBar } from "@/components/chat/WebResearchViews";
import { TurnTimeline, AgentWorkingShimmer } from "@/components/chat/TurnTimeline";
import { MessageActions } from "@/components/chat/MessageActions";
import { useAutoResizeTextarea } from "@/lib/hooks/use-auto-resize-textarea";
import { markdownCodeComponents } from "@/lib/markdown/markdownCodeComponents";
import { StatusProgressCard } from "@/components/chat/StatusProgressCard";
import { extractAssistantCopyText } from "@/lib/extract-message-text";
import {
  clearMessageRating,
  loadMessageRatings,
  toggleMessageRating,
  type MessageRating,
} from "@/lib/message-feedback";
import { SessionCharts } from "@/components/chat/SessionCharts";

import type { DockTab } from "@/lib/layout/dock-tab";

type PlanPendingChunk = ChatChunk & { type: "orchestration_plan_pending" };
type AgentMode = "normal" | "plan" | "ask" | "debug" | "deep_research";
type LiveArtifactMessage = {
  id: string;
  title: string;
  artType: string;
  buffer: string;
  savedPath?: string;
  execution?: string;
};
type ChatMessageArtifact = ChatHistoryArtifact | LiveArtifactMessage;

function isMemorizationMessage(content: string): boolean {
  const prefixes = [
    "L'agente ha memorizzato:",
    "The agent has memorized:",
    "El agente ha memorizado:",
    "L'agent a mémorisé:",
    "Der Agent hat gespeichert:",
    "L'agente ha memorizzato",
    "The agent has memorized",
    "El agente ha memorizado",
    "L'agent a mémorisé",
    "Der Agent hat gespeichert",
    "L'agente ha rilevato",
    "The agent detected",
    "El agente detectó",
    "L'agent a détecté",
    "Der Agent hat festgestellt",
    "L'agente ha vericato",
    "L'agente ha verificato",
    "The agent verified",
    "El agente verificó",
    "L'agent a vérifié",
    "Der Agent hat verifiziert"
  ];
  const cleaned = content.trim();
  return prefixes.some(p => cleaned.includes(p));
}

type ChatViewState = { kind: "main" } | { kind: "task"; taskId: string };

type ChatMessage = {
  id: string;
  role: "user" | "assistant" | "internal";
  content: string;
  metadata?: {
    plan_id?: string;
    plan_task_id?: string;
    memorized_message_id?: string;
  };
  reasoning?: string;
  steps?: ChatHistoryStep[];
  artifacts?: ChatMessageArtifact[];
  /** Thinking era atteso ma il backend non ha inviato chunk reasoning */
  reasoningUnavailable?: boolean;
  webSources?: WebSourceCard[];
  /** Persisted or live interleaved timeline (preferred over flat fields for display). */
  segments?: TurnSegment[];
  rating?: MessageRating | null;
  feedbackComment?: string | null;
};

function parseWebHostInput(raw: string): string | null {
  const s = raw.trim().toLowerCase();
  if (!s || s.length > 253) return null;
  if (s === "localhost") return s;
  if (/^\*\.([a-z0-9]([a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}$/.test(s)) return s;
  if (/^([a-z0-9]([a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}$/.test(s)) return s;
  return null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value != null && typeof value === "object" && !Array.isArray(value);
}

function isPlanArtifact(artifact: unknown, content = ""): boolean {
  const art = isRecord(artifact) ? artifact : {};
  const artType = String(art.type || "").trim().toLowerCase();
  if (artType === "plan") return true;
  const id = String(art.identifier || "").trim().toLowerCase();
  if (id.startsWith("execution_plan_")) return true;
  return /<plan\b/i.test(content);
}

function isHtmlArtifactPath(path: string): boolean {
  const p = path.trim().toLowerCase();
  return p.startsWith("workspace/") && p.endsWith(".html");
}

function isHistoricalPlanArtifact(a: ChatHistoryArtifact): boolean {
  if (a.kind === "plan") return true;
  const name = (a.original_name || "").toLowerCase();
  if (name.startsWith("execution_plan_")) return true;
  const key = (a.storage_key || "").toLowerCase();
  if (key.includes("execution_plan")) return true;
  return false;
}

function isLiveArtifact(value: ChatMessageArtifact): value is LiveArtifactMessage {
  return "buffer" in value;
}

function historyMessageRole(role: string): ChatMessage["role"] {
  return role === "user" ? "user" : role === "internal" ? "internal" : "assistant";
}

function historyMessageFromApi(m: ChatHistoryMessage): ChatMessage {
  let webSources: WebSourceCard[] | undefined = undefined;
  if (m.steps) {
    for (const step of m.steps) {
      if (step.name === "web_search" && step.output) {
        try {
          const data = JSON.parse(step.output);
          const rows = Array.isArray(data?.results) ? data.results : [];
          if (rows.length > 0) {
            webSources = webSources || [];
            const seen = new Set(webSources.map((c) => c.url));
            let idx = webSources.length;
            for (const row of rows) {
              const r = row as Record<string, unknown>;
              const url = String(r?.url ?? "").trim();
              if (!url || seen.has(url)) continue;
              seen.add(url);
              idx += 1;
              webSources.push({
                index: idx,
                title: String(r?.title || url).slice(0, 500),
                url,
                provider: r?.provider != null ? String(r.provider) : undefined,
              });
            }
          }
        } catch {
          // ignore malformed step output
        }
      }
    }
  }

  return {
    id: m.id,
    role: historyMessageRole(m.role),
    content: m.content,
    reasoning: m.reasoning,
    steps: m.steps,
    artifacts: m.artifacts,
    webSources,
    segments: m.timeline && m.timeline.length > 0 ? (m.timeline as TurnSegment[]) : undefined,
    metadata: m.metadata,
    rating: m.rating as MessageRating | undefined,
    feedbackComment: m.feedback_comment,
  };
}

function turnSteps(state: TurnState): ChatHistoryStep[] {
  return state.toolOrder
    .map((id) => state.toolSteps[id])
    .filter(Boolean)
    .map((s) => ({
      id: s.id,
      name: s.name,
      type: "tool",
      input: typeof s.input === "string" ? s.input : JSON.stringify(s.input ?? {}),
      output: s.output,
      is_error: Boolean(s.isError),
      created_at: new Date().toISOString(),
    }));
}

function turnArtifacts(state: TurnState): LiveArtifactMessage[] {
  return state.artifactOrder
    .map((id) => state.artifacts[id])
    .filter(Boolean)
    .map((a) => ({
      id: a.id,
      title: a.title || a.id,
      artType: a.artType,
      buffer: a.buffer,
      savedPath: a.savedPath,
      execution: a.execution,
    }));
}

function planChunkFromRecord(value: unknown): PlanPendingChunk | null {
  if (!isRecord(value)) return null;
  if (value.type !== "orchestration_plan_pending") return null;
  const raw = {
    type: "orchestration_plan_pending" as const,
    plan_id: String(value.plan_id || ""),
    plan: isRecord(value.plan)
      ? {
        goal: String((value.plan as { goal?: string }).goal || ""),
        tasks: Array.isArray((value.plan as { tasks?: unknown[] }).tasks)
          ? (value.plan as { tasks: unknown[] }).tasks
          : [],
        context: String((value.plan as { context?: string }).context || ""),
      }
      : { goal: "", tasks: [] },
    plan_markdown: String(value.plan_markdown || ""),
    todos: Array.isArray(value.todos) ? value.todos : [],
    annotations: isRecord(value.annotations) ? value.annotations : {},
    revision: Number(value.revision || 1),
    goal: String(value.goal || ""),
    force_sidebar_refresh: Boolean(value.force_sidebar_refresh),
    highlight_task_id: String(value.highlight_task_id || value.highlightTaskId || ""),
  };
  const pendingEvt = raw as Parameters<typeof normalizePlanPendingChunk>[0];
  if (planFromOrchestrationEvent(pendingEvt)) {
    return normalizePlanPendingChunk(pendingEvt) as PlanPendingChunk;
  }
  return raw as PlanPendingChunk;
}



function formatTextWithCitations(text: string, messageId?: string): string {
  if (!text) return text;
  // split by code blocks to avoid replacing inside them
  const parts = text.split(/(```[\s\S]*?```|`[^`]+`)/g);
  for (let i = 0; i < parts.length; i++) {
    // even indices are outside code blocks
    if (i % 2 === 0) {
      const prefix = messageId ? `source-${messageId}` : "source";
      // replace [1], [2], etc. avoiding negative lookbehinds for Safari compat
      parts[i] = parts[i].replace(/(^|[^\[])\[(\d+)\](?!\(|\])/g, `$1[[$2]](#${prefix}-$2)`);
      // Clean double brackets and URL-encode spaces in file paths for markdown link compatibility
      parts[i] = parts[i].replace(/\[\[?([^\]]+)\]\]?\(([^)]+)\)/g, (match, label, url) => {
        const cleanUrl = url.trim().startsWith("#") ? url.trim() : url.trim().replace(/ /g, "%20");
        return `[${label.trim()}](${cleanUrl})`;
      });
      // Replace LaTeX display formula delimiters \[ \] with $$
      parts[i] = parts[i].replace(/\\\[/g, "$$\n").replace(/\\\]/g, "\n$$");
      // Replace LaTeX inline formula delimiters \( \) with $
      parts[i] = parts[i].replace(/\\\(/g, "$").replace(/\\\)/g, "$");
    }
  }
  return parts.join("");
}

const KhubViewerLoader = () => {
  const t = useT();
  return (
    <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 text-muted-foreground">
      <Loader2 className="animate-spin text-primary" size={24} />
      <span className="text-xs font-medium">{t("khub_file.loading")}</span>
    </div>
  );
};

const KhubPdfViewer = dynamic(
  () => import("@/components/chat/KhubPdfViewer").then((m) => ({ default: m.KhubPdfViewer })),
  {
    ssr: false,
    loading: () => <KhubViewerLoader />,
  }
);

export function ChatWorkspace({ conversationId: initialConversationId }: { conversationId: string }) {
  const t = useT();
  const showPromptDebug = AION_PROMPT_DEBUG_UI_ENABLED;
  const chatStreamDebug = AION_CHAT_STREAM_DEBUG_ENABLED;
  const COMPOSER_MIN_HEIGHT = 110;
  const COMPOSER_TEXTAREA_MIN = 48;
  const COMPOSER_TEXTAREA_DEFAULT_MAX = 200;
  const userId = useStoredUserId();
  const token = useStoredToken();
  const shellActions = useShellActions();
  const sidebarOpen = useSidebarOpen();
  const [conversationId, setConversationId] = useState(initialConversationId);

  const [dockTab, setDockTab] = useState<DockTab>("none");
  const [lastActiveTab, setLastActiveTab] = useState<DockTab>("plan");

  // States for external Knowledge Hub file retrieval and dynamic PDF viewing
  const [khubLoading, setKhubLoading] = useState(false);
  const [khubError, setKhubError] = useState<string | null>(null);
  const [pdfUrl, setPdfUrl] = useState<string | null>(null);
  const [pdfName, setPdfName] = useState<string>("");

  // LLM Provider selection
  const [llmProviders, setLlmProviders] = useState<any[]>([]);
  const [selectedProvider, setSelectedProvider] = useState<string | null>(null);
  const [showProviderDropdown, setShowProviderDropdown] = useState(false);
  const [providersLoading, setProvidersLoading] = useState(false);

  useEffect(() => {
    return () => {
      if (pdfUrl) {
        URL.revokeObjectURL(pdfUrl);
      }
    };
  }, [pdfUrl]);

  useEffect(() => {
    if (token && userId) {
      fetchLlmProviders();
    }
  }, [token, userId]);

  const fetchLlmProviders = async () => {
    setProvidersLoading(true);
    try {
      const res = await fetch(`${apiBase()}/admin/llm-providers`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) {
        const data = await res.json();
        const enabled = Array.isArray(data) ? data.filter((p: any) => p.enabled) : [];
        setLlmProviders(enabled);
        const defaultProvider = enabled.find((p: any) => p.is_default);
        if (defaultProvider && !selectedProvider) {
          setSelectedProvider(defaultProvider.slug);
        }
      }
    } catch (err) {
      console.error("Failed to fetch LLM providers", err);
    } finally {
      setProvidersLoading(false);
    }
  };

  const selectedProviderName = useMemo(() => {
    if (!selectedProvider) return null;
    return llmProviders.find((p) => p.slug === selectedProvider);
  }, [selectedProvider, llmProviders]);

  // States for session files (moved from left sidebar to files panel on the right)
  const [sessionFiles, setSessionFiles] = useState<SessionFileRow[]>([]);
  const [loadingFiles, setLoadingFiles] = useState(false);

  const fetchSessionFiles = useCallback(async () => {
    if (!conversationId || conversationId === "default") {
      setSessionFiles([]);
      return;
    }
    setLoadingFiles(true);
    try {
      const [uploads, derived, workspace, rootFiles] = await Promise.all([
        listSessionFilesSubdir(conversationId, userId, "uploads", token).catch(() => []),
        listSessionFilesSubdir(conversationId, userId, "derived", token).catch(() => []),
        listSessionFilesSubdir(conversationId, userId, "workspace", token).catch(() => []),
        listSessionFilesSubdir(conversationId, userId, "", token).catch(() => []),
      ]);
      setSessionFiles([...uploads, ...derived, ...workspace, ...rootFiles]);
    } catch (err) {
      console.error("Errore recupero file di sessione:", err);
    } finally {
      setLoadingFiles(false);
    }
  }, [conversationId, userId, token]);

  useEffect(() => {
    fetchSessionFiles();
  }, [fetchSessionFiles]);



  const handleKhubFileClick = useCallback(async (filePath: string, fileName: string) => {
    // Revoke old URL if any to avoid leaks
    if (pdfUrl) {
      URL.revokeObjectURL(pdfUrl);
      setPdfUrl(null);
    }

    // Set default name if empty
    const cleanName = fileName || filePath.split("/").pop() || t("khub_file.title");
    const decodedName = decodeURIComponent(cleanName);
    setPdfName(decodedName);
    setKhubLoading(true);
    setKhubError(null);
    setDockTab("khub_file"); // Switch dock panel to our document viewer

    try {
      const decodedPath = decodeURIComponent(filePath);
      const blob = await fetchKhubFileContent(decodedPath, userId, token);
      const url = URL.createObjectURL(blob);
      setPdfUrl(url);
    } catch (err: any) {
      console.error("Error retrieving document from Knowledge Hub:", err);
      setKhubError(err?.message || t("khub_file.error"));
    } finally {
      setKhubLoading(false);
    }
  }, [pdfUrl, userId, token]);

  const renderMarkdownLink = useCallback(({ node, className, href, children, ...props }: any) => {
    if (href?.startsWith("#source-")) {
      return (
        <a
          href={href}
          className="inline-flex items-center justify-center min-w-5 h-5 ml-0.5 px-1 text-[10px] font-semibold transition-all duration-300 bg-primary/10 hover:bg-primary hover:text-primary-foreground rounded-full text-primary align-super no-underline shadow-sm"
          title={t("chat.go_to_source")}
          onClick={(e) => {
            e.preventDefault();
            const el = document.getElementById(href.replace("#", ""));
            if (el) {
              el.scrollIntoView({ behavior: "smooth", block: "center" });
              el.classList.add("ring-2", "ring-primary", "ring-offset-2", "ring-offset-background");
              setTimeout(() => el.classList.remove("ring-2", "ring-primary", "ring-offset-2", "ring-offset-background"), 1500);
            }
          }}
          {...props}
        >
          {children}
        </a>
      );
    }

    const isKhubFile = href &&
      !href.startsWith("http://") &&
      !href.startsWith("https://") &&
      !href.startsWith("#") &&
      !href.startsWith("mailto:") &&
      !href.startsWith("tel:");

    if (isKhubFile) {
      return (
        <a
          href={href}
          className={cn(className, "text-primary hover:underline cursor-pointer inline-flex items-center gap-1 font-semibold")}
          onClick={(e) => {
            e.preventDefault();
            // clean brackets around name in citations if present
            let label = children?.toString() || "";
            if (label.startsWith("[") && label.endsWith("]")) {
              label = label.slice(1, -1);
            }
            void handleKhubFileClick(href, label || href);
          }}
          {...props}
        >
          {children}
        </a>
      );
    }

    return <a href={href} className={className} target="_blank" rel="noopener noreferrer" {...props}>{children}</a>;
  }, [handleKhubFileClick]);

  // Sincronizza lo stato se la prop iniziale cambia (es. navigazione avanti/indietro del browser)
  useEffect(() => {
    setConversationId(initialConversationId);
  }, [initialConversationId]);

  useEffect(() => {
    const onPopState = () => {
      const match = window.location.pathname.match(/^\/c\/([^/]+)/);
      const id = match?.[1];
      if (id && id !== conversationId) {
        setConversationId(id);
      }
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, [conversationId]);

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [recoveryAssistantId, setRecoveryAssistantId] = useState<string | null>(null);
  const [editingMessageId, setEditingMessageId] = useState<string | null>(null);
  const [editInput, setEditInput] = useState("");
  const [messageRatings, setMessageRatings] = useState<Record<string, MessageRating>>({});
  const [activeCommentBoxId, setActiveCommentBoxId] = useState<string | null>(null);

  useEffect(() => {
    setMessageRatings(loadMessageRatings());
  }, []);

  const handleMessageRate = useCallback(async (messageId: string, rating: MessageRating | null) => {
    setMessageRatings((prev) => {
      const copy = { ...prev };
      if (rating == null) delete copy[messageId];
      else copy[messageId] = rating;
      return copy;
    });

    if (rating === -1) {
      setActiveCommentBoxId(messageId);
    } else {
      setActiveCommentBoxId(null);
    }

    if (rating == null) {
      clearMessageRating(messageId);
    } else {
      toggleMessageRating(messageId, rating);
    }

    setMessages((prev) =>
      prev.map((m) =>
        m.id === messageId
          ? { ...m, rating: rating }
          : m
      )
    );

    try {
      const msg = messages.find((m) => m.id === messageId);
      const comment = msg?.feedbackComment || null;
      await rateMessage(conversationId, messageId, rating, comment, userId, token);
    } catch (e) {
      console.error("Error rating message:", e);
    }
  }, [conversationId, userId, token, messages]);

  const handleMessageComment = useCallback(async (messageId: string, comment: string) => {
    setMessages((prev) =>
      prev.map((m) =>
        m.id === messageId
          ? { ...m, feedbackComment: comment }
          : m
      )
    );

    try {
      const rating = messageRatings[messageId] ?? null;
      await rateMessage(conversationId, messageId, rating, comment, userId, token);
    } catch (e) {
      console.error("Error saving comment:", e);
    }
  }, [conversationId, userId, token, messageRatings]);

  const lastUserMessageId = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].role === "user") {
        return messages[i].id;
      }
    }
    return null;
  }, [messages]);

  const lastAssistantMessageId = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].role === "assistant") {
        return messages[i].id;
      }
    }
    return null;
  }, [messages]);

  const visibleMessages = useMemo(() => {
    if (!recoveryAssistantId) return messages;
    return messages.filter((m) => m.id !== recoveryAssistantId);
  }, [messages, recoveryAssistantId]);

  const handleStartEdit = useCallback((msg: ChatMessage) => {
    setEditingMessageId(msg.id);
    setEditInput(msg.content);
  }, []);

  const [profiles, setProfiles] = useState<ProfileRow[]>([]);
  const [profile, setProfile] = useState("aion_std");
  const [sqlQueryProject, setSqlQueryProject] = useState(() =>
    typeof window !== "undefined" ? readStoredSqlProject() : "default"
  );

  useEffect(() => {
    if (typeof window !== "undefined" && sqlQueryProject) {
      localStorage.setItem("aion_sql_query_project", sqlQueryProject);
    }
  }, [sqlQueryProject]);

  const activeProfileSlug = useMemo(() => {
    const row = profiles.find((p) => p.slug === profile || p.name === profile);
    if (row?.slug) return row.slug;
    return profile.replace(/\s+/g, "_").toLowerCase();
  }, [profiles, profile]);

  const activeProfileRow = useMemo(
    () => profiles.find((p) => p.slug === profile || p.name === profile),
    [profiles, profile]
  );

  const activeProfileName = useMemo(() => {
    return activeProfileRow?.name || profile;
  }, [activeProfileRow, profile]);

  const showSqlQueryMemory = useMemo(
    () => hasSqlQueryMemory(activeProfileRow),
    [activeProfileRow]
  );
  const showNavigationMemory = useMemo(
    () => hasMempalaceMcp(activeProfileRow),
    [activeProfileRow]
  );
  const showProjectMemory = useMemo(
    () => showProjectMemoryUi(activeProfileRow),
    [activeProfileRow]
  );

  const [projectCreateOpen, setProjectCreateOpen] = useState(false);
  const [isSavingInfo, setIsSavingInfo] = useState(false);
  const [memorizingMessageId, setMemorizingMessageId] = useState<string | null>(null);
  const [projectWarningModalOpen, setProjectWarningModalOpen] = useState(false);

  // States for available SQL QueryMemory projects
  const [sqlProjects, setSqlProjects] = useState<SqlProject[]>([]);
  const [loadingSqlProjects, setLoadingSqlProjects] = useState(false);

  // Fetch available projects from backend
  const fetchProjectsList = useCallback(async () => {
    if (!userId) return;
    setLoadingSqlProjects(true);
    try {
      const list = await fetchSqlProjects(userId, token, activeProfileSlug);
      setSqlProjects(list);
    } catch (err) {
      console.error("Error fetching SQL projects:", err);
    } finally {
      setLoadingSqlProjects(false);
    }
  }, [userId, token, activeProfileSlug]);

  // Load project list when memory capabilities are enabled
  useEffect(() => {
    if (showSqlQueryMemory) {
      void fetchProjectsList();
    } else {
      setSqlProjects([]);
    }
  }, [showSqlQueryMemory, fetchProjectsList]);

  // Auto-resolve stale or invalid project slug selections
  useEffect(() => {
    if (!showSqlQueryMemory || loadingSqlProjects) return;

    const isValid = sqlProjects.some((p) => p.slug === sqlQueryProject);
    if (!isValid && sqlProjects.length > 0) {
      const firstProj = sqlProjects[0].slug;
      setSqlQueryProject(firstProj);
      localStorage.setItem("aion_sql_query_project", firstProj);
      if (messages.length > 0) {
        updateConversationMetadata(conversationId, { sql_query_project: firstProj }, userId, token)
          .catch((err) => console.error("Error saving auto-selected project preference to DB:", err));
      }
    }
  }, [
    sqlProjects,
    sqlQueryProject,
    showSqlQueryMemory,
    loadingSqlProjects,
    conversationId,
    messages.length,
    userId,
    token,
  ]);



  const isProjectRequiredButMissing = useMemo(() => {
    if (!showSqlQueryMemory) return false;
    if (loadingSqlProjects) return false;
    if (sqlProjects.length === 0) return true;
    return (
      !sqlQueryProject ||
      sqlQueryProject.trim().toLowerCase() === "default" ||
      !sqlProjects.some((p) => p.slug === sqlQueryProject)
    );
  }, [showSqlQueryMemory, sqlProjects, sqlQueryProject, loadingSqlProjects]);

  const [thinkingEnabled, setThinkingEnabled] = useState(false);
  const [reasoningEffort, setReasoningEffort] = useState<"min" | "medium" | "max">("medium");
  const [agentMode, setAgentMode] = useState<AgentMode>("normal");
  const [researchAdoptId, setResearchAdoptId] = useState<string | null>(null);
  const [researchAdoptQuery, setResearchAdoptQuery] = useState<string | null>(null);
  const [planExecAdoptRunId, setPlanExecAdoptRunId] = useState<string | null>(null);
  const [planExecAdoptPlanId, setPlanExecAdoptPlanId] = useState<string | null>(null);
  const [planExecutionRehydrateReady, setPlanExecutionRehydrateReady] = useState(false);
  const [chatView, setChatView] = useState<ChatViewState>({ kind: "main" });
  const searchParams = useSearchParams();
  const planExecHandledRef = useRef<Set<string>>(new Set());
  const planFinalSummaryHandledRef = useRef<Set<string>>(new Set());
  const adoptedResearchRef = useRef<Set<string>>(new Set());
  const [conversationTitle, setConversationTitle] = useState<string | null>(null);
  const [mcpPending, setMcpPending] = useState<
    Array<{ server_slug: string; display_name: string; reason: string; message: string; integration?: Record<string, unknown> }>
  >([]);
  const [mcpRuntimeErrors, setMcpRuntimeErrors] = useState<
    Array<{ server_slug: string; display_name: string; reason: string; message: string; error?: string; hint?: string }>
  >([]);
  const [mcpPendingOpen, setMcpPendingOpen] = useState(false);
  const [sessionPrepareStatus, setSessionPrepareStatus] = useState<
    "idle" | "warming" | "ready" | "failed"
  >("idle");
  const prepareAbortRef = useRef<AbortController | null>(null);
  const mcpAutoOpenRef = useRef<string | null>(null);

  const mcpAlertCount = mcpPending.length + mcpRuntimeErrors.length;

  const refreshMcpAlerts = useCallback(
    (opts?: { probe?: boolean }) => {
      if (!activeProfileSlug || !userId) {
        setMcpPending([]);
        setMcpRuntimeErrors([]);
        return;
      }
      const headers = jsonHeaders(userId, token);
      const pendingUrl = `${apiBase()}/v1/integrations/pending?profile=${encodeURIComponent(activeProfileSlug)}`;
      const probeQ = opts?.probe ? "&probe=1" : "";
      const runtimeUrl = `${apiBase()}/v1/integrations/runtime-errors?profile=${encodeURIComponent(activeProfileSlug)}&session_id=${encodeURIComponent(conversationId)}${probeQ}`;
      void fetch(pendingUrl, { headers })
        .then((r) => (r.ok ? r.json() : { pending: [] }))
        .then((d) => setMcpPending(d.pending || []))
        .catch(() => setMcpPending([]));
      void fetch(runtimeUrl, { headers })
        .then((r) => (r.ok ? r.json() : { errors: [] }))
        .then((d) => setMcpRuntimeErrors(d.errors || []))
        .catch(() => setMcpRuntimeErrors([]));
    },
    [activeProfileSlug, userId, token, conversationId]
  );

  useEffect(() => {
    refreshMcpAlerts({ probe: false });
  }, [refreshMcpAlerts]);

  // Pre-warm MCP + agent cache; surface integration errors instead of a silent stall.
  useEffect(() => {
    if (!conversationId || !userId || !activeProfileSlug) return;
    prepareAbortRef.current?.abort();
    const ac = new AbortController();
    prepareAbortRef.current = ac;
    setSessionPrepareStatus("warming");

    void (async () => {
      const result = await waitForChatPrepare(
        conversationId,
        activeProfileSlug,
        userId,
        token,
        agentMode,
        { signal: ac.signal, llmProviderName: selectedProvider || undefined }
      );
      if (ac.signal.aborted) return;

      if (!result) {
        setSessionPrepareStatus("idle");
        refreshMcpAlerts({ probe: true });
        return;
      }

      const nextStatus =
        result.status === "warming"
          ? "ready"
          : result.status === "idle"
            ? "idle"
            : result.status;
      setSessionPrepareStatus(nextStatus);

      const runtimeRows = (result.mcp_errors ?? []).map((row: ChatPrepareMcpError) => ({
        server_slug: row.server_slug,
        display_name: row.display_name,
        reason: row.reason ?? "runtime_error",
        message: row.message ?? row.hint ?? row.error ?? "MCP non disponibile",
        error: row.error,
        hint: row.hint,
      }));
      if (runtimeRows.length) {
        setMcpRuntimeErrors(runtimeRows);
        if (mcpAutoOpenRef.current !== conversationId) {
          mcpAutoOpenRef.current = conversationId;
          setMcpPendingOpen(true);
        }
      }
      refreshMcpAlerts({ probe: false });
    })();

    return () => {
      ac.abort();
    };
  }, [conversationId, activeProfileSlug, userId, token, agentMode, refreshMcpAlerts, selectedProvider]);

  const handleToggleThinking = useCallback((enabled: boolean) => {
    setThinkingEnabled(enabled);
    localStorage.setItem("aion_last_thinking_enabled", String(enabled));
    if (messages.length > 0) {
      updateConversationMetadata(conversationId, { thinking_enabled: enabled }, userId, token)
        .catch((err) => console.error("Error saving thinking preference to DB:", err));
    }
  }, [conversationId, messages.length, userId, token]);

  const handleReasoningEffortChange = useCallback((effort: "min" | "medium" | "max") => {
    setReasoningEffort(effort);
    localStorage.setItem("aion_last_reasoning_effort", effort);
    if (messages.length > 0) {
      updateConversationMetadata(conversationId, { reasoning_effort: effort }, userId, token)
        .catch((err) => console.error("Error saving reasoning effort preference to DB:", err));
    }
  }, [conversationId, messages.length, userId, token]);

  const handleProfileChange = useCallback((newProfile: string) => {
    setProfile(newProfile);
    if (messages.length > 0) {
      updateConversationProfile(conversationId, newProfile, userId, token)
        .catch((err) => console.error("Error saving profile preference to DB:", err));
    }
  }, [conversationId, messages.length, userId, token]);

  const handleProjectChange = useCallback((newProject: string) => {
    const proj = newProject.trim();
    setSqlQueryProject(proj);
    if (typeof window !== "undefined") {
      localStorage.setItem("aion_sql_query_project", proj);
    }
    if (messages.length > 0) {
      updateConversationMetadata(conversationId, { sql_query_project: proj }, userId, token)
        .catch((err) => console.error("Error saving project preference to DB:", err));
    }
    void fetchProjectsList();
  }, [conversationId, messages.length, userId, token, fetchProjectsList]);

  const handleAgentModeChange = useCallback((mode: AgentMode) => {
    setAgentMode(mode);
    localStorage.setItem("aion_agent_mode", mode);
    if (messages.length > 0) {
      updateConversationMetadata(
        conversationId,
        {
          agent_mode: mode,
          plan_mode: mode === "plan",
          deep_research_mode: mode === "deep_research",
        },
        userId,
        token
      ).catch((err) => console.error("Error saving agent mode preference to DB:", err));
    }
  }, [conversationId, messages.length, userId, token]);



  // Stati e logica per i nuovi menù popover "+", "Profilo", "Thinking" e "Agent Mode"
  const [isPlusOpen, setIsPlusOpen] = useState(false);
  const [isProfileOpen, setIsProfileOpen] = useState(false);
  const [isAgentModeOpen, setIsAgentModeOpen] = useState(false);
  const [isToolsViewSubOpen, setIsToolsViewSubOpen] = useState(false);
  const [isWebSearchSubOpen, setIsWebSearchSubOpen] = useState(false);
  const [isThinkingSubOpen, setIsThinkingSubOpen] = useState(false);

  const closePlusSubMenus = useCallback(() => {
    setIsToolsViewSubOpen(false);
    setIsWebSearchSubOpen(false);
    setIsThinkingSubOpen(false);
  }, []);

  const [toolsView, setToolsView] = useState<"hidden" | "partial" | "full">(() => {
    if (typeof window !== "undefined") {
      const stored = localStorage.getItem("aion_chat_tools_view");
      if (stored === "hidden" || stored === "partial" || stored === "full") {
        return stored;
      }
    }
    return "full";
  });

  const handleToolsViewChange = useCallback((view: "hidden" | "partial" | "full") => {
    setToolsView(view);
    localStorage.setItem("aion_chat_tools_view", view);
  }, []);

  const [webSearchEnabled, setWebSearchEnabled] = useState(true);
  const [webRestrictHosts, setWebRestrictHosts] = useState<string[]>([]);
  const [webRestrictModalOpen, setWebRestrictModalOpen] = useState(false);
  const [webRestrictDraft, setWebRestrictDraft] = useState<string[]>([]);
  const [webRestrictInput, setWebRestrictInput] = useState("");
  const [webRestrictInputError, setWebRestrictInputError] = useState<string | null>(null);

  useEffect(() => {
    try {
      const en = localStorage.getItem("aion_chat_web_search_enabled");
      if (en === "0" || en === "false") setWebSearchEnabled(false);
      else if (en === "1" || en === "true") setWebSearchEnabled(true);
      const raw = localStorage.getItem("aion_web_search_restrict_hosts");
      if (raw) {
        const arr = JSON.parse(raw) as unknown;
        if (Array.isArray(arr)) {
          const hosts = arr.filter((x): x is string => typeof x === "string").slice(0, 20);
          setWebRestrictHosts(hosts);
        }
      }
    } catch {
      /* ignore */
    }
  }, []);

  const persistWebSearchEnabled = useCallback((enabled: boolean) => {
    setWebSearchEnabled(enabled);
    try {
      localStorage.setItem("aion_chat_web_search_enabled", enabled ? "1" : "0");
    } catch {
      /* ignore */
    }
  }, []);

  const persistWebRestrictHosts = useCallback((hosts: string[]) => {
    setWebRestrictHosts(hosts);
    try {
      if (hosts.length) localStorage.setItem("aion_web_search_restrict_hosts", JSON.stringify(hosts));
      else localStorage.removeItem("aion_web_search_restrict_hosts");
    } catch {
      /* ignore */
    }
  }, []);

  const plusMenuRef = useRef<HTMLDivElement>(null);
  const profileMenuRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (plusMenuRef.current && !plusMenuRef.current.contains(event.target as Node)) {
        setIsPlusOpen(false);
        closePlusSubMenus();
      }
      if (profileMenuRef.current && !profileMenuRef.current.contains(event.target as Node)) {
        setIsProfileOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [closePlusSubMenus]);

  const [turnVisual, setTurnVisual] = useState<TurnState | null>(null);
  const [streaming, setStreaming] = useState(false);
  const [streamRecovery, setStreamRecovery] = useState(false);
  const streamRecoveryRef = useRef(false);
  const [activeMessageId, setActiveMessageId] = useState<string | null>(null);

  useEffect(() => {
    if (dockTab !== "none") {
      setLastActiveTab(dockTab);
    }
  }, [dockTab]);

  useEffect(() => {
    if (!streaming) {
      fetchSessionFiles();
    }
  }, [streaming, fetchSessionFiles]);

  useEffect(() => {
    if (dockTab === "memory" && !showProjectMemory) {
      setDockTab("artifacts");
    }
    if (
      (dockTab === "query_memory" || dockTab === "navigation_memory") &&
      showProjectMemory
    ) {
      setDockTab("memory");
    }
    if (dockTab === "query_memory" && !showSqlQueryMemory) {
      setDockTab(showProjectMemory ? "memory" : "artifacts");
    } else if (dockTab === "navigation_memory" && !showNavigationMemory) {
      setDockTab(showProjectMemory ? "memory" : "artifacts");
    }
  }, [dockTab, showProjectMemory, showSqlQueryMemory, showNavigationMemory]);

  const toggleDock = useCallback(() => {
    setDockTab((prev) => (prev === "none" ? lastActiveTab : "none"));
  }, [lastActiveTab]);

  const adoptResearchSession = useCallback(
    (sessionId: string, query: string | null, source: string) => {
      if (adoptedResearchRef.current.has(sessionId)) {
        researchLog("adopt skipped (already handled)", { sessionId, source });
        return;
      }
      adoptedResearchRef.current.add(sessionId);
      const q = (query || "").trim() || "Ricerca avviata dall'agente";
      researchLog("adopt from chat", { sessionId, query: q, source });
      rememberWatchedResearch(sessionId, q, conversationId);
      setResearchAdoptId(sessionId);
      setResearchAdoptQuery(q);
      setDockTab("research");
    },
    [conversationId]
  );

  useEffect(() => {
    if (!turnVisual) return;
    for (const seg of turnVisual.segments) {
      if (
        seg.kind === "tool" &&
        seg.name === "trigger_research" &&
        seg.status === "done" &&
        seg.output
      ) {
        try {
          const out = JSON.parse(seg.output) as {
            research_session_id?: string;
            ui_event?: string;
            query?: string;
          };
          if (out.research_session_id && out.ui_event === "research_started") {
            adoptResearchSession(out.research_session_id, out.query || null, "turnVisual");
          }
        } catch {
          /* ignore */
        }
      }
    }
  }, [turnVisual, adoptResearchSession]);

  const {
    planChunk,
    planMountKey,
    planChunkRef,
    setPlanChunk,
    openPlanDockFromChunk,
    openPlanDockFromMarkdown,
    updatePlanDockStreaming,
  } = usePlanDockState({
    onOpenPlanTab: useCallback(() => setDockTab("plan"), []),
  });
  // const [dbTableHint, setDbTableHint] = useState<string | null>(null);
  const [promptSnapshots, setPromptSnapshots] = useState<PromptSnapshot[]>([]);
  const dockArtifacts = useMemo<DockArtifactItem[]>(() => {
    const fromMessages = messages.flatMap((message, messageIndex) =>
      (message.artifacts || []).flatMap((artifact, artifactIndex) => {
        if (!isLiveArtifact(artifact) && isHistoricalPlanArtifact(artifact)) {
          return [];
        }
        if (
          isLiveArtifact(artifact) &&
          isPlanArtifact(
            { identifier: artifact.id, type: artifact.artType, title: artifact.title },
            artifact.buffer || "",
          )
        ) {
          return [];
        }
        const live = isLiveArtifact(artifact);
        const savedPath = live ? artifact.savedPath || "" : artifact.storage_key || "";
        const title = live ? artifact.title : artifact.original_name || artifact.id;
        const artType = live ? artifact.artType : artifact.mime;
        return [{
          key: `msg-${message.id}-${artifact.id}-${artifactIndex}`,
          id: artifact.id,
          title,
          language: artifactLanguage(artType, savedPath),
          typeLabel: artType || "artifact",
          savedPath: savedPath || undefined,
          downloadUrl: savedPath ? sessionDownloadUrl(conversationId, savedPath, token) : undefined,
          execution: live ? artifact.execution : undefined,
          source: "history",
          order: messageIndex * 1000 + artifactIndex,
        } as DockArtifactItem];
      })
    );
    const fromLiveTurn = turnVisual
      ? turnVisual.artifactOrder
        .map((id, artifactIndex) => {
          const artifact = turnVisual.artifacts[id];
          if (!artifact) return null;
          const isPlan =
            artifact.artType.toLowerCase() === "plan" ||
            isPlanArtifact(
              { identifier: artifact.id, type: artifact.artType, title: artifact.title },
              artifact.buffer,
            );
          const streaming = !artifact.savedPath && Boolean(artifact.buffer.trim()) && !isPlan;
          return {
            key: `live-${artifact.id}-${artifactIndex}`,
            id: artifact.id,
            title: artifact.title || artifact.id,
            language: artifactLanguage(artifact.artType, artifact.savedPath),
            typeLabel: artifact.artType || "artifact",
            savedPath: artifact.savedPath,
            downloadUrl: artifact.savedPath ? sessionDownloadUrl(conversationId, artifact.savedPath, token) : undefined,
            execution: artifact.execution,
            source: "live",
            order: messages.length * 1000 + artifactIndex,
            buffer: streaming ? artifact.buffer : undefined,
            streaming,
          } as DockArtifactItem;
        })
        .filter((x): x is DockArtifactItem => x !== null)
      : [];

    return [...fromMessages, ...fromLiveTurn].sort((a, b) => b.order - a.order);
  }, [conversationId, messages, turnVisual]);


  const [postTurnCharts, setPostTurnCharts] = useState<SessionChart[]>([]);
  const [postTurnFiles, setPostTurnFiles] = useState<{ rp: string; label: string }[]>([]);
  const seenFilesRef = useRef<Set<string>>(new Set());
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [input, setInput] = useState("");
  const [composerTextMax, setComposerTextMax] = useState(COMPOSER_TEXTAREA_DEFAULT_MAX);
  const [composerResizing, setComposerResizing] = useState(false);
  const composerContainerRef = useRef<HTMLDivElement | null>(null);
  const composerTextareaRef = useRef<HTMLTextAreaElement | null>(null);
  const composerResizeStartRef = useRef({ y: 0, textMax: COMPOSER_TEXTAREA_DEFAULT_MAX });
  useAutoResizeTextarea(composerTextareaRef, input, {
    minHeight: COMPOSER_TEXTAREA_MIN,
    maxHeight: composerTextMax,
  });
  const [pendingFiles, setPendingFiles] = useState<File[]>([]);

  const handleFilesDropped = useCallback((files: File[]) => {
    setPendingFiles((prev) => {
      const filtered = files.filter(
        (sf) => !prev.some((pf) => pf.name === sf.name && pf.size === sf.size)
      );
      return [...prev, ...filtered];
    });
  }, []);

  const [streamEpoch, setStreamEpoch] = useState(0);
  const abortRef = useRef<AbortController | null>(null);
  const internalBusyRef = useRef(false);
  const planTextParserEnabled =
    process.env.NEXT_PUBLIC_AION_PLAN_TEXT_PARSER === "1";
  /** Evita che fetchConversationHistory in ritardo sovrascriva la chat durante uno stream. */
  const streamingRef = useRef(false);
  /** Ignora stream-status Redis residuo subito dopo fine turno (stessa tab). */
  const streamFinishedAtRef = useRef(0);
  const activeConversationRef = useRef(conversationId);
  const {
    historyLoadEpochRef,
    previousConversationIdRef,
    bumpHistoryLoadEpoch,
    markStreamConversation,
    streamingConversationIdRef,
  } = useConversationTranscriptRefs();

  const messagesContainerRef = useRef<HTMLDivElement | null>(null);
  // True while the user has manually scrolled up during a stream — disables auto-scroll.
  const userScrolledAwayRef = useRef(false);
  // Threshold: how many px from the bottom counts as "at bottom".
  const SCROLL_THRESHOLD = 80;

  // Auto-scroll to bottom helper (used for non-streaming jumps: conversation load, etc.)
  const scrollToBottom = useCallback((behavior: ScrollBehavior = "auto") => {
    const container = messagesContainerRef.current;
    if (container) {
      container.scrollTo({ top: container.scrollHeight, behavior });
    }
  }, []);

  // Detect manual scroll-away during streaming so we don't fight the user.
  // When they scroll back near the bottom, re-engage auto-scroll.
  useEffect(() => {
    const container = messagesContainerRef.current;
    if (!container) return;

    const onScroll = () => {
      if (!streamingRef.current) return;
      const distFromBottom =
        container.scrollHeight - container.scrollTop - container.clientHeight;
      if (distFromBottom > SCROLL_THRESHOLD + 40) {
        // User scrolled up — disable auto-scroll.
        userScrolledAwayRef.current = true;
      } else if (distFromBottom <= SCROLL_THRESHOLD) {
        // User scrolled back near the bottom — re-enable.
        userScrolledAwayRef.current = false;
      }
    };

    container.addEventListener("scroll", onScroll, { passive: true });
    return () => container.removeEventListener("scroll", onScroll);
  }, []); // stable: runs once after mount

  // ResizeObserver: fires on every content height change (tokens, tool cards, images…).
  // This is the core of reliable auto-scroll — React effects are too coarse-grained.
  useEffect(() => {
    const container = messagesContainerRef.current;
    if (!container) return;

    const ro = new ResizeObserver(() => {
      if (!streamingRef.current) return;
      if (userScrolledAwayRef.current) return;
      // Instant scroll (no smooth) to avoid lag between height changes.
      container.scrollTop = container.scrollHeight;
    });

    // Observe the inner content div (first child), not the scroll container itself.
    const inner = container.firstElementChild;
    if (inner) ro.observe(inner);

    return () => ro.disconnect();
  }, []); // stable: ResizeObserver lives for the component lifetime

  // Reset "scrolled away" flag when streaming starts so each new turn starts locked.
  useEffect(() => {
    if (streaming) {
      userScrolledAwayRef.current = false;
      // Immediately snap to bottom at the start of a new turn.
      scrollToBottom("auto");
    }
  }, [streaming, scrollToBottom]);

  // Scroll to bottom when a new conversation is selected or history finishes loading.
  useEffect(() => {
    if (!streaming) {
      scrollToBottom("smooth");
    }
  }, [conversationId, messages.length, scrollToBottom, streaming]);


  const isStaleHistoryLoad = useCallback(
    (cid: string, epoch: number) =>
      activeConversationRef.current !== cid || historyLoadEpochRef.current !== epoch,
    [historyLoadEpochRef],
  );

  const transcriptStreaming = useMemo(
    () => ({
      streamingRef,
      streamingConversationIdRef,
    }),
    [streamingConversationIdRef],
  );

  useEffect(() => {
    streamingRef.current = streaming;
  }, [streaming]);

  useEffect(() => {
    streamRecoveryRef.current = streamRecovery;
  }, [streamRecovery]);

  useEffect(() => {
    activeConversationRef.current = conversationId;
  }, [conversationId]);

  useEffect(() => {
    if (!showPromptDebug || !conversationId || !userId) {
      setPromptSnapshots([]);
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const res = await fetchPromptSnapshots(conversationId, userId, token);
        if (cancelled) return;
        setPromptSnapshots((res.snapshots || []) as PromptSnapshot[]);
      } catch {
        if (!cancelled) setPromptSnapshots([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [conversationId, showPromptDebug, token, userId]);

  useEffect(() => {
    const prev = previousConversationIdRef.current;
    if (prev && prev !== conversationId) {
      if (streamingRef.current && streamingConversationIdRef.current === prev) {
        abortRef.current?.abort();
        void chatStop(prev, userId, token).catch(() => undefined);
        abortRef.current = null;
      }
      streamingRef.current = false;
      markStreamConversation(null);
      setStreaming(false);
      setStreamRecovery(false);
      streamRecoveryRef.current = false;
      setRecoveryAssistantId(null);
      setTurnVisual(null);
      clearActiveStreamMarker(prev);
    }
    previousConversationIdRef.current = conversationId;
  }, [conversationId, userId, token, markStreamConversation, streamingConversationIdRef]);

  useEffect(() => {
    planChunkRef.current = planChunk;
  }, [planChunk]);

  const effectiveEffort = thinkingEnabled ? reasoningEffort : "min";

  const refreshThreads = shellActions.refreshThreads;

  const handleTitleChange = useCallback(async (newTitle: string) => {
    if (!conversationId) return;
    try {
      await updateConversationTitle(conversationId, newTitle, userId, token);
      setConversationTitle(newTitle);
      void refreshThreads();
    } catch (err) {
      console.error("Error saving conversation title to DB:", err);
    }
  }, [conversationId, userId, token, refreshThreads]);

  const adoptPlanExecution = useCallback(
    (
      runId: string,
      planId: string,
      opts?: { rehydrate?: boolean; status?: string },
    ) => {
      const rid = runId.trim();
      const pid = planId.trim();
      if (!rid || !pid) return;
      if (!opts?.rehydrate && planExecHandledRef.current.has(rid)) return;
      planExecHandledRef.current.add(rid);
      rememberWatchedPlanExecution(rid, pid, conversationId);
      setPlanExecAdoptRunId(rid);
      setPlanExecAdoptPlanId(pid);
      if (!opts?.rehydrate) {
        setDockTab("plan");
        setAgentMode("normal");
        localStorage.setItem("aion_agent_mode", "normal");
        void updateConversationMetadata(
          conversationId,
          { agent_mode: "normal", plan_mode: false },
          userId,
          token,
        ).catch(() => {
          /* ignore */
        });
      }
    },
    [conversationId, userId, token],
  );

  usePlanExecutionRehydrate({
    conversationId,
    userId,
    token,
    enabled: planExecutionRehydrateReady,
    onAdopt: adoptPlanExecution,
    onRestorePlan: (planId, markdown) => {
      openPlanDockFromMarkdown(planId, markdown);
    },
  });

  const handlePlanFinalSummary = useCallback(
    (summary: string, _planId: string, runId?: string) => {
      const text = (summary || "").trim();
      if (!text) return;
      const rid = (runId || planExecAdoptRunId || "").trim();
      if (rid) {
        if (planFinalSummaryHandledRef.current.has(rid)) return;
        planFinalSummaryHandledRef.current.add(rid);
      }
      const aid = crypto.randomUUID();
      setMessages((m) => [...m, { id: aid, role: "assistant", content: text }]);
      // Documented exception: plan final summary is not persisted by the standard turn pipeline.
      void saveAssistantMessage(conversationId, aid, text, undefined, userId, token).catch((err) =>
        console.error("[aion-chat-ui] save plan summary:", err),
      );
      setPlanExecAdoptRunId(null);
      setPlanExecAdoptPlanId(null);
      setChatView({ kind: "main" });
      void refreshThreads();
    },
    [conversationId, userId, token, refreshThreads, planExecAdoptRunId],
  );

  const handlePlanExecutionAdoptHandled = useCallback(() => {
    setPlanExecAdoptRunId(null);
    setPlanExecAdoptPlanId(null);
    setChatView({ kind: "main" });
  }, []);

  const refreshPlanExecutionHistory = useCallback(
    async (opts?: { syncAssistantId?: string | null }) => {
      // Background plan-execution turns set stream-active without a client SSE session;
      // still refresh so task chat can hydrate from DB.
      if (
        streamingRef.current &&
        streamingConversationIdRef.current === conversationId
      ) {
        return;
      }
      try {
        const result = await fetchConversationHistory(conversationId, userId, token, undefined, {
          includePlanInternal: true,
        });
        if (activeConversationRef.current !== conversationId) return;
        const mapped = result.messages.map(historyMessageFromApi);
        setMessages((prev) => {
          const { next, error } = applyHistoryToMessages(
            prev,
            mapped,
            result,
            conversationId,
            transcriptStreaming,
            { source: "plan-execution", mode: "merge" },
          );
          if (error) setHistoryError(error);
          return next;
        });
        const syncId = (opts?.syncAssistantId || "").trim();
        if (result.ok && syncId) {
          const apiMsg = result.messages.find((m) => m.id === syncId);
          if (apiMsg?.role === "assistant") {
            const hydrated = historyMessageFromApi(apiMsg);
            setTurnVisual(
              turnStateFromHistoryMessage({
                reasoning: hydrated.reasoning,
                content: hydrated.content,
                steps: hydrated.steps,
                artifacts: hydrated.artifacts,
                timeline: hydrated.segments,
              }),
            );
          }
        }
      } catch {
        /* keep transcript */
      }
    },
    [conversationId, userId, token, transcriptStreaming, streamingConversationIdRef],
  );

  const planExecutionProgress = usePlanExecutionProgress(planExecAdoptRunId, userId, token, {
    onTaskDone: () => {
      void refreshPlanExecutionHistory();
    },
  });

  useEffect(() => {
    if (!planExecAdoptRunId || !planExecutionProgress?.tasks?.length) return;
    if (!planExecutionProgress.done && planExecutionProgress.status === "running") return;
    void refreshPlanExecutionHistory();
  }, [
    planExecAdoptRunId,
    planExecutionProgress?.done,
    planExecutionProgress?.status,
    planExecutionProgress?.tasks?.length,
    refreshPlanExecutionHistory,
  ]);

  const openPlanTaskId = chatView.kind === "task" ? chatView.taskId : null;
  const openPlanTask = useMemo(
    () => findPlanTask(planExecutionProgress?.tasks, openPlanTaskId),
    [planExecutionProgress?.tasks, openPlanTaskId],
  );

  const openPlanTaskView = useCallback(
    (taskId: string) => {
      const tid = taskId.trim();
      if (!tid) return;
      setChatView({ kind: "task", taskId: tid });
      void refreshPlanExecutionHistory();
    },
    [refreshPlanExecutionHistory],
  );

  const mainFeedMessages = useMemo(() => {
    let list = visibleMessages.filter((m) => m.role !== "internal" && !m.metadata?.memorized_message_id);
    if (planExecAdoptRunId && planExecutionProgress?.tasks?.length) {
      const planMsgIds = allPlanExecutionMessageIds(planExecutionProgress.tasks);
      if (planMsgIds.size) {
        list = list.filter(
          (m) => !planMsgIds.has(m.id) && !(m.metadata?.plan_task_id || "").trim(),
        );
      }
    }
    return list;
  }, [visibleMessages, planExecAdoptRunId, planExecutionProgress?.tasks]);

  const taskViewLiveAssistantId = useMemo(() => {
    if (chatView.kind !== "task" || !openPlanTask || !recoveryAssistantId) return null;
    const tid = openPlanTask.task_id;
    const ids = messageIdsForPlanTask(openPlanTask);
    if (ids.has(recoveryAssistantId)) return recoveryAssistantId;
    const recoveryMsg = messages.find((m) => m.id === recoveryAssistantId);
    const metaTid = (recoveryMsg?.metadata?.plan_task_id || "").trim();
    if (metaTid && metaTid === tid) return recoveryAssistantId;
    const progressTid = (planExecutionProgress?.progress?.task_id || "").trim();
    const livePhase =
      planExecutionProgress?.progress?.phase === "task_start" ||
      planExecutionProgress?.progress?.phase === "task_turn_started";
    if (progressTid === tid && livePhase) return recoveryAssistantId;
    return null;
  }, [
    chatView.kind,
    openPlanTask,
    recoveryAssistantId,
    messages,
    planExecutionProgress?.progress?.phase,
    planExecutionProgress?.progress?.task_id,
  ]);

  const taskViewMessages = useMemo(() => {
    if (!openPlanTask) return [];
    // Use full transcript: visibleMessages hides the recovery assistant during background runs.
    let list = messages.filter((m) => isMessageInPlanTask(m, openPlanTask));
    if (taskViewLiveAssistantId) {
      list = list.filter(
        (m) => !(m.id === taskViewLiveAssistantId && m.role === "assistant"),
      );
    }
    return list;
  }, [messages, openPlanTask, taskViewLiveAssistantId]);

  const showMainTurnVisual = Boolean(
    turnVisual &&
    chatView.kind === "main" &&
    !memorizingMessageId &&
    !(
      planExecAdoptRunId &&
      recoveryAssistantId &&
      allPlanExecutionMessageIds(planExecutionProgress?.tasks).has(recoveryAssistantId)
    ),
  );

  const showEmptyState = useMemo(
    () =>
      chatView.kind === "main" &&
      mainFeedMessages.length === 0 &&
      !streaming &&
      !streamRecovery &&
      !showMainTurnVisual &&
      !historyError,
    [
      chatView.kind,
      mainFeedMessages.length,
      streaming,
      streamRecovery,
      showMainTurnVisual,
      historyError,
    ],
  );

  const handleEmptySuggestion = useCallback((text: string) => {
    setInput(text);
    requestAnimationFrame(() => {
      composerTextareaRef.current?.focus();
    });
  }, []);

  const handleCancelPlanExecution = useCallback(async () => {
    const rid = (planExecAdoptRunId || "").trim();
    if (!rid) return;
    try {
      await cancelPlanExecution(rid, userId, token);
    } catch {
      /* ignore */
    }
  }, [planExecAdoptRunId, userId, token]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && chatView.kind === "task") {
        setChatView({ kind: "main" });
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [chatView.kind]);

  useEffect(() => {
    const taskParam = (searchParams.get("task") || "").trim();
    if (!taskParam || !planExecutionProgress?.tasks?.length) return;
    if (findPlanTask(planExecutionProgress.tasks, taskParam)) {
      setChatView({ kind: "task", taskId: taskParam });
    }
  }, [searchParams, planExecutionProgress?.tasks]);

  const runChatRequest = useCallback(
    async (
      message: string,
      opts?: {
        message_source?: "user_input" | "internal_trigger";
        /** Post-approval execution must use normal mode (full tool list). */
        agentModeOverride?: AgentMode;
        planModeOverride?: boolean;
        deepResearchModeOverride?: boolean;
        /** Hide orchestration system prompts from the chat transcript. */
        showUserBubble?: boolean;
        metadata?: Record<string, any>;
      },
    ) => {
      const effectiveAgentMode = opts?.agentModeOverride ?? agentMode;
      const effectivePlanMode =
        opts?.planModeOverride !== undefined
          ? opts.planModeOverride
          : effectiveAgentMode === "plan";
      const effectiveDeepResearchMode =
        opts?.deepResearchModeOverride !== undefined
          ? opts.deepResearchModeOverride
          : effectiveAgentMode === "deep_research";
      let uidMsg = crypto.randomUUID();
      let aid = crypto.randomUUID();
      setActiveMessageId(aid);

      const hasPendingFiles = pendingFiles.length > 0;
      const uploads = await uploadSessionFiles(conversationId, userId, pendingFiles, token);
      setPendingFiles([]);
      void fetchSessionFiles();
      // Fetch existing session uploads only when new files were uploaded,
      // so previous uploads aren't incorrectly attached to the current message.
      const existing = hasPendingFiles ? await listSessionUploads(conversationId, userId, token) : [];
      const attachments = hasPendingFiles ? mergeAttachmentRefs(uploads, existing) : [];

      const userArtifacts: ChatHistoryArtifact[] = uploads.map((a, i) => ({
        id: `att-${i}-${Date.now()}`,
        storage_key: a.relative_path,
        original_name: a.original_name || a.relative_path.split("/").pop() || "file",
        mime: a.mime || "application/octet-stream",
        size_bytes: 0,
        kind: "user_attachment",
        created_at: new Date().toISOString(),
      }));

      if (opts?.showUserBubble !== false) {
        setMessages((m) => [
          ...m,
          {
            id: uidMsg,
            role: "user",
            content: message,
            artifacts: userArtifacts.length ? userArtifacts : undefined,
          },
        ]);
      }

      let state = newTurn();
      setStreamEpoch((e) => e + 1);
      setTurnVisual(state);
      streamingRef.current = true;
      markStreamConversation(conversationId);
      setStreaming(true);
      setStreamRecovery(false);
      streamRecoveryRef.current = false;
      writeActiveStreamMarker(conversationId, {
        assistantMessageId: aid,
        userMessageId: uidMsg,
      });
      if ((opts?.message_source ?? "user_input") === "user_input" && opts?.showUserBubble !== false) {
        void saveChatMessage(conversationId, uidMsg, "user", message, userId, token).catch((err) =>
          console.error("[aion-chat-ui] early user save:", err),
        );
      }
      setPostTurnCharts([]);
      setPostTurnFiles([]);
      abortRef.current = new AbortController();

      const debug = chatStreamDebug;
      let tokenChunks = 0;
      let reasoningChunks = 0;
      let sawReasoning = false;

      try {
        const stream = await postChatStream(
          {
            message,
            session_id: conversationId,
            profile: activeProfileSlug,
            user_id: userId,
            reasoning_effort: reasoningEffort,
            thinking_enabled: thinkingEnabled,
            agent_mode: effectiveAgentMode,
            plan_mode: effectivePlanMode,
            deep_research_mode: effectiveDeepResearchMode,
            attachments: attachments.length ? attachments : undefined,
            turn_attachments: uploads.length ? uploads : undefined,
            user_message_id: uidMsg,
            assistant_message_id: aid,
            message_source: opts?.message_source ?? "user_input",
            web_search_enabled: webSearchEnabled,
            web_search_restrict_hosts: webRestrictHosts.length ? webRestrictHosts : undefined,
            sql_query_project: showProjectMemory && sqlQueryProject.trim()
              ? sqlQueryProject.trim()
              : undefined,
            llm_provider_name: selectedProvider || undefined,
            metadata: opts?.metadata,
          },
          token,
          abortRef.current.signal
        );

        await consumeChatStream(stream, (chunk) => {
          if (chunk.type === "turn_started") {
            const uid = String(chunk.user_message_id || uidMsg);
            const asst = String(chunk.assistant_message_id || aid);
            writeActiveStreamMarker(conversationId, {
              assistantMessageId: asst,
              userMessageId: uid,
            });
            // Sync local IDs with server-confirmed IDs from turn_started
            // and the final setMessages call use the correct IDs, preventing
            // duplicate messages on reload.
            if (uid !== uidMsg) {
              const prevUid = uidMsg;
              uidMsg = uid;
              // Patch the optimistic user message ID in state
              setMessages((prev) =>
                prev.map((m) => (m.id === prevUid ? { ...m, id: uid } : m))
              );
            }
            if (asst !== aid) {
              aid = asst;
            }
            return;
          }
          if (chunk.type === "token") tokenChunks += 1;
          if (chunk.type === "reasoning") {
            reasoningChunks += 1;
            sawReasoning = true;
          }
          state = reduceChunk(state, chunk);
          setTurnVisual({ ...state });

          if (chunk.type === "tool_event") {
            const ev = (chunk.event || {}) as Record<string, unknown>;
            if (ev.type === "tool_end" && ev.name === "trigger_research") {
              try {
                const out = JSON.parse(String(ev.output || "{}")) as {
                  research_session_id?: string;
                  ui_event?: string;
                  query?: string;
                };
                const rsid = out.research_session_id;
                if (rsid && out.ui_event === "research_started") {
                  adoptResearchSession(rsid, out.query || null, "tool_event");
                }
              } catch {
                /* ignore */
              }
            }
            // A tool completed successfully → clear stale warm-up errors.
            if (ev.type === "tool_end") {
              refreshMcpAlerts({ probe: false });
            }
          }
          if (planTextParserEnabled && chunk.type === "plan_progress") {
            const md = String((chunk as { plan_markdown?: string }).plan_markdown || "").trim();
            if (md) {
              updatePlanDockStreaming("streaming-plan", md, { title: "Execution Plan", type: "plan" });
            }
          }
          if (chunk.type === "orchestration_plan_pending") {
            openPlanDockFromChunk(chunk as PlanPendingChunk);
          }
          if (chunk.type === "plan_error") {
            /* surfaced via reducer status segment */
          }
          if (chunk.type === "prompt_snapshot" && chunk.snapshot) {
            const snap = chunk.snapshot as PromptSnapshot;
            const aid = String(chunk.assistant_message_id || snap.assistant_message_id || "");
            setPromptSnapshots((prev) => {
              const merged = {
                ...snap,
                assistant_message_id: aid || snap.assistant_message_id,
                stored_at_ms: snap.stored_at_ms || Date.now(),
              };
              if (!aid) {
                return [merged, ...prev];
              }
              const existing = prev.find((row) => row.assistant_message_id === aid);
              if (existing) {
                return prev.map((row) =>
                  row.assistant_message_id === aid ? { ...existing, ...merged } : row
                );
              }
              return [merged, ...prev];
            });
            // Do not auto-open the prompt debug tab on every turn
            /*
            if (showPromptDebug) {
              setDockTab("prompt_debug");
            }
            */
          }
          if (chunk.type === "presentation_preview") {
            const rp = String((chunk as { relative_path?: string }).relative_path || "").trim();
            if (rp) {
              setDockTab("artifacts");
            }
          }
          if (planTextParserEnabled && chunk.type === "artifact_start") {
            const art = (chunk.artifact || {}) as Record<string, unknown>;
            const aid = String(art.identifier || "");
            if (aid && isPlanArtifact(art)) {
              updatePlanDockStreaming(aid, "", art);
            } else if (aid) {
              setDockTab("artifacts");
            }
          }
          if (planTextParserEnabled && chunk.type === "artifact_content") {
            for (const id of state.artifactOrder) {
              const artifact = state.artifacts[id];
              if (!artifact || artifact.savedPath) continue;
              if (
                artifact.artType.toLowerCase() === "plan" ||
                isPlanArtifact(
                  { identifier: id, type: artifact.artType, title: artifact.title },
                  artifact.buffer,
                )
              ) {
                updatePlanDockStreaming(id, artifact.buffer, {
                  identifier: id,
                  type: artifact.artType,
                  title: artifact.title,
                });
              }
            }
          }
          if (planTextParserEnabled && chunk.type === "token" && state.planCaptureActive) {
            const md = extractStreamingPlanMarkdown(state.assistantContent);
            if (md) {
              updatePlanDockStreaming("streaming-plan", md, { title: "Execution Plan", type: "plan" });
            }
          }
          if (chunk.type === "artifact_end") {
            const art = (chunk.artifact || {}) as Record<string, unknown>;
            const aid = String(art.identifier || "");
            const savedPath = String(art.path || "");
            const cur = aid ? state.artifacts[aid] : undefined;
            const buf = cur?.buffer || "";
            const isPlan = aid ? isPlanArtifact(art, buf) : false;
            if (
              planTextParserEnabled &&
              aid &&
              isPlan &&
              !planChunkRef.current?.plan_id &&
              buf.trim() &&
              !String(art.storage_key || "").startsWith("orchestration://")
            ) {
              openPlanDockFromMarkdown(aid, buf, art);
            }
            if (savedPath && !isPlan) {
              setDockTab("artifacts");
            }
          }
        });

        setTurnVisual({ ...state });

        if (debug) {
          console.info("[aion-chat-ui] stream done", {
            tokenChunks,
            reasoningChunks,
            thinkingEnabled,
            reasoning_effort: effectiveEffort,
          });
        }

        const strippedContent = (
          planTextParserEnabled
            ? stripPlanBlocksForChatDisplay(state.assistantContent)
            : state.assistantContent
        ) || "";
        const isPlanGuardError = Boolean(
          state.error?.includes("Plan Mode:") &&
          (state.error.includes("missing_plan_tag") ||
            state.error.includes("approvazione sidebar")),
        );
        let assistantText = strippedContent;
        if (!assistantText.trim() && state.error && !isPlanGuardError) {
          assistantText = t("chat.error", { msg: state.error });
        }
        const reasoningUnavailable =
          thinkingEnabled && !sawReasoning && assistantText.trim().length > 0 && !state.error;
        const completedSteps = turnSteps(state);
        const completedArtifacts = turnArtifacts(state);

        {
          const persistedSegments = segmentsForPersist(state.segments);
          if (activeConversationRef.current === conversationId) {
            setMessages((m) => [
              ...m,
              {
                id: aid,
                role: "assistant",
                content: assistantText,
                reasoning: state.reasoning.trim() || undefined,
                steps: completedSteps.length ? completedSteps : undefined,
                artifacts: completedArtifacts.length ? completedArtifacts : undefined,
                segments: persistedSegments.length ? persistedSegments : undefined,
                reasoningUnavailable,
                webSources: state.webSourceCards.length ? state.webSourceCards : undefined,
              },
            ]);
          }
        }

        if (activeConversationRef.current !== conversationId) {
          await refreshThreads();
          return;
        }

        const ch = await fetchSessionCharts(conversationId, userId, token);
        setPostTurnCharts(ch);

        const newLinks: { rp: string; label: string }[] = [];
        for (const sub of ["workspace", "derived"] as const) {
          const rows = await listSessionFilesSubdir(conversationId, userId, sub, token);
          for (const row of rows) {
            const rp = row.relative_path;
            if (!rp || seenFilesRef.current.has(rp)) continue;
            seenFilesRef.current.add(rp);
            newLinks.push({ rp, label: row.name || rp });
          }
        }
        setPostTurnFiles(newLinks);
        refreshMcpAlerts({ probe: false });
        try {
          if (activeConversationRef.current !== conversationId) return;
          const result = await fetchConversationHistory(conversationId, userId, token);
          if (activeConversationRef.current !== conversationId) return;
          const mapped = result.messages.map(historyMessageFromApi);
          setMessages((prev) => {
            const { next, error } = applyHistoryToMessages(
              prev,
              mapped,
              result,
              conversationId,
              transcriptStreaming,
              { source: "post-stream", mode: "merge" },
            );
            if (error) setHistoryError(error);
            return next;
          });
          if (
            result.ok &&
            result.messages.length === 0 &&
            activeConversationRef.current === conversationId
          ) {
            const retry = await fetchConversationHistory(conversationId, userId, token);
            if (activeConversationRef.current !== conversationId) return;
            if (retry.ok && retry.messages.length > 0) {
              const retryMapped = retry.messages.map(historyMessageFromApi);
              setMessages((prev) =>
                applyHistoryToMessages(
                  prev,
                  retryMapped,
                  retry,
                  conversationId,
                  transcriptStreaming,
                  { source: "post-stream-retry", mode: "merge" },
                ).next,
              );
            }
          }
        } catch {
          /* keep optimistic transcript */
        }
        await refreshThreads();
      } catch (e: unknown) {
        const aborted =
          (e instanceof DOMException && e.name === "AbortError") ||
          (e instanceof Error && e.name === "AbortError");
        if (aborted) {
          const partialText = (state.assistantContent ?? "").trim();
          if (partialText && activeConversationRef.current === conversationId) {
            const partialReasoning = state.reasoning?.trim() || undefined;
            const STOP_BADGE = `\n\n---\n*⚠️ ${t("chat.interrupted")}*`;
            const contentToSave = partialText + STOP_BADGE;

            const completedSteps = turnSteps(state);
            const completedArtifacts = turnArtifacts(state);
            const partialSegments = segmentsForPersist(state.segments);
            setMessages((m) => [
              ...m,
              {
                id: aid,
                role: "assistant",
                content: contentToSave,
                reasoning: partialReasoning,
                steps: completedSteps.length ? completedSteps : undefined,
                artifacts: completedArtifacts.length ? completedArtifacts : undefined,
                segments: partialSegments.length ? partialSegments : undefined,
              },
            ]);

            void refreshThreads();
          }
          return;
        }
        const msg = e instanceof Error ? e.message : String(e);
        setMessages((m) => [...m, { id: crypto.randomUUID(), role: "assistant", content: `❌ ${msg}` }]);
      } finally {
        streamingRef.current = false;
        markStreamConversation(null);
        streamFinishedAtRef.current = Date.now();
        setStreaming(false);
        setStreamRecovery(false);
        streamRecoveryRef.current = false;
        setRecoveryAssistantId(null);
        setActiveMessageId(null);
        setTurnVisual(null);
        clearActiveStreamMarker(conversationId);
        abortRef.current = null;
      }
    },
    [
      conversationId,
      userId,
      token,
      activeProfileSlug,
      effectiveEffort,
      pendingFiles,
      thinkingEnabled,
      markStreamConversation,
      transcriptStreaming,
      openPlanDockFromChunk,
      openPlanDockFromMarkdown,
      updatePlanDockStreaming,
      refreshThreads,
      webSearchEnabled,
      webRestrictHosts,
      agentMode,
      sqlQueryProject,
      showProjectMemory,
      showPromptDebug,
      chatStreamDebug,
      adoptResearchSession,
      selectedProvider,
    ]
  );

  const handleMemorize = useCallback(async (msgId: string) => {
    const msgIdx = messages.findIndex((msg) => msg.id === msgId);
    if (msgIdx === -1) return;

    const clickedMsg = messages[msgIdx];

    // Find the preceding user message (the question)
    let userQuestion = "";
    for (let i = msgIdx - 1; i >= 0; i--) {
      if (messages[i].role === "user") {
        userQuestion = messages[i].content;
        break;
      }
    }

    let assistantThinking = clickedMsg.reasoning || "";
    let assistantResponse = clickedMsg.content || "";

    if (clickedMsg.segments && clickedMsg.segments.length > 0) {
      const thinkingParts: string[] = [];
      const responseParts: string[] = [];
      for (const seg of clickedMsg.segments) {
        if (seg.kind === "reasoning" && seg.content) {
          thinkingParts.push(seg.content);
        } else if (seg.kind === "text" && seg.content) {
          responseParts.push(seg.content);
        }
      }
      if (thinkingParts.length > 0) {
        assistantThinking = thinkingParts.join("\n").trim();
      }
      if (responseParts.length > 0) {
        assistantResponse = responseParts.join("\n").trim();
      }
    }

    const turnDetails = [
      `[Domanda Utente]\n${userQuestion.trim()}`,
      assistantThinking.trim() ? `[Thinking Agente]\n${assistantThinking.trim()}` : "",
      `[Risposta Agente]\n${assistantResponse.trim()}`
    ].filter(Boolean).join("\n\n");

    const hasNoActiveProject = !sqlQueryProject || sqlQueryProject === "default";
    if (hasNoActiveProject) {
      setProjectWarningModalOpen(true);
      return;
    }

    setMemorizingMessageId(msgId);
    setIsSavingInfo(true);
    try {
      const activeProject = sqlQueryProject;
      const projectWingName = `wing_proj_${activeProject}`;

      const instruction = t("chat.actions.memorize_instruction");
      const prompt = `${instruction}\n\n[Active Project Context]\nActive SQL QueryMemory project slug: "${activeProject}"\nMemPalace project wing: "${projectWingName}"\n\n[Conversation Turn to Memorize]\n${turnDetails}`;
      await runChatRequest(prompt, {
        message_source: "internal_trigger",
        showUserBubble: false,
        metadata: { memorized_message_id: msgId },
      });
    } catch (err) {
      console.error("[aion-chat-ui] error during memorization:", err);
    } finally {
      setIsSavingInfo(false);
      setMemorizingMessageId(null);
    }
  }, [messages, sqlQueryProject, runChatRequest, t]);

  const handleSaveEdit = useCallback(async (msgId: string) => {
    const newText = editInput.trim();
    if (!newText || streaming) return;

    setEditingMessageId(null);
    setStreaming(true);

    try {
      const res = await fetch(`${apiBase()}/chat-ui/conversations/${conversationId}/messages/${msgId}`, {
        method: "DELETE",
        headers: baseUserHeaders(userId, token),
      });

      if (!res.ok) {
        throw new Error(`Failed to prune old turns: ${res.statusText}`);
      }

      setMessages((prev) => {
        const idx = prev.findIndex((msg) => msg.id === msgId);
        if (idx === -1) return prev;
        return prev.slice(0, idx);
      });

      setPostTurnCharts([]);
      setPostTurnFiles([]);
      setPlanChunk(null);

      await runChatRequest(newText);
    } catch (err) {
      console.error("Error editing message:", err);
    } finally {
      setStreaming(false);
    }
  }, [conversationId, editInput, streaming, userId, token, runChatRequest]);

  const handleRegenerate = useCallback(async () => {
    if (streaming || !lastUserMessageId) return;

    const lastUserMsg = messages.find((msg) => msg.id === lastUserMessageId);
    if (!lastUserMsg) return;

    const userText = lastUserMsg.content.trim();
    if (!userText) return;

    setStreaming(true);

    try {
      const res = await fetch(`${apiBase()}/chat-ui/conversations/${conversationId}/messages/${lastUserMessageId}`, {
        method: "DELETE",
        headers: baseUserHeaders(userId, token),
      });

      if (!res.ok) {
        throw new Error(`Failed to prune old turn for regeneration: ${res.statusText}`);
      }

      setMessages((prev) => {
        const idx = prev.findIndex((msg) => msg.id === lastUserMessageId);
        if (idx === -1) return prev;
        return prev.slice(0, idx);
      });

      setPostTurnCharts([]);
      setPostTurnFiles([]);
      setPlanChunk(null);

      await runChatRequest(userText);
    } catch (err) {
      console.error("Error regenerating response:", err);
    } finally {
      setStreaming(false);
    }
  }, [conversationId, lastUserMessageId, messages, streaming, userId, token, runChatRequest]);

  useEffect(() => {
    fetchProfiles(userId, token)
      .then((p) => {
        setProfiles(p);
        if (p.length) {
          setProfile((curr) => {
            const matched = p.find((x) => x.slug === curr || x.name === curr);
            if (matched) {
              return matched.slug || matched.name;
            }
            return p[0].slug || p[0].name;
          });
        }
      })
      .catch((e: unknown) => console.error("profiles fetch", e));
    queueMicrotask(() => {
      void refreshThreads().catch((e: unknown) => console.error("threads refresh", e));
    });
  }, [userId, token, refreshThreads]);

  // Carica le preferenze di Thinking, Reasoning Effort e Profilo quando cambia conversationId
  useEffect(() => {
    if (!conversationId) return;

    // Reset immediato a "aion_std" (o primo profilo abilitato) per le nuove chat / fallback
    const defaultProfile = profiles.some((x) => x.slug === "aion_std") ? "aion_std" : (profiles[0]?.slug || "aion_std");
    setProfile(defaultProfile);
    setSqlQueryProject(readStoredSqlProject());
    setConversationTitle(null);

    // 1. Carica prima i valori di fallback locali (localStorage)
    const storedThinking = localStorage.getItem("aion_last_thinking_enabled");
    const storedEffort = localStorage.getItem("aion_last_reasoning_effort");
    const storedAgentMode = localStorage.getItem("aion_agent_mode") || "normal";

    let initialThinking = true;
    let initialEffort: "min" | "medium" | "max" = "medium";

    if (storedThinking !== null) {
      initialThinking = storedThinking === "true";
    }
    if (storedEffort === "min" || storedEffort === "medium" || storedEffort === "max") {
      initialEffort = storedEffort as "min" | "medium" | "max";
    }

    setThinkingEnabled(initialThinking);
    setReasoningEffort(initialEffort);
    setAgentMode(storedAgentMode as AgentMode);

    // 2. Chiedi i dettagli della conversazione al DB per l'override specifico
    const cid = conversationId;
    fetchConversationDetails(cid, userId, token)
      .then((details) => {
        if (activeConversationRef.current !== cid) return;
        if (details) {
          if (details.profile_slug) {
            setProfile(details.profile_slug);
          }
          if (details.title) {
            setConversationTitle(details.title);
          }
          if (details.metadata) {
            const meta = details.metadata;
            if (typeof meta.thinking_enabled === "boolean") {
              setThinkingEnabled(meta.thinking_enabled);
              localStorage.setItem("aion_last_thinking_enabled", String(meta.thinking_enabled));
            }
            if (meta.reasoning_effort === "min" || meta.reasoning_effort === "medium" || meta.reasoning_effort === "max") {
              setReasoningEffort(meta.reasoning_effort as "min" | "medium" | "max");
              localStorage.setItem("aion_last_reasoning_effort", meta.reasoning_effort);
            }
            if (
              meta.agent_mode === "normal" ||
              meta.agent_mode === "plan" ||
              meta.agent_mode === "ask" ||
              meta.agent_mode === "debug" ||
              meta.agent_mode === "deep_research"
            ) {
              setAgentMode(meta.agent_mode as AgentMode);
              localStorage.setItem("aion_agent_mode", meta.agent_mode);
            }
            if (typeof meta.sql_query_project === "string" && meta.sql_query_project.trim()) {
              setSqlQueryProject(meta.sql_query_project.trim());
            }
          }
        }
      })
      .catch((err) => {
        console.debug("Could not fetch conversation details (new conversation):", err);
      });
  }, [conversationId, userId, token, profiles]);

  useEffect(() => {
    if (!conversationId) return;

    // Resetta immediatamente i messaggi e lo stato del dock per evitare la permanenza della vecchia chat
    setMessages([]);
    setHistoryError(null);
    setStreamRecovery(false);
    setRecoveryAssistantId(null);
    streamRecoveryRef.current = false;
    setTurnVisual(null);
    setPostTurnFiles([]);
    setChatView({ kind: "main" });
    setPlanExecAdoptRunId(null);
    setPlanExecAdoptPlanId(null);
    planExecHandledRef.current = new Set();
    planFinalSummaryHandledRef.current = new Set();
    setPlanExecutionRehydrateReady(false);
    setDockTab("none");
    setPlanChunk(null);
    // setDbTableHint(null);

    const cid = conversationId;
    const loadEpoch = bumpHistoryLoadEpoch();
    const ac = new AbortController();
    seenFilesRef.current = new Set();
    queueMicrotask(() => {
      if (activeConversationRef.current === cid) setPostTurnFiles([]);
    });
    fetchConversationHistory(cid, userId, token, ac.signal)
      .then((result) => {
        if (isStaleHistoryLoad(cid, loadEpoch)) return;
        const mapped = result.messages.map(historyMessageFromApi);
        setMessages((prev) => {
          const { next, error } = applyHistoryToMessages(
            prev,
            mapped,
            result,
            cid,
            transcriptStreaming,
            { loadEpoch, source: "sidebar-load", mode: "replace" },
          );
          if (error && activeConversationRef.current === cid) {
            setHistoryError(error);
          } else if (result.ok && activeConversationRef.current === cid) {
            setHistoryError(null);
          }
          return next;
        });

        const hist = result.ok ? result.messages : [];
        const ratingsMap: Record<string, MessageRating> = {};
        hist.forEach((m) => {
          if (m.rating === 1 || m.rating === -1) {
            ratingsMap[m.id] = m.rating as MessageRating;
          }
        });
        setMessageRatings((prev) => ({ ...prev, ...ratingsMap }));

        // 1. Sincronizza Agent DB table hint da cronologia (disabilitato)
        /*
        let foundDbHint = false;
        for (let i = hist.length - 1; i >= 0; i--) {
          const m = hist[i];
          if (m.role === "user" && m.content.trim().startsWith("/db")) {
            const parts = m.content.trim().split(/\s+/);
            const hint = parts.length >= 3 ? parts[2] : null;
            setDbTableHint(hint);
            foundDbHint = true;
            break;
          }
        }
        if (!foundDbHint) {
          setDbTableHint(null);
        }
        */

        // 2. Sincronizza Piano da cronologia
        {
          let foundPlan = false;
          for (let i = hist.length - 1; i >= 0; i--) {
            const m = hist[i];
            if (m.artifacts && m.artifacts.length > 0) {
              const planArt = m.artifacts.find(isHistoricalPlanArtifact);
              if (planArt) {
                const sk = String(planArt.storage_key || "");
                if (sk.startsWith("orchestration://")) {
                  foundPlan = true;
                  break;
                }
                const url = sessionDownloadUrl(cid, planArt.storage_key, token);
                fetch(url)
                  .then((r) => {
                    if (!r.ok) throw new Error("Failed to fetch plan file");
                    return r.text();
                  })
                  .then((text) => {
                    if (activeConversationRef.current !== cid) return;
                    openPlanDockFromMarkdown(planArt.id, text, {
                      identifier: planArt.id,
                      type: "plan",
                      title: planArt.original_name || "Execution Plan",
                    });
                  })
                  .catch((err) => console.error("Error fetching historical plan:", err));
                foundPlan = true;
                break;
              }
            }
          }
          if (!foundPlan) {
            setPlanChunk(null);
          }
        }

        if (activeConversationRef.current === cid) {
          setPlanExecutionRehydrateReady(true);
        }
      })
      .catch((e: unknown) => {
        const aborted =
          (e instanceof DOMException && e.name === "AbortError") ||
          (e instanceof Error && e.name === "AbortError");
        if (aborted) return;
        console.error("Error fetching history", e);
        if (activeConversationRef.current === cid) {
          setPlanExecutionRehydrateReady(true);
        }
      });
    Promise.all(
      (["workspace", "derived"] as const).map((sub) =>
        listSessionFilesSubdir(cid, userId, sub, token)
      )
    )
      .then((groups) => {
        if (activeConversationRef.current !== cid) return;
        const seen = new Set<string>();
        for (const rows of groups) {
          for (const row of rows) {
            if (row.relative_path) seen.add(row.relative_path);
          }
        }
        seenFilesRef.current = seen;
      })
      .catch((e: unknown) => {
        const aborted =
          (e instanceof DOMException && e.name === "AbortError") ||
          (e instanceof Error && e.name === "AbortError");
        if (aborted) return;
        console.error("session files seed", e);
      });
    return () => ac.abort();
  }, [
    conversationId,
    userId,
    token,
    openPlanDockFromChunk,
    bumpHistoryLoadEpoch,
    isStaleHistoryLoad,
    transcriptStreaming,
  ]);

  useEffect(() => {
    if (!conversationId || !userId) return;
    if (streamingRef.current && !streamRecoveryRef.current) return;

    let cancelled = false;

    const finishRecovery = async () => {
      streamRecoveryRef.current = false;
      setStreamRecovery(false);
      setRecoveryAssistantId(null);
      setActiveMessageId(null);
      streamingRef.current = false;
      setStreaming(false);
      setTurnVisual(null);
      clearActiveStreamMarker(conversationId);
      try {
        const result = await fetchConversationHistory(conversationId, userId, token);
        if (!cancelled && activeConversationRef.current === conversationId) {
          const mapped = result.messages.map(historyMessageFromApi);
          setMessages((prev) => {
            const { next, error } = applyHistoryToMessages(
              prev,
              mapped,
              result,
              conversationId,
              transcriptStreaming,
              { source: "recovery-finish", mode: "replace" },
            );
            if (error) setHistoryError(error);
            return next;
          });
        }
        await refreshThreads();
      } catch {
        /* ignore */
      }
    };

    const runSseRecovery = async () => {
      streamRecoveryRef.current = true;
      setStreamRecovery(true);
      streamingRef.current = true;
      setStreaming(true);

      while (!cancelled && activeConversationRef.current === conversationId) {
        let state = newTurn();
        setTurnVisual(state);

        try {
          const sseStream = await getChatStreamReconnect(conversationId, userId, token);
          if (cancelled || activeConversationRef.current !== conversationId) break;

          if (sseStream) {
            await consumeChatStream(sseStream, (chunk) => {
              if (cancelled || activeConversationRef.current !== conversationId) return;
              if (chunk.type === "turn_started") {
                const uid = String(chunk.user_message_id || "");
                const asst = String(chunk.assistant_message_id || "");
                setRecoveryAssistantId(asst || null);
                setActiveMessageId(asst || null);
                writeActiveStreamMarker(conversationId, {
                  assistantMessageId: asst,
                  userMessageId: uid,
                });
                return;
              }
              state = reduceChunk(state, chunk);
              setTurnVisual({ ...state });
            });
          }
        } catch (err) {
          console.error("[aion-chat-ui] SSE reconnect stream error:", err);
        }

        if (cancelled || activeConversationRef.current !== conversationId) break;
        const status = await fetchStreamStatus(conversationId, userId, token);
        if (!status.active) {
          break;
        }
        await new Promise((resolve) => setTimeout(resolve, 2000));
      }

      if (!cancelled && activeConversationRef.current === conversationId) {
        await finishRecovery();
      }
    };

    const maybeStart = async () => {
      const marker = readActiveStreamMarker(conversationId);
      const status = await fetchStreamStatus(conversationId, userId, token);
      if (cancelled || (streamingRef.current && !streamRecoveryRef.current)) return;
      if (status.active || marker || planExecAdoptRunId) {
        await runSseRecovery();
      } else if (marker) {
        clearActiveStreamMarker(conversationId);
      }
    };

    void maybeStart();

    const onVis = () => {
      if (document.visibilityState === "visible" && !streamingRef.current) {
        void maybeStart();
      }
    };
    document.addEventListener("visibilitychange", onVis);

    return () => {
      cancelled = true;
      document.removeEventListener("visibilitychange", onVis);
    };
  }, [conversationId, userId, token, refreshThreads, planExecAdoptRunId]);

  useEffect(() => {
    const ac = new AbortController();
    void (async () => {
      try {
        const body = await openSessionEventsStream(conversationId, userId, token, ac.signal);
        if (!body) return;
        await drainSessionEventsLoop(body, async (ev) => {
          if (ev.type === "orchestration_plan_pending") {
            const pending = planChunkFromRecord(ev);
            if (pending) openPlanDockFromChunk(pending);
            return;
          }
          if (streamingRef.current || internalBusyRef.current) return;
          if (ev.type !== "orchestration_plan_approved") return;
          const pid = String(ev.plan_id || "").trim();
          const rid = String((ev as { run_id?: string }).run_id || "").trim();
          if (!pid || !rid) return;
          adoptPlanExecution(rid, pid);
        });
      } catch (e: unknown) {
        const aborted =
          (e instanceof DOMException && e.name === "AbortError") ||
          (e instanceof Error && e.name === "AbortError");
        if (aborted) return;
        console.error("session events stream", e);
      }
    })();
    return () => ac.abort();
  }, [
    conversationId,
    userId,
    token,
    openPlanDockFromChunk,
    adoptPlanExecution,
  ]);

  const send = async () => {
    const t = input.trim();
    if (!t || streaming) return;
    if (isProjectRequiredButMissing) {
      setProjectCreateOpen(true);
      return;
    }
    /*
    if (t.startsWith("/db")) {
      const parts = t.split(/\s+/);
      const hint = parts.length >= 3 ? parts[2] : null;
      setDbTableHint(hint);
      setDockTab("agentdb");
      setInput("");
      setMessages((m) => [...m, { id: crypto.randomUUID(), role: "user", content: t }]);
      setMessages((m) => [
        ...m,
        { id: crypto.randomUUID(), role: "assistant", content: "Pannello Agent DB aperto sulla destra." },
      ]);
      return;
    }
    */
    setInput("");
    try {
      await refreshThreads();
    } catch (e: unknown) {
      console.error("refreshThreads", e);
    }
    await runChatRequest(t);
  };

  const stop = () => {
    abortRef.current?.abort();
    void chatStop(conversationId, userId, token).catch(() => {
      /* ignore network errors */
    });
  };

  useEffect(() => {
    if (!composerResizing) return;
    function onMouseMove(e: MouseEvent) {
      const maxCap = Math.max(COMPOSER_TEXTAREA_MIN, Math.floor(window.innerHeight * 0.45));
      const dy = composerResizeStartRef.current.y - e.clientY;
      const next = Math.min(
        maxCap,
        Math.max(COMPOSER_TEXTAREA_MIN, composerResizeStartRef.current.textMax + dy)
      );
      setComposerTextMax(next);
    }
    function onMouseUp() {
      setComposerResizing(false);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", onMouseUp);
    }
    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", onMouseUp);
    return () => {
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", onMouseUp);
    };
  }, [composerResizing]);

  const startComposerResize = useCallback(
    (e: React.MouseEvent<HTMLButtonElement>) => {
      e.preventDefault();
      composerResizeStartRef.current = { y: e.clientY, textMax: composerTextMax };
      document.body.style.cursor = "ns-resize";
      document.body.style.userSelect = "none";
      setComposerResizing(true);
    },
    [composerTextMax]
  );

  const tabsToRender = useMemo(() => {
    const list: DockTab[] = [
      "plan",
      "research",
      "artifacts",
      // "agentdb"
    ];
    if (showProjectMemory) list.push("memory");
    if (showPromptDebug) list.push("prompt_debug");
    if (pdfUrl || khubLoading || khubError) list.push("khub_file");
    return list;
  }, [pdfUrl, khubLoading, khubError, showProjectMemory, showPromptDebug]);

  const planLiveMarkdown = useMemo(() => {
    if (!turnVisual) return "";
    for (const id of turnVisual.artifactOrder) {
      const artifact = turnVisual.artifacts[id];
      if (!artifact || artifact.savedPath) continue;
      if (
        artifact.artType.toLowerCase() === "plan" ||
        isPlanArtifact(
          { identifier: id, type: artifact.artType, title: artifact.title },
          artifact.buffer,
        )
      ) {
        return artifact.buffer;
      }
    }
    if (turnVisual.planCaptureActive) {
      return extractStreamingPlanMarkdown(turnVisual.assistantContent);
    }
    return "";
  }, [turnVisual]);

  const planStreaming = Boolean(
    streaming &&
    turnVisual?.segments.some((s) => s.kind === "generating" && s.target === "plan"),
  );

  const dockTabs = (
    <div className="flex h-14 shrink-0 overflow-x-auto border-b border-border bg-card/80 text-xs backdrop-blur-sm no-scrollbar">
      {tabsToRender.map((tab) => (
        <button
          key={tab}
          type="button"
          className={cn(
            "focus-ring flex h-full min-w-[4.5rem] shrink-0 flex-1 items-center justify-center border-b-2 border-transparent px-2 font-medium transition-colors",
            dockTab === tab
              ? "border-primary bg-muted/50 text-foreground"
              : "text-muted-foreground hover:bg-muted/40 hover:text-foreground"
          )}
          onClick={() => setDockTab(tab)}
        >
          {t(`${tab}.title`)}
        </button>
      ))}
    </div>
  );

  const closeDock = useCallback(() => setDockTab("none"), []);

  const dockBody = (
    <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain">
      {dockTab !== "none" && (
        <div className={cn("h-full min-h-0", dockTab !== "research" && "hidden")}>
          <DeepResearchPanel
            userId={userId}
            token={token}
            conversationId={conversationId}
            adoptSessionId={researchAdoptId}
            adoptQuery={researchAdoptQuery}
            onAdoptHandled={() => {
              setResearchAdoptId(null);
              setResearchAdoptQuery(null);
            }}
          />
        </div>
      )}
      {dockTab === "plan" && (planChunk || planExecAdoptRunId) && (
        <PlanPanel
          chunk={planChunk}
          apiBaseUrl={apiBase()}
          sessionId={conversationId}
          remountKey={planMountKey}
          userId={userId}
          profileName={activeProfileSlug}
          token={token}
          planStreaming={planStreaming}
          planLiveMarkdown={planLiveMarkdown}
          adoptRunId={planExecAdoptRunId}
          adoptPlanId={planExecAdoptPlanId}
          executionProgress={planExecutionProgress}
          selectedTaskId={openPlanTaskId}
          onAdoptHandled={handlePlanExecutionAdoptHandled}
          onPlanApproved={adoptPlanExecution}
          onFinalSummary={handlePlanFinalSummary}
          onTaskSelect={(taskId) => {
            if (!taskId) setChatView({ kind: "main" });
            else openPlanTaskView(taskId);
          }}
        />
      )}
      {dockTab === "artifacts" && (
        <ArtifactsPanel
          items={dockArtifacts}
          sessionFiles={sessionFiles}
          loadingFiles={loadingFiles}
          onRefreshFiles={fetchSessionFiles}
          conversationId={conversationId}
          token={token}
        />
      )}
      {dockTab === "prompt_debug" && (
        <PromptDebugPanel snapshots={promptSnapshots} enabled={showPromptDebug} />
      )}
      {dockTab === "memory" && showProjectMemory && (
        <MemoryDockPanel
          userId={userId}
          sessionId={conversationId}
          token={token}
          profileSlug={activeProfileSlug}
          projectSlug={sqlQueryProject}
          onProjectChange={handleProjectChange}
          showSqlQueryMemory={showSqlQueryMemory}
          showNavigationMemory={showNavigationMemory}
        />
      )}
      {dockTab === "khub_file" && (
        <div className="flex flex-col h-full w-full bg-card text-foreground">
          {/* Header */}
          <div className="flex items-center justify-between p-3 border-b border-border bg-muted/20 shrink-0 select-none">
            <div className="flex items-center gap-2 min-w-0">
              <FileText size={15} className="text-primary shrink-0" />
              <span className="font-semibold text-xs truncate pr-2" title={pdfName}>{pdfName}</span>
            </div>
            <div className="flex items-center gap-1.5">
              {pdfUrl && (
                <a
                  href={pdfUrl}
                  download={pdfName}
                  className="flex items-center justify-center p-1.5 text-muted-foreground hover:text-foreground hover:bg-muted rounded-lg transition-all"
                  title={t("khub_file.download")}
                >
                  <Download size={15} />
                </a>
              )}
            </div>
          </div>

          {/* Body */}
          <div className="flex-1 w-full h-full min-h-0 relative bg-muted/5">
            {khubLoading ? (
              <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 text-muted-foreground animate-in fade-in-0 duration-300">
                <Loader2 className="animate-spin text-primary" size={24} />
                <span className="text-xs font-medium">{t("khub_file.loading")}</span>
              </div>
            ) : khubError ? (
              <div className="absolute inset-0 flex flex-col items-center justify-center p-6 text-center gap-3 animate-in fade-in-0 duration-300">
                <AlertCircle className="text-destructive" size={28} />
                <span className="text-sm font-semibold text-destructive">{t("khub_file.error")}</span>
                <span className="text-xs max-w-xs text-muted-foreground leading-relaxed">{khubError}</span>
              </div>
            ) : pdfUrl ? (
              <div className="absolute inset-0">
                <KhubPdfViewer src={pdfUrl} />
              </div>
            ) : (
              <div className="absolute inset-0 flex flex-col items-center justify-center p-4 text-center text-muted-foreground">
                <span className="text-xs">{t("khub_file.empty")}</span>
              </div>
            )}
          </div>
        </div>
      )}
      {dockTab === "none" && (
        <p className="p-4 text-xs text-muted-foreground">
          {t("dock.none_hint")}
        </p>
      )}
    </div>
  );

  const hasVisibleAssistantText = Boolean(
    turnVisual?.assistantContent?.trim() ||
    turnVisual?.segments.some((s) => s.kind === "text" && s.content.trim()),
  );
  const hasVisibleReasoning = Boolean(
    turnVisual?.reasoning?.trim() ||
    turnVisual?.segments.some((s) => s.kind === "reasoning" && s.content.trim()),
  );
  const hasRunningTool = Boolean(
    turnVisual?.segments.some((s) => s.kind === "tool" && s.status === "running"),
  );
  const hasGeneratingIndicator = Boolean(
    turnVisual?.segments.some((s) => s.kind === "generating"),
  );
  const hasStreamingArtifact = Boolean(
    turnVisual?.artifactOrder.some((id) => {
      const artifact = turnVisual.artifacts[id];
      if (!artifact || artifact.savedPath) return false;
      const isPlan =
        artifact.artType.toLowerCase() === "plan" ||
        isPlanArtifact(
          { identifier: id, type: artifact.artType, title: artifact.title },
          artifact.buffer,
        );
      return !isPlan && Boolean(artifact.buffer.trim());
    }),
  );
  const contextCompacting = Boolean(turnVisual?.contextCompacting);
  const showAgentWorkingShimmer = Boolean(
    streaming &&
    turnVisual &&
    !contextCompacting &&
    !hasVisibleAssistantText &&
    !hasVisibleReasoning &&
    !hasRunningTool &&
    !hasGeneratingIndicator &&
    !hasStreamingArtifact,
  );
  const showContextCompactingShimmer = Boolean(streaming && contextCompacting);
  const agentWorkingLabel = thinkingEnabled
    ? t("chat.agent_status.thinking")
    : t("chat.agent_status.working");

  const {
    setHeader,
    setDock,
    setDockOpen,
    clearChrome,
    setDockCloseHandler,
    toggleSidebar,
  } = shellActions;

  useLayoutEffect(() => {
    setDockCloseHandler(closeDock);
    return () => setDockCloseHandler(null);
  }, [setDockCloseHandler, closeDock]);

  useLayoutEffect(() => {
    setHeader(
      <ChatHeader
        conversationId={conversationId}
        profiles={profiles}
        profile={activeProfileName}
        onProfileChange={handleProfileChange}
        agentMode={agentMode}
        onAgentModeChange={handleAgentModeChange}
        dockTab={dockTab}
        onToggleDock={toggleDock}
        isSidebarOpen={sidebarOpen}
        onToggleSidebar={toggleSidebar}
        title={conversationTitle}
        onTitleChange={handleTitleChange}
        llmProviders={llmProviders}
        selectedProvider={selectedProvider}
        providersLoading={providersLoading}
        onProviderChange={setSelectedProvider}
      />,
    );
  }, [
    setHeader,
    sidebarOpen,
    toggleSidebar,
    conversationId,
    profiles,
    activeProfileName,
    handleProfileChange,
    agentMode,
    handleAgentModeChange,
    dockTab,
    toggleDock,
    conversationTitle,
    handleTitleChange,
    llmProviders,
    selectedProvider,
    providersLoading,
  ]);

  useLayoutEffect(() => {
    setDockOpen(dockTab !== "none");
    if (dockTab === "none") {
      setDock(null);
      return;
    }
    setDock(
      <>
        {dockTabs}
        {dockBody}
      </>,
    );
  });

  useLayoutEffect(() => {
    return () => clearChrome();
  }, [clearChrome]);

  return (
    <>
      <ChatDragDrop onFilesDropped={handleFilesDropped}>
        <div id="chat-pane" className="relative flex min-h-0 min-w-0 flex-1 flex-col overflow-x-hidden">
          <div
            ref={messagesContainerRef}
            className={cn(
              "flex-1 overflow-y-auto px-3 py-4 sm:px-4 sm:py-8",
              showEmptyState && "flex flex-col justify-center",
            )}
            aria-busy={streaming}
            aria-live="polite"
          >
            <div className="mx-auto w-full max-w-3xl flex flex-col">
              {historyError ? (
                <div
                  className="flex items-start gap-2 rounded-xl border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm text-destructive"
                  role="alert"
                >
                  <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden />
                  <span>{t("chat.history_load_error", { msg: historyError })}</span>
                </div>
              ) : null}
              {sessionPrepareStatus === "warming" && !streaming ? (
                <div
                  className="mb-4 flex items-center gap-2 rounded-xl border border-border/50 bg-muted/30 px-4 py-3 text-sm text-muted-foreground"
                  role="status"
                >
                  <Loader2 className="size-4 shrink-0 animate-spin text-primary" aria-hidden />
                  <ShimmerText>{t("chat.session_preparing")}</ShimmerText>
                </div>
              ) : null}
              {mcpRuntimeErrors.length > 0 && sessionPrepareStatus !== "warming" ? (
                <div
                  className="mb-4 rounded-xl border border-red-500/40 bg-red-500/10 px-4 py-3 text-sm"
                  role="alert"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex items-start gap-2">
                      <AlertTriangle className="mt-0.5 size-4 shrink-0 text-red-600 dark:text-red-400" aria-hidden />
                      <div>
                        <p className="font-medium text-red-800 dark:text-red-200">
                          {t("integrationsPage.composer_runtime_errors")}
                        </p>
                        <p className="mt-1 text-xs text-red-700/90 dark:text-red-300/90">
                          {t("chat.mcp_errors_hint")}
                        </p>
                        <ul className="mt-2 space-y-1 text-xs text-red-800/90 dark:text-red-200/90">
                          {mcpRuntimeErrors.slice(0, 3).map((p) => (
                            <li key={p.server_slug}>
                              <span className="font-medium">{p.display_name}</span>
                              {p.message ? ` — ${p.message}` : null}
                            </li>
                          ))}
                        </ul>
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={() => setMcpPendingOpen(true)}
                      className="shrink-0 rounded-lg border border-red-500/30 bg-background/80 px-2.5 py-1 text-xs font-medium text-red-800 hover:bg-red-500/10 dark:text-red-200"
                    >
                      {t("chat.mcp_errors_details")}
                    </button>
                  </div>
                </div>
              ) : null}
              {showEmptyState ? (
                <ChatEmptyState
                  profileName={activeProfileName}
                  onSuggestion={handleEmptySuggestion}
                />
              ) : null}
              {chatView.kind === "task" && openPlanTask && planExecutionProgress ? (
                <TaskChatView
                  task={openPlanTask}
                  tasks={planExecutionProgress.tasks}
                  messages={taskViewMessages}
                  progress={planExecutionProgress}
                  onBack={() => setChatView({ kind: "main" })}
                  onOpenTask={openPlanTaskView}
                  onCancel={handleCancelPlanExecution}
                  renderMessage={(m, msgIdx) => {
                    if (m.role === "internal") {
                      return (
                        <div className="my-3 rounded-lg border border-border/50 bg-muted/25 px-3 py-2 text-xs text-muted-foreground">
                          ▶ {t("chat.plan.task.starting")} <code className="font-mono">{openPlanTask.task_id}</code>
                        </div>
                      );
                    }
                    if (m.role !== "assistant") return null;
                    const prevMsg = msgIdx > 0 ? taskViewMessages[msgIdx - 1] : null;
                    const afterUser = prevMsg?.role === "user" || prevMsg?.role === "internal";
                    return (
                      <div
                        key={m.id}
                        data-message-id={m.id}
                        className={cn(
                          "group relative mr-auto w-full max-w-[min(92%,48rem)] flex flex-col px-5 chat-font text-foreground",
                          afterUser ? "pt-0.5 pb-2" : "py-3",
                        )}
                      >
                        <TurnTimeline
                          segments={segmentsForMessage({
                            segments: (m as ChatMessage).segments,
                            reasoning: (m as ChatMessage).reasoning,
                            content: (m as ChatMessage).content,
                            steps: (m as ChatMessage).steps,
                            artifacts: (m as ChatMessage).artifacts?.map((a) => {
                              if (isLiveArtifact(a as ChatMessageArtifact)) {
                                const live = a as LiveArtifactMessage;
                                return {
                                  id: live.id,
                                  title: live.title,
                                  artType: live.artType,
                                  buffer: live.buffer,
                                  storage_key: live.savedPath,
                                };
                              }
                              const hist = a as ChatHistoryArtifact;
                              return {
                                id: hist.id,
                                title: hist.original_name || hist.id,
                                artType: hist.mime || "text",
                                buffer: `[File: ${hist.original_name || hist.id}]`,
                                storage_key: hist.storage_key,
                              };
                            }),
                          })}
                          toolsView={toolsView}
                          conversationId={conversationId}
                          token={token}
                          isPlanArtifact={isPlanArtifact}
                          renderMarkdownLink={renderMarkdownLink}
                          formatTextWithCitations={formatTextWithCitations}
                        />
                      </div>
                    );
                  }}
                />
              ) : null}
              {chatView.kind === "main" && planExecutionProgress ? (
                <PlanExecutionChatBanner
                  progress={planExecutionProgress}
                  onOpenTask={openPlanTaskView}
                  onOpenAllTasks={() => setDockTab("plan")}
                />
              ) : null}
              {chatView.kind === "main" && !showEmptyState
                ? mainFeedMessages.map((m, msgIdx) => {
                  const isLastUser = m.role === "user" && m.id === lastUserMessageId;
                  const prevMsg = msgIdx > 0 ? mainFeedMessages[msgIdx - 1] : null;
                  const afterUser = m.role === "assistant" && prevMsg?.role === "user";
                  const turnGapClass =
                    msgIdx === 0
                      ? ""
                      : afterUser
                        ? "mt-0.5"
                        : prevMsg?.role === "assistant" && m.role === "user"
                          ? "mt-6"
                          : "mt-4";
                  return (
                    <div
                      key={m.id}
                      data-message-id={m.id}
                      className={cn(
                        "group relative w-full flex flex-col transition-opacity",
                        turnGapClass,
                      )}
                    >
                      <div
                        className={cn(
                          "w-full px-5 chat-font",
                          m.role === "user"
                            ? cn(
                              "ml-auto max-w-[min(92%,42rem)] sm:max-w-[min(70%,42rem)] rounded-3xl text-foreground [&_a]:text-foreground [&_code]:bg-background [&_code]:text-foreground",
                              editingMessageId === m.id
                                ? "bg-transparent p-0"
                                : "border border-border/40 bg-muted/45 py-3 px-4",
                            )
                            : cn(
                              "mr-auto max-w-[min(92%,48rem)] bg-transparent text-foreground",
                              afterUser ? "pt-0.5 pb-2" : "py-3",
                            ),
                        )}
                      >
                        {m.role === "internal" ? (
                          <>
                            <div className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                              {t("chat.plan.execution")}
                            </div>
                            {m.content?.trim() ? (
                              <div className="prose-chat text-muted-foreground">
                                <InternalMessageMarkdown
                                  content={m.content.trim()}
                                  streaming={streaming}
                                  renderMarkdownLink={renderMarkdownLink}
                                  formatTextWithCitations={formatTextWithCitations}
                                />
                              </div>
                            ) : null}
                          </>
                        ) : null}
                        {m.role === "assistant" && m.content && isMemorizationMessage(m.content) ? (
                          <div className="chat-font flex items-start gap-2.5 rounded-2xl border border-border/40 bg-muted/25 px-4 py-3 text-muted-foreground max-w-[min(92%,42rem)] my-1 shadow-sm mr-auto">
                            <Brain size={16} className="mt-0.5 shrink-0 text-primary" aria-hidden />
                            <div className="flex-1">
                              <InternalMessageMarkdown
                                content={m.content.trim()}
                                streaming={streaming}
                                renderMarkdownLink={renderMarkdownLink}
                                formatTextWithCitations={formatTextWithCitations}
                              />
                            </div>
                          </div>
                        ) : m.role === "assistant" &&
                          (m.reasoning || (m.steps && m.steps.length > 0) || (m.artifacts && m.artifacts.length > 0) || m.content) ? (
                          <div className={cn(afterUser ? "mb-2" : "mb-3")}>
                            <TurnTimeline
                              segments={segmentsForMessage({
                                segments: m.segments,
                                reasoning: m.reasoning,
                                content: m.content,
                                steps: m.steps,
                                artifacts: m.artifacts?.map((a) => {
                                  if (isLiveArtifact(a)) {
                                    return {
                                      id: a.id,
                                      title: a.title,
                                      artType: a.artType,
                                      buffer: a.buffer,
                                      storage_key: a.savedPath,
                                    };
                                  }
                                  return {
                                    id: a.id,
                                    title: a.original_name || a.id,
                                    artType: a.mime || "text",
                                    buffer: `[File: ${a.original_name || a.id}]`,
                                    storage_key: a.storage_key,
                                  };
                                }),
                              })}
                              toolsView={toolsView}
                              conversationId={conversationId}
                              token={token}
                              isPlanArtifact={isPlanArtifact}
                              renderMarkdownLink={renderMarkdownLink}
                              formatTextWithCitations={formatTextWithCitations}
                              messageId={m.id}
                            />
                          </div>
                        ) : null}

                        {m.role === "user" && m.artifacts && m.artifacts.length > 0 && (
                          <div className="mb-3 flex flex-wrap gap-2">
                            {m.artifacts.map((a) => {
                              const storageKey = "storage_key" in a ? a.storage_key : a.savedPath || "";
                              const title = "original_name" in a ? a.original_name : a.title || storageKey;
                              const mime = "mime" in a ? a.mime : a.artType;
                              const downloadUrl = storageKey ? sessionDownloadUrl(conversationId, storageKey, token) : undefined;
                              return (
                                <a
                                  key={a.id}
                                  href={downloadUrl}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className="inline-flex items-center gap-2 rounded-xl bg-background/40 hover:bg-background/60 px-3 py-1.5 text-xs text-foreground/90 transition-colors border border-border/40 shadow-sm"
                                >
                                  <Paperclip size={13} className="text-muted-foreground" />
                                  <span className="font-medium truncate max-w-[200px]">{title}</span>
                                  {mime && (
                                    <span className="text-[10px] text-muted-foreground uppercase px-1.5 py-0.5 bg-muted/50 rounded">
                                      {mime.split("/")[1] || mime}
                                    </span>
                                  )}
                                </a>
                              );
                            })}
                          </div>
                        )}

                        {m.role === "user" && editingMessageId === m.id ? (
                          <div className="flex flex-col gap-3">
                            <div className="relative flex flex-col rounded-[24px] border border-border/50 bg-card/60 p-2 shadow-sm backdrop-blur-xl focus-within:ring-1 focus-within:ring-border/80 hover:border-border/80 transition-colors">
                              <textarea
                                value={editInput}
                                onChange={(e) => setEditInput(e.target.value)}
                                onKeyDown={(e) => {
                                  if (e.key === "Enter" && !e.shiftKey) {
                                    e.preventDefault();
                                    void handleSaveEdit(m.id);
                                  }
                                }}
                                placeholder={t("chat.edit.placeholder")}
                                className="focus-ring chat-font min-h-[80px] flex-1 w-full resize-none rounded-[20px] border-0 bg-transparent px-4 py-3 text-foreground placeholder:text-muted-foreground focus-visible:ring-0"
                              />
                            </div>
                            <div className="flex justify-end gap-2 text-xs">
                              <button
                                type="button"
                                onClick={() => setEditingMessageId(null)}
                                className="rounded-lg border border-border/60 bg-muted/10 px-3 py-1.5 text-muted-foreground hover:bg-muted/40 hover:text-foreground transition-all duration-200"
                              >
                                {t("btn.cancel")}
                              </button>
                              <button
                                type="button"
                                disabled={!editInput.trim() || streaming}
                                onClick={() => handleSaveEdit(m.id)}
                                className="rounded-lg bg-primary px-3 py-1.5 text-primary-foreground hover:bg-primary/90 transition-all duration-200 disabled:opacity-50"
                              >
                                {t("chat.edit.save_send")}
                              </button>
                            </div>
                          </div>
                        ) : m.role === "user" ? (
                          <div className="prose-chat">
                            <UserMessageMarkdown
                              content={m.content.trim()}
                              renderMarkdownLink={renderMarkdownLink}
                              formatTextWithCitations={formatTextWithCitations}
                            />
                          </div>
                        ) : null}
                        {m.role === "assistant" && m.webSources && m.webSources.length > 0 ? (
                          <WebSourcesBar cards={m.webSources} messageId={m.id} />
                        ) : null}
                        {m.role === "assistant" && m.reasoningUnavailable ? (
                          <p className="mt-2 border-t border-border pt-2 text-[11px] leading-snug text-muted-foreground">
                            {t("chat.edit.no_reasoning", { level: "min" })}
                          </p>
                        ) : null}
                      </div>

                      {m.role === "user" && !streaming && editingMessageId !== m.id ? (
                        <div className="mt-1 flex justify-end gap-1 pr-2">
                          {isLastUser ? (
                            <button
                              type="button"
                              onClick={() => handleStartEdit(m)}
                              className="inline-flex items-center gap-1 rounded-lg p-1.5 text-xs text-muted-foreground opacity-100 transition-opacity hover:bg-foreground/5 hover:text-foreground lg:opacity-0 lg:group-hover:opacity-100"
                              title={t("chat.edit.tooltip")}
                            >
                              <Pencil size={14} aria-hidden />
                            </button>
                          ) : null}
                          <MessageActions
                            messageId={m.id}
                            copyText={m.content}
                            className="pr-1"
                          />
                        </div>
                      ) : null}

                      {m.role === "assistant" && !streaming && !isMemorizationMessage(m.content) ? (
                        <div className="mt-0.5 flex flex-col items-start justify-start pl-1 w-full">
                          <MessageActions
                            messageId={m.id}
                            copyText={extractAssistantCopyText(m)}
                            rating={messageRatings[m.id] ?? null}
                            onRate={handleMessageRate}
                            onRegenerate={handleRegenerate}
                            showRegenerate={
                              m.id === lastAssistantMessageId &&
                              messages[messages.length - 1]?.id === m.id
                            }
                            pinned={
                              m.id === lastAssistantMessageId &&
                              messages[messages.length - 1]?.id === m.id
                            }
                            onMemorize={() => handleMemorize(m.id)}
                          />
                          {activeCommentBoxId === m.id && (
                            <div className="mt-3 w-full max-w-xl p-4 sm:p-5 rounded-2xl bg-card border border-rose-500/30 shadow-[0_0_20px_rgba(244,63,94,0.08)] flex flex-col gap-4 relative">
                              {/* Header */}
                              <div className="flex items-center justify-between shrink-0">
                                <div className="flex items-center gap-2 font-bold text-xs text-rose-400">
                                  <ThumbsDown className="w-4 h-4 text-rose-500 fill-current" />
                                  {t("chat.actions.feedback_title")}
                                </div>
                                <button
                                  onClick={() => setActiveCommentBoxId(null)}
                                  className="p-1 text-muted-foreground hover:text-foreground hover:bg-foreground/5 rounded-lg transition-colors cursor-pointer"
                                >
                                  <X className="w-4 h-4" />
                                </button>
                              </div>

                              {/* Textarea Wrapper */}
                              <div className="relative w-full">
                                <textarea
                                  id={`feedback-textarea-${m.id}`}
                                  placeholder={t("chat.actions.feedback_placeholder")}
                                  className="w-full min-h-[85px] text-xs bg-black/40 border border-white/10 hover:border-white/20 focus:border-rose-500 rounded-xl p-3 pr-8 text-foreground focus:outline-none focus:ring-1 focus:ring-rose-500/30 resize-none transition-all placeholder:text-muted-foreground/75"
                                  defaultValue={m.feedbackComment ?? ""}
                                  onKeyDown={(e) => {
                                    if (e.key === "Enter" && !e.shiftKey) {
                                      e.preventDefault();
                                      const text = (e.target as HTMLTextAreaElement).value;
                                      handleMessageComment(m.id, text);
                                      setActiveCommentBoxId(null);
                                    }
                                  }}
                                />
                              </div>

                              {/* Footer Actions */}
                              <div className="flex items-center justify-end gap-2 shrink-0">
                                <button
                                  onClick={() => {
                                    handleMessageRate(m.id, null);
                                    setActiveCommentBoxId(null);
                                  }}
                                  className="px-4 py-1.5 text-xs font-semibold rounded-full border border-white/10 bg-white/5 hover:bg-white/10 text-gray-300 transition-all cursor-pointer"
                                >
                                  {t("chat.actions.feedback_cancel")}
                                </button>
                                <button
                                  onClick={() => {
                                    const el = document.getElementById(`feedback-textarea-${m.id}`) as HTMLTextAreaElement;
                                    if (el) {
                                      handleMessageComment(m.id, el.value);
                                    }
                                    setActiveCommentBoxId(null);
                                  }}
                                  className="px-5 py-1.5 text-xs font-bold rounded-full bg-rose-500 hover:bg-rose-600 text-white transition-all shadow-md shadow-rose-500/20 cursor-pointer"
                                >
                                  {t("chat.actions.feedback_submit")}
                                </button>
                              </div>
                            </div>
                          )}
                        </div>
                      ) : null}

                      {memorizingMessageId === m.id && streaming ? (
                        <div className="chat-font flex items-start gap-2.5 rounded-2xl border border-border/40 bg-muted/25 px-4 py-3 text-muted-foreground max-w-[min(92%,42rem)] my-1 shadow-sm mr-auto mt-2">
                          <Loader2 className="h-4 w-4 shrink-0 animate-spin text-primary mt-0.5" />
                          <div className="flex-1">
                            <div className="font-semibold">{t("chat.agent_status.saving_info")}</div>
                            <div className="text-xs text-muted-foreground">{t("chat.agent_status.saving_info_desc")}</div>
                          </div>
                        </div>
                      ) : null}

                      {(() => {
                        const memorizationMsgs = messages.filter(
                          (msg) => msg.metadata?.memorized_message_id === m.id
                        );
                        if (memorizationMsgs.length === 0) return null;
                        return memorizationMsgs.map((mm) => (
                          <div key={mm.id} className="chat-font flex items-start gap-2.5 rounded-2xl border border-border/40 bg-muted/25 px-4 py-3 text-muted-foreground max-w-[min(92%,42rem)] my-1 shadow-sm mr-auto mt-2">
                            <Brain size={16} className="mt-0.5 shrink-0 text-primary" aria-hidden />
                            <div className="flex-1">
                              <InternalMessageMarkdown
                                content={mm.content.trim()}
                                streaming={streaming}
                                renderMarkdownLink={renderMarkdownLink}
                                formatTextWithCitations={formatTextWithCitations}
                              />
                            </div>
                          </div>
                        ));
                      })()}
                    </div>
                  );
                })
                : null}
              {chatView.kind === "main" && streamRecovery ? (
                <div
                  className="mx-auto mb-3 flex max-w-3xl items-center gap-2 rounded-xl border border-border/60 bg-muted/30 px-4 py-2.5 text-sm"
                  role="status"
                  aria-live="polite"
                >
                  <Loader2 className="h-4 w-4 shrink-0 animate-spin text-muted-foreground" />
                  <AgentWorkingShimmer label={t("chat.stream_recovery")} />
                </div>
              ) : null}
              {showMainTurnVisual && turnVisual ? (
                <div className="mr-auto mt-0.5 w-full max-w-4xl min-h-[3.5rem] bg-transparent px-5 pt-0 pb-3 chat-font text-foreground">
                  {isSavingInfo ? (
                    <StatusProgressCard
                      className="mb-3"
                      icon={Database}
                      title={t("chat.agent_status.saving_info")}
                      subtitle={t("chat.agent_status.saving_info_desc")}
                    />
                  ) : showContextCompactingShimmer ? (
                    <StatusProgressCard
                      className="mb-3"
                      icon={Database}
                      title={t("chat.agent_status.compacting")}
                      subtitle={t("chat.agent_status.compacting_desc")}
                    />
                  ) : showAgentWorkingShimmer ? (
                    <AgentWorkingShimmer label={agentWorkingLabel} />
                  ) : null}

                  {!isSavingInfo && (
                    <TurnTimeline
                      key={streamEpoch}
                      segments={turnVisual.segments}
                      toolsView={toolsView}
                      streaming={streaming}
                      conversationId={conversationId}
                      token={token}
                      isPlanArtifact={isPlanArtifact}
                      renderMarkdownLink={renderMarkdownLink}
                      formatTextWithCitations={formatTextWithCitations}
                      messageId={activeMessageId || undefined}
                    />
                  )}

                  {streaming && !isSavingInfo && turnVisual.webSourceCards.length > 0 ? (
                    <WebSourcesBar cards={turnVisual.webSourceCards} messageId={activeMessageId || undefined} />
                  ) : null}
                </div>
              ) : null}
              {(postTurnCharts.length > 0 || postTurnFiles.length > 0) && (
                <div className="mr-auto mt-2 w-full max-w-4xl rounded-2xl border border-border bg-card/40 px-5 py-4 shadow-sm">
                  <SessionCharts charts={postTurnCharts} />
                  {postTurnFiles.length > 0 && (
                    <div className="mt-3 text-xs">
                      <div className="mb-1 font-medium text-muted-foreground">{t("chat.session_files_new")}</div>
                      <ul className="list-inside list-disc space-y-1">
                        {postTurnFiles.map((f) => (
                          <li key={f.rp}>
                            <a
                              className="focus-ring rounded text-primary underline-offset-2 hover:underline"
                              href={sessionDownloadUrl(conversationId, f.rp, token)}
                            >
                              {f.label}
                            </a>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>

          <div className="relative z-20 min-w-0 shrink-0 bg-transparent p-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] sm:p-4 sm:pb-6 backdrop-blur-none">
            <div className="mx-auto w-full min-w-0 max-w-3xl">
              {pendingFiles.length > 0 && (
                <div className="mb-3 flex flex-wrap gap-2">
                  {pendingFiles.map((f) => (
                    <span
                      key={f.name}
                      className="inline-flex items-center gap-1.5 rounded-full border border-border bg-muted/60 px-3 py-1.5 text-[12px] font-medium text-foreground backdrop-blur-sm"
                    >
                      {f.name}
                      <button
                        type="button"
                        className="focus-ring rounded-full px-0.5 text-muted-foreground hover:text-destructive transition-colors"
                        aria-label={t("chat.remove_file", { name: f.name })}
                        onClick={() => setPendingFiles((prev) => prev.filter((x) => x.name !== f.name))}
                      >
                        ×
                      </button>
                    </span>
                  ))}
                </div>
              )}
              {isProjectRequiredButMissing && (
                <div className="mb-3 rounded-xl border border-amber-500/30 bg-amber-500/10 p-3.5 text-xs text-amber-800 dark:text-amber-200 shadow-sm flex flex-col sm:flex-row sm:items-center justify-between gap-3 animate-in fade-in slide-in-from-bottom-2 duration-200">
                  <div className="flex-1 leading-relaxed">
                    <span className="font-semibold block mb-0.5 text-amber-900 dark:text-amber-300 text-sm">{t("chat.project_required.title")}</span>
                    {t("chat.project_required.desc")}
                  </div>
                  <button
                    type="button"
                    onClick={() => setProjectCreateOpen(true)}
                    className="shrink-0 self-start sm:self-center inline-flex items-center justify-center rounded-lg bg-amber-600 hover:bg-amber-500 active:bg-amber-700 px-3.5 py-1.5 font-semibold text-white dark:text-black dark:bg-amber-400 dark:hover:bg-amber-300 transition-colors"
                  >
                    {t("chat.project_required.button")}
                  </button>
                </div>
              )}
              <div
                ref={composerContainerRef}
                className={cn(
                  "relative flex min-w-0 flex-col overflow-visible rounded-[26px] border bg-card/45 p-2.5 shadow-md backdrop-blur-xl focus-within:ring-1",
                  agentMode === "plan"
                    ? "border-orange-500/35 shadow-[0_0_12px_rgba(249,115,22,0.08)] focus-within:ring-orange-500/30"
                    : agentMode === "deep_research"
                      ? "border-violet-500/35 shadow-[0_0_12px_rgba(139,92,246,0.08)] focus-within:ring-violet-500/30"
                      : "border-border hover:border-border/80 focus-within:ring-primary/30",
                  composerResizing ? "" : "transition-colors"
                )}
                style={{ minHeight: COMPOSER_MIN_HEIGHT }}
              >
                <button
                  type="button"
                  aria-label={t("chat.resize_composer")}
                  onMouseDown={startComposerResize}
                  className="focus-ring absolute left-0 top-0 z-10 h-4 w-full -translate-y-1/2 cursor-ns-resize bg-transparent"
                />
                {(webRestrictHosts.length > 0 || !webSearchEnabled) && (
                  <div className="flex flex-wrap gap-2 px-3 pt-1 text-[11px] text-muted-foreground" aria-live="polite">
                    {!webSearchEnabled ? (
                      <span className="rounded-full border border-amber-500/40 bg-amber-500/15 dark:bg-amber-500/10 px-2 py-0.5 font-medium text-amber-700 dark:text-amber-200">
                        {t("chat.web_search.disabled")}
                      </span>
                    ) : null}
                    {webRestrictHosts.length > 0 ? (
                      <span className="rounded-full border border-cyan-500/35 bg-cyan-500/15 dark:bg-cyan-500/10 px-2 py-0.5 font-medium text-cyan-700 dark:text-cyan-200">
                        {t("chat.web_search.restricted", { count: webRestrictHosts.length })}
                      </span>
                    ) : null}
                  </div>
                )}
                <div className="min-h-0 shrink-0">
                  <textarea
                    ref={composerTextareaRef}
                    value={input}
                    disabled={streaming || isProjectRequiredButMissing}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Tab" && e.shiftKey) {
                        e.preventDefault();
                        handleAgentModeChange(agentMode === "plan" ? "normal" : "plan");
                      } else if (e.key === "Enter" && !e.shiftKey) {
                        e.preventDefault();
                        void send();
                      }
                    }}
                    placeholder={isProjectRequiredButMissing ? t("chat.project_required.textarea_placeholder") : t("chat.composer_placeholder")}
                    className="focus-ring chat-font box-border min-h-[48px] min-w-0 max-w-full w-full resize-none overflow-x-hidden break-words rounded-[20px] border-0 bg-transparent px-4 py-2.5 text-foreground [overflow-wrap:anywhere] placeholder:text-muted-foreground/75 focus-visible:ring-0"
                    rows={1}
                  />
                </div>
                <div className="mt-1 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1.5 px-2 pb-1">
                  <input
                    ref={fileInputRef}
                    type="file"
                    multiple
                    className="hidden"
                    onChange={(e) => {
                      const selected = Array.from(e.target.files || []);
                      setPendingFiles((prev) => {
                        const filtered = selected.filter(
                          (sf) => !prev.some((pf) => pf.name === sf.name && pf.size === sf.size)
                        );
                        return [...prev, ...filtered];
                      });
                      e.target.value = "";
                    }}
                  />
                  {/* Pulsante "+" con Menu di Allega File */}
                  <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2">
                    <div ref={plusMenuRef} className="relative">
                      <button
                        type="button"
                        onClick={() => {
                          setIsPlusOpen((prev) => !prev);
                          closePlusSubMenus();
                          setIsProfileOpen(false);
                          setIsAgentModeOpen(false);
                        }}
                        className={cn(
                          "focus-ring inline-flex size-7 items-center justify-center rounded-full border transition-all duration-200 active:scale-95",
                          isPlusOpen || !webSearchEnabled || thinkingEnabled
                            ? "border-primary bg-primary/10 text-primary"
                            : "border-border bg-muted/40 text-muted-foreground hover:bg-muted/60 hover:text-foreground"
                        )}
                        title={t("chat.tools.plus_tooltip")}
                      >
                        <span
                          className={cn(
                            "flex items-center justify-center transition-transform duration-200",
                          )}
                        >
                          {
                            isPlusOpen ? <X size={14} aria-hidden /> : <Plus size={14} aria-hidden />
                          }
                        </span>
                      </button>

                      {isPlusOpen && (
                        <div className="absolute bottom-full left-0 z-50 mb-2 min-w-[15rem] max-w-[min(100vw-2rem,18rem)] rounded-xl border border-border bg-popover p-1.5 text-popover-foreground shadow-lg backdrop-blur-md animate-in fade-in-0 slide-in-from-bottom-2 duration-150">
                          {/* Opzione: Allega File */}
                          <button
                            type="button"
                            onClick={() => {
                              fileInputRef.current?.click();
                              setIsPlusOpen(false);
                              closePlusSubMenus();
                            }}
                            onMouseEnter={() => {
                              closePlusSubMenus();
                            }}
                            className="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-xs font-medium text-muted-foreground hover:bg-muted/60 hover:text-foreground transition-colors text-left"
                          >
                            <Paperclip size={12} className="shrink-0" aria-hidden />
                            <span>{t("chat.tools.attach_file")}</span>
                          </button>

                          {/* Opzione: Vista Tools > */}
                          <div className="relative" onMouseLeave={() => setIsToolsViewSubOpen(false)}>
                            <button
                              type="button"
                              onClick={() => {
                                setIsToolsViewSubOpen((prev) => !prev);
                                setIsWebSearchSubOpen(false);
                                setIsThinkingSubOpen(false);
                              }}
                              onMouseEnter={() => {
                                setIsToolsViewSubOpen(true);
                                setIsWebSearchSubOpen(false);
                                setIsThinkingSubOpen(false);
                              }}
                              className={cn(
                                "flex w-full items-center justify-between rounded-lg px-2.5 py-1.5 text-xs font-medium transition-colors text-left",
                                isToolsViewSubOpen
                                  ? "bg-muted/60 text-foreground"
                                  : "text-muted-foreground hover:bg-muted/60 hover:text-foreground"
                              )}
                            >
                              <div className="flex items-center gap-2">
                                <Wrench size={12} className="shrink-0" aria-hidden />
                                <span>{t("chat.tools.view_label")}</span>
                              </div>
                              <ChevronRight size={12} className="shrink-0" aria-hidden />
                            </button>

                            {/* Sottomenu Vista Tools */}
                            {isToolsViewSubOpen && (
                              <div className="absolute bottom-full left-0 z-50 pb-1.5 w-48 sm:bottom-0 sm:left-full sm:pb-0 sm:pl-1.5">
                                <div
                                  onMouseEnter={() => setIsToolsViewSubOpen(true)}
                                  className="w-full rounded-xl border border-border bg-card/95 p-1 shadow-lg backdrop-blur-md animate-in fade-in-0 slide-in-from-bottom-2 duration-150 sm:slide-in-from-left-2"
                                >
                                  <div className="px-2 py-1 text-[10px] font-semibold text-muted-foreground border-b border-border/45 mb-1">
                                    {t("chat.tools.select_view")}
                                  </div>
                                  <div className="space-y-0.5">
                                    {/* Opzione: Nascondi */}
                                    <button
                                      type="button"
                                      onClick={() => {
                                        handleToolsViewChange("hidden");
                                        setIsPlusOpen(false);
                                        closePlusSubMenus();
                                      }}
                                      className={cn(
                                        "flex w-full items-center justify-between rounded-lg px-2.5 py-1.5 text-xs font-medium transition-colors text-left",
                                        toolsView === "hidden"
                                          ? "bg-primary/10 text-primary"
                                          : "text-muted-foreground hover:bg-muted/60 hover:text-foreground"
                                      )}
                                    >
                                      <span>{t("chat.tools.hide")}</span>
                                      {toolsView === "hidden" && <Check size={12} className="shrink-0 text-primary" />}
                                    </button>

                                    {/* Opzione: Parziale */}
                                    <button
                                      type="button"
                                      onClick={() => {
                                        handleToolsViewChange("partial");
                                        setIsPlusOpen(false);
                                        closePlusSubMenus();
                                      }}
                                      className={cn(
                                        "flex w-full items-center justify-between rounded-lg px-2.5 py-1.5 text-xs font-medium transition-colors text-left",
                                        toolsView === "partial"
                                          ? "bg-primary/10 text-primary"
                                          : "text-muted-foreground hover:bg-muted/60 hover:text-foreground"
                                      )}
                                    >
                                      <span>{t("chat.tools.partial")}</span>
                                      {toolsView === "partial" && <Check size={12} className="shrink-0 text-primary" />}
                                    </button>

                                    {/* Opzione: Completa */}
                                    <button
                                      type="button"
                                      onClick={() => {
                                        handleToolsViewChange("full");
                                        setIsPlusOpen(false);
                                        closePlusSubMenus();
                                      }}
                                      className={cn(
                                        "flex w-full items-center justify-between rounded-lg px-2.5 py-1.5 text-xs font-medium transition-colors text-left",
                                        toolsView === "full"
                                          ? "bg-primary/10 text-primary"
                                          : "text-muted-foreground hover:bg-muted/60 hover:text-foreground"
                                      )}
                                    >
                                      <span>{t("chat.tools.full")}</span>
                                      {toolsView === "full" && <Check size={12} className="shrink-0 text-primary" />}
                                    </button>
                                  </div>
                                </div>
                              </div>
                            )}
                          </div>

                          {/* Opzione: Web search > */}
                          <div className="relative" onMouseLeave={() => setIsWebSearchSubOpen(false)}>
                            <button
                              type="button"
                              onClick={() => {
                                setIsWebSearchSubOpen((prev) => !prev);
                                setIsToolsViewSubOpen(false);
                                setIsThinkingSubOpen(false);
                              }}
                              onMouseEnter={() => {
                                setIsWebSearchSubOpen(true);
                                setIsToolsViewSubOpen(false);
                                setIsThinkingSubOpen(false);
                              }}
                              className={cn(
                                "flex w-full items-center justify-between rounded-lg px-2.5 py-1.5 text-xs font-medium transition-colors text-left",
                                isWebSearchSubOpen
                                  ? "bg-muted/60 text-foreground"
                                  : "text-muted-foreground hover:bg-muted/60 hover:text-foreground",
                              )}
                            >
                              <div className="flex min-w-0 items-center gap-2">
                                {webSearchEnabled ? (
                                  <Globe size={12} className="shrink-0" aria-hidden />
                                ) : (
                                  <GlobeLock size={12} className="shrink-0" aria-hidden />
                                )}
                                <span className="truncate">{t("chat.web_search.global")}</span>
                              </div>
                              <ChevronRight size={12} className="shrink-0" aria-hidden />
                            </button>

                            {isWebSearchSubOpen ? (
                              <div className="absolute bottom-full left-0 z-50 pb-1.5 w-44 sm:bottom-0 sm:left-full sm:pb-0 sm:pl-1.5">
                                <div
                                  onMouseEnter={() => setIsWebSearchSubOpen(true)}
                                  className="w-full rounded-xl border border-border bg-card/95 p-1 shadow-lg backdrop-blur-md animate-in fade-in-0 slide-in-from-bottom-2 duration-150 sm:slide-in-from-left-2"
                                >
                                  <div className="border-b border-border/45 px-2 py-1 text-[10px] font-semibold text-muted-foreground">
                                    {t("chat.web_search.global")}
                                  </div>
                                  <div className="space-y-0.5 p-0.5">
                                    <button
                                      type="button"
                                      onClick={() => {
                                        persistWebSearchEnabled(false);
                                        setIsPlusOpen(false);
                                        closePlusSubMenus();
                                      }}
                                      className={cn(
                                        "flex w-full items-center justify-between rounded-lg px-2.5 py-1.5 text-xs font-medium transition-colors text-left",
                                        !webSearchEnabled
                                          ? "bg-primary/10 text-primary"
                                          : "text-muted-foreground hover:bg-muted/60 hover:text-foreground",
                                      )}
                                    >
                                      <span>{t("chat.web_search.off_short")}</span>
                                      {!webSearchEnabled ? (
                                        <Check size={12} className="shrink-0 text-primary" />
                                      ) : null}
                                    </button>
                                    <button
                                      type="button"
                                      onClick={() => {
                                        persistWebSearchEnabled(true);
                                        setIsPlusOpen(false);
                                        closePlusSubMenus();
                                      }}
                                      className={cn(
                                        "flex w-full items-center justify-between rounded-lg px-2.5 py-1.5 text-xs font-medium transition-colors text-left",
                                        webSearchEnabled
                                          ? "bg-primary/10 text-primary"
                                          : "text-muted-foreground hover:bg-muted/60 hover:text-foreground",
                                      )}
                                    >
                                      <span>{t("chat.web_search.on_short")}</span>
                                      {webSearchEnabled ? (
                                        <Check size={12} className="shrink-0 text-primary" />
                                      ) : null}
                                    </button>
                                  </div>
                                </div>
                              </div>
                            ) : null}
                          </div>

                          {/* Opzione: Thinking > */}
                          <div className="relative" onMouseLeave={() => setIsThinkingSubOpen(false)}>
                            <button
                              type="button"
                              onClick={() => {
                                setIsThinkingSubOpen((prev) => !prev);
                                setIsToolsViewSubOpen(false);
                                setIsWebSearchSubOpen(false);
                              }}
                              onMouseEnter={() => {
                                setIsThinkingSubOpen(true);
                                setIsToolsViewSubOpen(false);
                                setIsWebSearchSubOpen(false);
                              }}
                              className={cn(
                                "flex w-full items-center justify-between rounded-lg px-2.5 py-1.5 text-xs font-medium transition-colors text-left",
                                isThinkingSubOpen || thinkingEnabled
                                  ? "bg-muted/60 text-foreground"
                                  : "text-muted-foreground hover:bg-muted/60 hover:text-foreground",
                              )}
                            >
                              <div className="flex min-w-0 items-center gap-2">
                                <Sparkles size={12} className="shrink-0" aria-hidden />
                                <span className="truncate">{t("chat.thinking.label")}</span>
                              </div>
                              <ChevronRight size={12} className="shrink-0" aria-hidden />
                            </button>

                            {isThinkingSubOpen ? (
                              <div className="absolute bottom-full left-0 z-50 pb-1.5 w-44 sm:bottom-0 sm:left-full sm:pb-0 sm:pl-1.5">
                                <div
                                  onMouseEnter={() => setIsThinkingSubOpen(true)}
                                  className="w-full rounded-xl border border-border bg-card/95 p-1 shadow-lg backdrop-blur-md animate-in fade-in-0 slide-in-from-bottom-2 duration-150 sm:slide-in-from-left-2"
                                >
                                  <div className="border-b border-border/45 px-2 py-1 text-[10px] font-semibold text-muted-foreground">
                                    {t("chat.thinking.label")}
                                  </div>
                                  <div className="space-y-0.5 p-0.5">
                                    <button
                                      type="button"
                                      onClick={() => {
                                        handleToggleThinking(false);
                                        setIsPlusOpen(false);
                                        closePlusSubMenus();
                                      }}
                                      className={cn(
                                        "flex w-full items-center justify-between rounded-lg px-2.5 py-1.5 text-xs font-medium transition-colors text-left",
                                        !thinkingEnabled
                                          ? "bg-primary/10 text-primary"
                                          : "text-muted-foreground hover:bg-muted/60 hover:text-foreground",
                                      )}
                                    >
                                      <span>{t("chat.thinking.disable")}</span>
                                      {!thinkingEnabled ? (
                                        <Check size={12} className="shrink-0 text-primary" />
                                      ) : null}
                                    </button>
                                    <button
                                      type="button"
                                      onClick={() => {
                                        handleToggleThinking(true);
                                        handleReasoningEffortChange("min");
                                        setIsPlusOpen(false);
                                        closePlusSubMenus();
                                      }}
                                      className={cn(
                                        "flex w-full items-center justify-between rounded-lg px-2.5 py-1.5 text-xs font-medium transition-colors text-left",
                                        thinkingEnabled && reasoningEffort === "min"
                                          ? "bg-primary/10 text-primary"
                                          : "text-muted-foreground hover:bg-muted/60 hover:text-foreground",
                                      )}
                                    >
                                      <span>{t("chat.thinking.min")}</span>
                                      {thinkingEnabled && reasoningEffort === "min" ? (
                                        <Check size={12} className="shrink-0 text-primary" />
                                      ) : null}
                                    </button>
                                    <button
                                      type="button"
                                      onClick={() => {
                                        handleToggleThinking(true);
                                        handleReasoningEffortChange("medium");
                                        setIsPlusOpen(false);
                                        closePlusSubMenus();
                                      }}
                                      className={cn(
                                        "flex w-full items-center justify-between rounded-lg px-2.5 py-1.5 text-xs font-medium transition-colors text-left",
                                        thinkingEnabled && reasoningEffort === "medium"
                                          ? "bg-primary/10 text-primary"
                                          : "text-muted-foreground hover:bg-muted/60 hover:text-foreground",
                                      )}
                                    >
                                      <span>{t("chat.thinking.med")}</span>
                                      {thinkingEnabled && reasoningEffort === "medium" ? (
                                        <Check size={12} className="shrink-0 text-primary" />
                                      ) : null}
                                    </button>
                                    <button
                                      type="button"
                                      onClick={() => {
                                        handleToggleThinking(true);
                                        handleReasoningEffortChange("max");
                                        setIsPlusOpen(false);
                                        closePlusSubMenus();
                                      }}
                                      className={cn(
                                        "flex w-full items-center justify-between rounded-lg px-2.5 py-1.5 text-xs font-medium transition-colors text-left",
                                        thinkingEnabled && reasoningEffort === "max"
                                          ? "bg-primary/10 text-primary"
                                          : "text-muted-foreground hover:bg-muted/60 hover:text-foreground",
                                      )}
                                    >
                                      <span>{t("chat.thinking.max")}</span>
                                      {thinkingEnabled && reasoningEffort === "max" ? (
                                        <Check size={12} className="shrink-0 text-primary" />
                                      ) : null}
                                    </button>
                                  </div>
                                </div>
                              </div>
                            ) : null}
                          </div>

                          <div className="my-1 border-t border-border/45" />
                          <button
                            type="button"
                            className="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-xs font-medium text-muted-foreground hover:bg-primary/5 hover:text-primary transition-colors text-left border border-transparent hover:border-primary/20"
                            onClick={() => {
                              setWebRestrictDraft([...webRestrictHosts]);
                              setWebRestrictInput("");
                              setWebRestrictInputError(null);
                              setWebRestrictModalOpen(true);
                              setIsPlusOpen(false);
                              closePlusSubMenus();
                            }}
                          >
                            <Settings size={12} className="shrink-0" aria-hidden />
                            <span className="truncate">{t("chat.web_search.advanced")}</span>
                          </button>
                        </div>
                      )}
                    </div>

                    {/* Pulsante Profilo con Dropdown Opzioni */}
                    <div ref={profileMenuRef} className="relative">
                      <button
                        type="button"
                        onClick={() => {
                          setIsProfileOpen((prev) => !prev);
                          setIsPlusOpen(false);
                          closePlusSubMenus();
                          setIsAgentModeOpen(false);
                        }}
                        className={cn(
                          "focus-ring inline-flex h-8 max-w-full items-center gap-1.5 rounded-full border px-3 text-[11px] font-semibold transition-all duration-200 hover:scale-[1.01] active:scale-[0.99]",
                          isProfileOpen
                            ? "border-primary/45 bg-primary/10 text-primary"
                            : "border-border/80 bg-muted/20 text-muted-foreground hover:bg-muted/40 hover:text-foreground"
                        )}
                      >
                        <User size={12} className="shrink-0" aria-hidden />
                        <span className="max-w-[6.5rem] truncate sm:max-w-[9rem]">
                          {activeProfileName || t("chat.profile.label")}
                        </span>
                        <ChevronDown size={10} className="opacity-70" aria-hidden />
                      </button>

                      {isProfileOpen && (
                        <div className="absolute bottom-full left-0 mb-2 z-50 w-[min(100vw-2rem,17rem)] rounded-xl border border-border bg-card/95 p-1 shadow-lg backdrop-blur-md animate-in fade-in-0 slide-in-from-bottom-2 duration-150">
                          <div className="border-b border-border/45 px-2.5 py-1.5 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
                            {t("chat.profile.select")}
                          </div>
                          <p className="px-2.5 py-1 text-[10px] leading-snug text-muted-foreground">
                            {t("chat.profile.active_hint")}
                          </p>
                          <div className="max-h-52 overflow-y-auto p-0.5">
                            {profiles.map((p) => {
                              const slug = p.slug || p.name.replace(/\s+/g, "_").toLowerCase();
                              const isSelected = p.slug === profile || p.name === profile;
                              return (
                                <ComposerOptionRow
                                  key={p.name}
                                  label={p.name}
                                  description={p.description}
                                  selected={isSelected}
                                  onClick={() => {
                                    handleProfileChange(slug);
                                    setIsProfileOpen(false);
                                  }}
                                />
                              );
                            })}
                            {profiles.length === 0 ? (
                              <div className="px-2.5 py-2 text-xs italic text-muted-foreground">
                                {t("chat.profile.none")}
                              </div>
                            ) : null}
                          </div>
                          <div className="border-t border-border/45 p-1">
                            <Link
                              href="/settings?tab=user-md"
                              className="focus-ring flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-xs font-medium text-muted-foreground transition hover:bg-muted/55 hover:text-foreground"
                              onClick={() => setIsProfileOpen(false)}
                            >
                              <Settings size={12} className="shrink-0" aria-hidden />
                              <span>{t("chat.profile.customize")}</span>
                            </Link>
                          </div>
                        </div>
                      )}
                    </div>


                    {showProjectMemory && (
                      <ProjectMemoryChip
                        userId={userId}
                        token={token}
                        profileSlug={activeProfileSlug}
                        projectSlug={sqlQueryProject}
                        onOpenPanel={() => setDockTab("memory")}
                      />
                    )}

                    <AgentModeSelectChip
                      mode={agentMode}
                      onChange={handleAgentModeChange}
                      open={isAgentModeOpen}
                      onOpenChange={(open) => {
                        setIsAgentModeOpen(open);
                        if (open) {
                          setIsPlusOpen(false);
                          closePlusSubMenus();
                          setIsProfileOpen(false);
                        }
                      }}
                      onAfterSelect={(mode) => {
                        if (mode === "deep_research") setDockTab("research");
                      }}
                    />
                  </div>

                  {/* Altri controlli a destra */}
                  <div className="ml-auto flex shrink-0 items-center gap-2">
                    {mcpAlertCount > 0 && (
                      <button
                        type="button"
                        onClick={() => setMcpPendingOpen(true)}
                        className={cn(
                          "focus-ring flex items-center gap-1 rounded-full border px-2.5 py-1 text-[11px] font-medium",
                          mcpRuntimeErrors.length > 0
                            ? "border-red-500/50 bg-red-500/15 text-red-800 dark:text-red-200"
                            : "border-amber-500/50 bg-amber-500/15 text-amber-800 dark:text-amber-200"
                        )}
                        title={t("integrationsPage.composer_pending")}
                      >
                        <AlertTriangle size={14} aria-hidden className="text-red-800" />
                        <span className={mcpRuntimeErrors.length > 0 ? "text-red-800" : "text-amber-800"}>
                          {mcpAlertCount}
                        </span>
                      </button>
                    )}
                    {streaming ? (
                      <button
                        type="button"
                        onClick={stop}
                        className="focus-ring inline-flex size-8 items-center justify-center rounded-full bg-destructive/20 text-destructive transition-colors hover:bg-destructive/30"
                      >
                        <Square size={12} aria-hidden fill="currentColor" />
                      </button>
                    ) : (
                      <button
                        type="button"
                        onClick={() => void send()}
                        disabled={!input.trim() || isProjectRequiredButMissing}
                        className="focus-ring inline-flex size-8 items-center justify-center rounded-full bg-primary text-primary-foreground transition-all duration-200 hover:scale-105 hover:bg-primary/95 disabled:pointer-events-none disabled:opacity-30"
                      >
                        <Send size={13} aria-hidden />
                      </button>
                    )}
                  </div>
                </div>
              </div>
              <div className="mt-3 text-center text-[12px] font-medium text-muted-foreground">
                {t("chat.footer_hint")}
              </div>
            </div>
          </div>
        </div>
      </ChatDragDrop>
      <ProjectCreateModal
        open={projectCreateOpen}
        onClose={() => setProjectCreateOpen(false)}
        userId={userId}
        token={token}
        profileSlug={activeProfileSlug}
        onCreated={(slug) => {
          setProjectCreateOpen(false);
          handleProjectChange(slug);
        }}
      />
      {projectWarningModalOpen ? (
        <div
          className="fixed inset-0 z-[200] flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm transition-all"
          role="presentation"
          onClick={() => setProjectWarningModalOpen(false)}
        >
          <div
            className="w-full max-w-md rounded-2xl border border-border bg-background p-6 shadow-xl"
            role="dialog"
            aria-modal="true"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start gap-3">
              <div className="rounded-full bg-warning/10 p-2 text-warning">
                <AlertTriangle className="size-6 text-amber-500" />
              </div>
              <div className="flex-1">
                <h3 className="text-lg font-semibold text-foreground">
                  {t("chat.project_warning.title")}
                </h3>
                <p className="mt-2 text-sm text-muted-foreground leading-relaxed">
                  {t("chat.project_warning.desc")}
                </p>
                <div className="mt-4 flex justify-end gap-2">
                  <button
                    type="button"
                    onClick={() => setProjectWarningModalOpen(false)}
                    className="rounded-lg border border-border/60 bg-muted/10 px-3 py-1.5 text-xs text-muted-foreground hover:bg-muted/40 hover:text-foreground transition-all duration-200"
                  >
                    {t("cancel") || "Annulla"}
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setProjectWarningModalOpen(false);
                      setProjectCreateOpen(true);
                    }}
                    className="rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90 transition-all duration-200"
                  >
                    {t("chat.project_warning.action")}
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      ) : null}
      {webRestrictModalOpen ? (
        <div
          className="fixed inset-0 z-[200] flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm transition-all"
          role="presentation"
          onClick={() => setWebRestrictModalOpen(false)}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="web-restrict-dialog-title"
            className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-2xl border border-border/60 bg-card/95 p-6 shadow-2xl backdrop-blur-xl flex flex-col"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center gap-3 border-b border-border/50 pb-4">
              <div className="flex size-10 items-center justify-center rounded-full bg-primary/10 text-primary">
                <Globe size={20} />
              </div>
              <div>
                <h2 id="web-restrict-dialog-title" className="text-lg font-semibold text-foreground">
                  {t("chat.web_search.modal_title")}
                </h2>
                <p className="text-sm text-muted-foreground">
                  {t("chat.web_search.modal_desc")}
                </p>
              </div>
            </div>

            <div className="mt-5">
              <label htmlFor="domain-input" className="block text-sm font-medium text-foreground mb-1.5">
                {t("chat.web_search.add_domain")}
              </label>
              <div className="flex gap-2">
                <input
                  id="domain-input"
                  type="text"
                  value={webRestrictInput}
                  onChange={(e) => {
                    setWebRestrictInput(e.target.value);
                    setWebRestrictInputError(null);
                  }}
                  onKeyDown={(e) => {
                    if (e.key !== "Enter") return;
                    e.preventDefault();
                    const parsed = parseWebHostInput(webRestrictInput);
                    if (!parsed) {
                      setWebRestrictInputError(t("chat.web_search.error_invalid_domain"));
                      return;
                    }
                    if (webRestrictDraft.includes(parsed)) {
                      setWebRestrictInputError(t("chat.web_search.error_duplicate_domain"));
                      return;
                    }
                    if (webRestrictDraft.length >= 20) {
                      setWebRestrictInputError(t("chat.web_search.error_max_domains"));
                      return;
                    }
                    setWebRestrictDraft((d) => [...d, parsed]);
                    setWebRestrictInput("");
                    setWebRestrictInputError(null);
                  }}
                  placeholder={t("chat.web_search.domain_placeholder")}
                  className="focus-ring min-w-0 flex-1 rounded-xl border border-border bg-background px-4 py-2.5 text-sm transition-colors hover:border-border/80 focus:border-primary/50"
                />
                <button
                  type="button"
                  className="flex items-center justify-center rounded-xl bg-primary px-4 py-2 text-primary-foreground font-medium transition-all hover:bg-primary/90 shadow-sm"
                  onClick={() => {
                    if (!webRestrictInput.trim()) return;
                    const parsed = parseWebHostInput(webRestrictInput);
                    if (!parsed) {
                      setWebRestrictInputError(t("chat.web_search.error_invalid_domain"));
                      return;
                    }
                    if (webRestrictDraft.includes(parsed)) {
                      setWebRestrictInputError(t("chat.web_search.error_duplicate_domain"));
                      return;
                    }
                    if (webRestrictDraft.length >= 20) {
                      setWebRestrictInputError(t("chat.web_search.error_max_domains"));
                      return;
                    }
                    setWebRestrictDraft((d) => [...d, parsed]);
                    setWebRestrictInput("");
                    setWebRestrictInputError(null);
                  }}
                >
                  {t("btn.add")}
                </button>
              </div>
              {webRestrictInputError ? (
                <p className="mt-2 text-xs font-medium text-destructive" role="alert">
                  {webRestrictInputError}
                </p>
              ) : (
                <p className="mt-2 text-xs text-muted-foreground">
                  {t("chat.web_search.domain_hint")}
                </p>
              )}
            </div>

            <div className="mt-6 flex-1">
              <h3 className="text-sm font-medium text-foreground mb-3">
                {t("chat.web_search.active_domains", { count: webRestrictDraft.length })}
              </h3>
              {webRestrictDraft.length > 0 ? (
                <div className="flex flex-wrap gap-2 p-3 rounded-xl border border-border/40 bg-muted/20 min-h-[80px]">
                  {webRestrictDraft.map((h) => (
                    <span
                      key={h}
                      className="group flex items-center gap-1.5 rounded-full border border-primary/20 bg-primary/5 px-3 py-1.5 text-sm font-medium text-primary shadow-sm transition-colors hover:bg-primary/10"
                    >
                      <Globe size={12} className="opacity-70" />
                      {h}
                      <button
                        type="button"
                        className="ml-1 flex size-4 items-center justify-center rounded-full text-primary/60 transition-colors hover:bg-primary/20 hover:text-primary"
                        aria-label={t("chat.web_search.remove_domain", { name: h })}
                        onClick={() => setWebRestrictDraft((d) => d.filter((x) => x !== h))}
                      >
                        <X size={10} strokeWidth={3} />
                      </button>
                    </span>
                  ))}
                </div>
              ) : (
                <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-border/60 bg-muted/10 py-8 text-center">
                  <p className="text-sm font-medium text-muted-foreground">{t("chat.web_search.no_domains")}</p>
                  <p className="mt-1 text-xs text-muted-foreground/80">
                    {t("chat.web_search.no_domains_desc")}
                  </p>
                </div>
              )}
            </div>

            <div className="mt-6 flex flex-wrap justify-between gap-2 border-t border-border/50 pt-5">
              <button
                type="button"
                className="rounded-xl px-4 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                onClick={() => {
                  setWebRestrictDraft([]);
                }}
              >
                {t("chat.web_search.clear_list")}
              </button>
              <div className="flex gap-2">
                <button
                  type="button"
                  className="rounded-xl border border-border/80 bg-background px-4 py-2 text-sm font-medium text-foreground shadow-sm transition-colors hover:bg-muted"
                  onClick={() => setWebRestrictModalOpen(false)}
                >
                  {t("btn.cancel")}
                </button>
                <button
                  type="button"
                  className="rounded-xl bg-primary px-5 py-2 text-sm font-medium text-primary-foreground shadow-sm transition-all hover:bg-primary/90"
                  onClick={() => {
                    persistWebRestrictHosts([...webRestrictDraft]);
                    setWebRestrictModalOpen(false);
                  }}
                >
                  {t("chat.web_search.save_preferences")}
                </button>
              </div>
            </div>
          </div>
        </div>
      ) : null}

      {mcpPendingOpen && mcpAlertCount > 0 && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="max-h-[85vh] w-full max-w-md overflow-y-auto rounded-xl border border-border bg-background p-5 shadow-xl">
            <div className="mb-3 flex items-center justify-between">
              <h3 className="text-lg font-semibold">
                {mcpRuntimeErrors.length > 0 && mcpPending.length === 0
                  ? t("integrationsPage.composer_runtime_errors")
                  : mcpRuntimeErrors.length > 0
                    ? t("integrationsPage.composer_alerts_mixed")
                    : t("integrationsPage.composer_pending")}
              </h3>
              <button type="button" onClick={() => setMcpPendingOpen(false)} className="text-muted-foreground hover:text-foreground">
                <X size={18} />
              </button>
            </div>
            <ul className="space-y-3 text-sm">
              {mcpRuntimeErrors.map((p) => (
                <li key={`err-${p.server_slug}`} className="rounded-lg border border-red-500/30 bg-red-500/5 p-3">
                  <div className="font-medium text-red-700 dark:text-red-300">{p.display_name}</div>
                  <p className="mt-1 text-xs text-muted-foreground">{p.message}</p>
                  {p.error ? (
                    <p className="mt-1 break-all font-mono text-[10px] text-red-600/90 dark:text-red-400/90">{p.error}</p>
                  ) : null}
                </li>
              ))}
              {mcpPending.map((p) => (
                <li key={p.server_slug} className="rounded-lg border border-border p-3">
                  <div className="font-medium">{p.display_name}</div>
                  <p className="mt-1 text-xs text-muted-foreground">{p.message}</p>
                  {p.reason === "credentials_missing" && p.integration ? (
                    <a
                      href="/integrations"
                      className="mt-2 inline-block text-xs font-medium text-primary hover:underline"
                      onClick={() => setMcpPendingOpen(false)}
                    >
                      {t("integrationsPage.connect")} →
                    </a>
                  ) : null}
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}
    </>
  );
}

const InternalMessageMarkdown = memo(function InternalMessageMarkdown({
  content,
  streaming,
  renderMarkdownLink,
  formatTextWithCitations,
}: {
  content: string;
  streaming: boolean;
  renderMarkdownLink: any;
  formatTextWithCitations: any;
}) {
  const components = useMemo(() => ({
    a: renderMarkdownLink,
    ...markdownCodeComponents({ streaming }),
  }), [streaming, renderMarkdownLink]);

  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm, remarkMath]}
      rehypePlugins={[rehypeKatex]}
      disallowedElements={["script"]}
      unwrapDisallowed
      components={components}
    >
      {formatTextWithCitations(content)}
    </ReactMarkdown>
  );
});

const UserMessageMarkdown = memo(function UserMessageMarkdown({
  content,
  renderMarkdownLink,
  formatTextWithCitations,
}: {
  content: string;
  renderMarkdownLink: any;
  formatTextWithCitations: any;
}) {
  const components = useMemo(() => ({
    table: ({ node, ...props }: any) => (
      <div className="table-wrapper">
        <table {...props} />
      </div>
    ),
    ...markdownCodeComponents(),
    a: renderMarkdownLink
  }), [renderMarkdownLink]);

  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm, remarkMath]}
      rehypePlugins={[rehypeKatex]}
      disallowedElements={["script"]}
      unwrapDisallowed
      components={components}
    >
      {formatTextWithCitations(content)}
    </ReactMarkdown>
  );
});
