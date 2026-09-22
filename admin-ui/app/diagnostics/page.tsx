"use client";

import React, { useState, useEffect, useRef } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  Play,
  Square,
  Eye,
  X,
  CheckCircle2,
  XCircle,
  Clock,
  Wrench,
  Brain,
  FileText,
  FileSpreadsheet,
  FileCode,
  Download,
  Copy,
  RefreshCw,
  Terminal,
  FlaskConical,
  ChevronRight,
  Sparkles,
  BarChart3,
  AlertCircle,
  Check,
  Search,
} from "lucide-react";
import { apiBase } from "@/lib/api";
import { apiFetch } from "@/lib/api/headers";
import { getStoredToken } from "@/lib/auth/storage";
import { SessionCharts } from "./SessionCharts";
import { MarkdownReportReader } from "./MarkdownReportReader";
import { HeaderDropdown } from "@/components/HeaderDropdown";

interface ProfileOption {
  slug: string;
  name: string;
  description?: string;
}

interface LogEvent {
  id: string;
  test?: string;
  test_name?: string;
  assistant?: string;
  step: string;
  message: string;
  timestamp: string;
  content?: string;
  token?: string;
  tool?: string;
  params?: any;
  result?: any;
  duration_sec?: number;
  status?: string;
  error?: string | boolean;
  preview?: string;
  final_output?: string;
  reasoning?: string;
  tool_calls?: any[];
  tool_count?: number;
  timeline?: any[];
  generated_files?: any[];
  single_report_filename?: string;
  score?: number;
  max_score?: number;
  rating?: string;
  passed?: boolean;
  eval_summary?: string;
  eval_criteria?: any[];
}

interface TestStatus {
  id: string;
  name: string;
  assistant?: string;
  status: "idle" | "running" | "completed" | "failed";
  duration_sec?: number;
  tool_count: number;
  reasoning_chars: number;
  last_message?: string;
  final_output?: string;
  reasoning?: string;
  tool_calls?: any[];
  timeline?: any[];
  generated_files?: any[];
  charts?: any[];
  single_report_filename?: string;
  score?: number;
  max_score?: number;
  rating?: string;
  passed?: boolean;
  eval_summary?: string;
  eval_criteria?: any[];
}

interface ReportFile {
  filename: string;
  size_bytes: number;
  modified_at: string;
}

function getScoreBadge(score?: number, rating?: string) {
  if (score === undefined) return null;
  const isHigh = score >= 90;
  const isGood = score >= 75;
  const isMid = score >= 50;
  const colorClass = isHigh
    ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/30"
    : isGood
      ? "bg-cyan-500/10 text-cyan-400 border-cyan-500/30"
      : isMid
        ? "bg-amber-500/10 text-amber-400 border-amber-500/30"
        : "bg-red-500/10 text-red-400 border-red-500/30";
  return (
    <span className={`px-2 py-0.5 rounded-md text-[11px] font-bold border flex items-center gap-1 ${colorClass}`}>
      <span>🎯</span>
      <span>{score}/100</span>
      {rating && <span className="opacity-80">[{rating}]</span>}
    </span>
  );
}

function getToolIcon(toolName?: string) {
  const name = (toolName || "").toLowerCase();
  if (name.includes("chart")) return <BarChart3 className="w-3.5 h-3.5 text-emerald-400 shrink-0" />;
  if (name.includes("python") || name.includes("node") || name.includes("code"))
    return <FileCode className="w-3.5 h-3.5 text-blue-400 shrink-0" />;
  if (name.includes("exec") || name.includes("command") || name.includes("terminal"))
    return <Terminal className="w-3.5 h-3.5 text-amber-400 shrink-0" />;
  if (name.includes("search") || name.includes("fetch"))
    return <Search className="w-3.5 h-3.5 text-cyan-400 shrink-0" />;
  if (name.includes("excel") || name.includes("xlsx") || name.includes("csv"))
    return <FileSpreadsheet className="w-3.5 h-3.5 text-emerald-400 shrink-0" />;
  if (name.includes("pdf") || name.includes("doc") || name.includes("file") || name.includes("ingest"))
    return <FileText className="w-3.5 h-3.5 text-orange-400 shrink-0" />;
  return <Wrench className="w-3.5 h-3.5 text-gray-400 shrink-0" />;
}

function MarkdownImage({ src, alt, ...props }: React.ImgHTMLAttributes<HTMLImageElement>) {
  const [hasError, setHasError] = useState(false);
  const token = getStoredToken();

  if (typeof src !== "string" || !src) return null;

  let resolvedSrc = src;
  const isHttpOrData = src.startsWith("http://") || src.startsWith("https://") || src.startsWith("data:");

  if (!isHttpOrData) {
    const cleanPath = src.replace(/^file:\/\/\/?(app\/)?/, "");
    resolvedSrc = `${apiBase()}/admin/diagnostics/file?path=${encodeURIComponent(cleanPath)}&access_token=${token || ""}`;
  }

  if (hasError) {
    return (
      <span className="my-2 inline-flex items-center gap-2 px-3 py-1.5 rounded-lg bg-[#141414] border border-[#262626] text-xs text-gray-300 select-none">
        <BarChart3 className="w-3.5 h-3.5 text-blue-400 shrink-0" />
        <span className="font-medium text-gray-200">{alt || "Generated Chart"}</span>
        <span className="text-[10px] text-gray-500 font-mono">({src.split("/").pop()})</span>
      </span>
    );
  }

  return (
    <span className="block my-3">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={resolvedSrc}
        alt={alt || "Generated Chart"}
        loading="lazy"
        onError={() => setHasError(true)}
        className="max-h-[440px] w-auto max-w-full rounded-xl border border-[#2e2e2e] bg-[#0d0d0d] shadow-lg object-contain"
        {...props}
      />
      {alt && <span className="block mt-1.5 text-[11px] text-gray-400 text-center font-sans italic">{alt}</span>}
    </span>
  );
}

function MarkdownLink({ href, children, ...props }: React.AnchorHTMLAttributes<HTMLAnchorElement>) {
  if (typeof href !== "string" || !href) return <a {...props}>{children}</a>;

  const isExternal = href.startsWith("http://") || href.startsWith("https://");
  if (isExternal) {
    return (
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        className="text-blue-400 hover:text-blue-300 underline hover:underline transition-colors"
        {...props}
      >
        {children}
      </a>
    );
  }

  if (href.startsWith("#") || href.startsWith("mailto:")) {
    return <a href={href} {...props}>{children}</a>;
  }

  let cleanPath = href.replace(/^file:\/\/\/?(app\/)?/i, "");
  cleanPath = cleanPath.replace(/^[./\\]+/, "");

  const token = getStoredToken();
  const downloadUrl = `${apiBase()}/admin/diagnostics/file?path=${encodeURIComponent(cleanPath)}&download=1&access_token=${token || ""}`;

  return (
    <a
      href={downloadUrl}
      download
      target="_blank"
      rel="noopener noreferrer"
      className="inline-flex items-center gap-1 text-blue-400 hover:text-blue-300 underline font-mono text-xs hover:bg-blue-950/30 px-1 py-0.5 rounded transition-colors"
      {...props}
    >
      <span>{children}</span>
      <Download className="w-3 h-3 inline opacity-70" />
    </a>
  );
}

const markdownComponents = {
  img: MarkdownImage,
  a: MarkdownLink,
};

export default function DiagnosticsPage() {
  const [isRunning, setIsRunning] = useState(false);
  const [activeTab, setActiveTab] = useState<"stream" | "report" | "history">("stream");
  const [filterTest, setFilterTest] = useState<string>("all");

  const [testsStatus, setTestsStatus] = useState<Record<string, TestStatus>>({
    test_1_excel: {
      id: "test_1_excel",
      name: "Excel Data Analysis",
      status: "idle",
      tool_count: 0,
      reasoning_chars: 0,
    },
    test_2_pdf: {
      id: "test_2_pdf",
      name: "Long PDF Document RAG",
      status: "idle",
      tool_count: 0,
      reasoning_chars: 0,
    },
    test_3_word: {
      id: "test_3_word",
      name: "Structured Word Generation",
      status: "idle",
      tool_count: 0,
      reasoning_chars: 0,
    },
  });

  const [logs, setLogs] = useState<LogEvent[]>([]);
  const [currentReport, setCurrentReport] = useState<string>("");
  const [currentReportName, setCurrentReportName] = useState<string>("");
  const [historyReports, setHistoryReports] = useState<ReportFile[]>([]);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [expandedLogs, setExpandedLogs] = useState<Record<string, boolean>>({});
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const [profiles, setProfiles] = useState<ProfileOption[]>([]);
  const [selectedProfile, setSelectedProfile] = useState<string>("generic_assistant");
  const [loadingProfiles, setLoadingProfiles] = useState<boolean>(false);

  const [selectedTestModal, setSelectedTestModal] = useState<TestStatus | null>(null);
  const [modalActiveTab, setModalActiveTab] = useState<"final" | "eval" | "charts" | "files" | "timeline" | "reasoning">("final");
  const eventSourceRef = useRef<EventSource | null>(null);

  const logsEndRef = useRef<HTMLDivElement>(null);
  const [autoScroll, setAutoScroll] = useState(true);

  useEffect(() => {
    fetchHistoryReports();
    fetchProfiles();
  }, []);

  useEffect(() => {
    if (autoScroll && logsEndRef.current) {
      logsEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [logs, autoScroll]);

  const fetchProfiles = async () => {
    setLoadingProfiles(true);
    try {
      const res = await apiFetch(`${apiBase()}/admin/profiles`);
      if (res.ok) {
        const data = await res.json();
        if (Array.isArray(data) && data.length > 0) {
          const mapped: ProfileOption[] = data.map((p: any) => ({
            slug: p.slug || p.name.replace(/\s+/g, "_").toLowerCase(),
            name: p.name || p.slug,
            description: p.description || "",
          }));
          setProfiles(mapped);
          const hasGeneric = mapped.some((p) => p.slug === "generic_assistant");
          if (!hasGeneric && mapped.length > 0) {
            setSelectedProfile(mapped[0].slug);
          }
        }
      }
    } catch (e) {
      console.error("Failed to fetch profiles:", e);
    } finally {
      setLoadingProfiles(false);
    }
  };

  const fetchHistoryReports = async () => {
    setLoadingHistory(true);
    try {
      const res = await apiFetch(`${apiBase()}/admin/diagnostics/reports`);
      if (res.ok) {
        const data = await res.json();
        setHistoryReports(data);
      }
    } catch (e) {
      console.error("Failed to fetch reports:", e);
    } finally {
      setLoadingHistory(false);
    }
  };

  const loadReportContent = async (filename: string) => {
    try {
      const res = await apiFetch(`${apiBase()}/admin/diagnostics/reports/${encodeURIComponent(filename)}`);
      if (res.ok) {
        const data = await res.json();
        setCurrentReport(data.content);
        setCurrentReportName(filename);
        setActiveTab("report");
      }
    } catch (e) {
      console.error("Failed to load report content:", e);
    }
  };

  const handleStopTests = async () => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
    try {
      await apiFetch(`${apiBase()}/admin/diagnostics/cancel`, { method: "POST" });
    } catch (e) {
      console.error("Failed to cancel diagnostics:", e);
    }
    setIsRunning(false);
    setLogs((prev) => [
      ...prev,
      {
        id: `cancelled_${Date.now()}`,
        step: "test_error",
        message: "Test suite execution cancelled by user.",
        timestamp: new Date().toISOString(),
        error: "Execution cancelled.",
      },
    ]);
  };

  const handleRunTests = async () => {
    if (isRunning) return;

    setIsRunning(true);
    setLogs([]);
    setCurrentReport("");
    setActiveTab("stream");

    // Reset test statuses
    setTestsStatus({
      test_1_excel: { id: "test_1_excel", name: "Excel Data Analysis", assistant: selectedProfile, status: "idle", tool_count: 0, reasoning_chars: 0 },
      test_2_pdf: { id: "test_2_pdf", name: "Long PDF Document RAG", assistant: selectedProfile, status: "idle", tool_count: 0, reasoning_chars: 0 },
      test_3_word: { id: "test_3_word", name: "Structured Word Generation", assistant: selectedProfile, status: "idle", tool_count: 0, reasoning_chars: 0 },
    });

    const token = getStoredToken();
    const profileParam = selectedProfile ? `&profile=${encodeURIComponent(selectedProfile)}` : "";
    const url = `${apiBase()}/admin/diagnostics/run-tests?access_token=${token || ""}${profileParam}`;

    try {
      const eventSource = new EventSource(url);
      eventSourceRef.current = eventSource;

      eventSource.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          const evtId = `${Date.now()}_${Math.random().toString(36).substr(2, 6)}`;
          const logEntry: LogEvent = {
            id: evtId,
            test: data.test,
            test_name: data.test_name,
            assistant: data.assistant,
            step: data.step,
            message: data.message || "",
            timestamp: data.timestamp || new Date().toISOString(),
            content: data.content,
            token: data.token,
            tool: data.tool,
            params: data.params,
            result: data.result,
            duration_sec: data.duration_sec,
            status: data.status,
            error: data.error,
            preview: data.preview,
            final_output: data.final_output,
            reasoning: data.reasoning,
            tool_calls: data.tool_calls,
            tool_count: data.tool_count,
            timeline: data.timeline,
            generated_files: data.generated_files,
            single_report_filename: data.single_report_filename,
          };

          // Aggregate streaming chunks in real-time
          setLogs((prev) => {
            // Aggregate consecutive reasoning chunks
            if (data.step === "reasoning" && data.content) {
              const lastIdx = prev.length - 1;
              if (lastIdx >= 0 && prev[lastIdx].step === "reasoning" && prev[lastIdx].test === data.test) {
                const updated = [...prev];
                updated[lastIdx] = {
                  ...updated[lastIdx],
                  content: (updated[lastIdx].content || "") + data.content,
                  timestamp: data.timestamp || updated[lastIdx].timestamp,
                };
                return updated;
              }
              return [...prev, { ...logEntry, message: "Reasoning Chain" }];
            }

            // Intermediate working notes (between tool calls)
            if (data.step === "working_note" && data.content) {
              return [...prev, { ...logEntry, message: data.message || "Operation Step" }];
            }

            // Streaming tokens of final response
            if (data.step === "token" && (data.token || data.content)) {
              const tokenText = data.token || data.content || "";
              const lastIdx = prev.length - 1;
              if (lastIdx >= 0 && prev[lastIdx].step === "token" && prev[lastIdx].test === data.test) {
                const updated = [...prev];
                updated[lastIdx] = {
                  ...updated[lastIdx],
                  content: (updated[lastIdx].content || "") + tokenText,
                  timestamp: data.timestamp || updated[lastIdx].timestamp,
                };
                return updated;
              }
              return [...prev, { ...logEntry, content: tokenText, message: "Generating Final Response..." }];
            }

            // Update matching tool call with result when tool_result arrives
            if (data.step === "tool_result") {
              for (let i = prev.length - 1; i >= 0; i--) {
                if (prev[i].step === "tool_call" && prev[i].test === data.test && prev[i].tool === data.tool) {
                  const updated = [...prev];
                  updated[i] = {
                    ...updated[i],
                    status: data.error ? "error" : "success",
                    error: data.error,
                    preview: data.preview,
                    result: data.result,
                  };
                  return updated;
                }
              }
            }

            return [...prev, logEntry];
          });

          // Update test cards status
          if (data.test && testsStatus[data.test] !== undefined) {
            setTestsStatus((prev) => {
              const curr = prev[data.test] || {
                id: data.test,
                name: data.test_name || data.test,
                assistant: data.assistant || selectedProfile,
                status: "running",
                tool_count: 0,
                reasoning_chars: 0,
              };

              let nextStatus = curr.status;
              let nextAssistant = data.assistant || curr.assistant || selectedProfile;
              let nextTools = curr.tool_count;
              let nextReasoning = curr.reasoning_chars;
              let nextFinalOutput = curr.final_output;
              let nextReasoningFull = curr.reasoning;
              let nextToolCalls = curr.tool_calls || [];
              let nextTimeline = curr.timeline || [];
              let nextFiles = curr.generated_files || [];
              let nextCharts = curr.charts || [];
              let nextScore = curr.score;
              let nextMaxScore = curr.max_score;
              let nextRating = curr.rating;
              let nextPassed = curr.passed;
              let nextEvalSummary = curr.eval_summary;
              let nextEvalCriteria = curr.eval_criteria;

              if (data.step === "test_start") nextStatus = "running";
              else if (data.step === "test_complete") {
                nextStatus = data.status === "failed" ? "failed" : "completed";
                nextFinalOutput = data.final_output;
                nextReasoningFull = data.reasoning;
                nextToolCalls = data.tool_calls || nextToolCalls;
                nextTimeline = data.timeline || nextTimeline;
                nextFiles = data.generated_files || nextFiles;
                if (data.assistant) nextAssistant = data.assistant;
                if (data.tool_count !== undefined) nextTools = data.tool_count;
                if (data.score !== undefined) nextScore = data.score;
                if (data.max_score !== undefined) nextMaxScore = data.max_score;
                if (data.rating !== undefined) nextRating = data.rating;
                if (data.passed !== undefined) nextPassed = data.passed;
                if (data.eval_summary !== undefined) nextEvalSummary = data.eval_summary;
                if (data.eval_criteria !== undefined) nextEvalCriteria = data.eval_criteria;
              } else if (data.step === "test_error") {
                nextStatus = "failed";
              }

              if (data.step === "tool_call") {
                nextTools += 1;
                if (data.tool === "render_chart" && data.params) {
                  nextCharts = [...nextCharts, data.params];
                }
              }
              if (data.step === "reasoning" && data.content) nextReasoning += data.content.length;

              return {
                ...prev,
                [data.test]: {
                  ...curr,
                  status: nextStatus,
                  assistant: nextAssistant,
                  duration_sec: data.duration_sec ?? curr.duration_sec,
                  tool_count: nextTools,
                  reasoning_chars: nextReasoning,
                  last_message: data.message,
                  final_output: nextFinalOutput,
                  reasoning: nextReasoningFull,
                  tool_calls: nextToolCalls,
                  timeline: nextTimeline,
                  generated_files: nextFiles,
                  charts: nextCharts,
                  single_report_filename: data.single_report_filename || curr.single_report_filename,
                  score: nextScore,
                  max_score: nextMaxScore,
                  rating: nextRating,
                  passed: nextPassed,
                  eval_summary: nextEvalSummary,
                  eval_criteria: nextEvalCriteria,
                },
              };
            });
          }

          if (data.step === "suite_complete") {
            if (data.report_content) {
              setCurrentReport(data.report_content);
              setCurrentReportName(data.report_filename || "report_smoke_test.md");
            }
            fetchHistoryReports();
            eventSource.close();
            eventSourceRef.current = null;
            setIsRunning(false);
          }
        } catch (err) {
          console.error("Error parsing event data:", err);
        }
      };

      eventSource.onerror = (err) => {
        console.error("EventSource error:", err);
        eventSource.close();
        eventSourceRef.current = null;
        setIsRunning(false);
      };
    } catch (e) {
      console.error("Failed to connect to SSE stream:", e);
      setIsRunning(false);
    }
  };

  const toggleExpand = (id: string, defaultOpen = false) => {
    setExpandedLogs((prev) => {
      const current = prev[id] !== undefined ? prev[id] : defaultOpen;
      return { ...prev, [id]: !current };
    });
  };

  const isLogExpanded = (id: string, defaultOpen = false) => {
    return expandedLogs[id] !== undefined ? expandedLogs[id] : defaultOpen;
  };

  const filteredLogs = logs.filter((log) => {
    if (filterTest === "all") return true;
    return log.test === filterTest;
  });

  const copyToClipboard = (text: string, id?: string) => {
    navigator.clipboard.writeText(text);
    if (id) {
      setCopiedId(id);
      setTimeout(() => setCopiedId(null), 2000);
    }
  };

  const downloadMarkdown = (content: string, filename: string) => {
    const blob = new Blob([content], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename || "smoke_test_report.md";
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  const activeProfileObj = profiles.find((p) => p.slug === selectedProfile);

  return (
    <div className="space-y-6">
      {/* Page Title & Description */}
      <div className="space-y-1 pb-1">
        <div className="flex items-center gap-3">
          <span className="p-2 rounded-xl bg-blue-500/10 text-blue-400 border border-blue-500/20 shadow-inner">
            <FlaskConical className="w-5 h-5" />
          </span>
          <h1 className="text-2xl sm:text-3xl font-extrabold tracking-tight text-white font-sans">
            Smoke Tests Diagnostics Suite
          </h1>
        </div>
        <p className="text-sm text-gray-400 max-w-3xl mt-1 font-sans">
          End-to-end evaluation suite with real-time reasoning interception, tool calls, interactive charts, and markdown evaluation reports.
        </p>
      </div>

      {/* ==========================================
          CONTROL BAR: TARGET PROFILE SWITCHER & TEST CONTROLS
          ========================================== */}
      <header className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 px-5 py-3.5 bg-[#0a0a0a]/95 border border-slate-800/80 backdrop-blur-xl shadow-xl rounded-2xl">
        <div className="flex items-center gap-4 flex-wrap">
          {/* Profile Switcher via HeaderDropdown */}
          <HeaderDropdown
            triggerIcon={<Terminal className="w-5 h-5" />}
            triggerLabelTop="Target Test Profile"
            triggerLabelMain={
              loadingProfiles
                ? "Loading..."
                : activeProfileObj
                  ? `${activeProfileObj.name} (${activeProfileObj.slug})`
                  : selectedProfile || "Select Profile..."
            }
            items={
              profiles.length > 0
                ? profiles.map((p) => ({
                  key: p.slug,
                  label: `${p.name} (${p.slug})`,
                }))
                : [{ key: "generic_assistant", label: "Generic Assistant (generic_assistant)" }]
            }
            selectedKey={selectedProfile}
            itemIcon={<Terminal className="w-4 h-4 text-blue-400" />}
            onItemSelect={(key) => {
              if (!isRunning) setSelectedProfile(key);
            }}
            searchPlaceholder="Search profiles..."
            emptyLabel="No profiles found"
            actions={[]}
          />

          {/* Active Profile Info / Description */}
          {activeProfileObj?.description && (
            <div className="hidden lg:flex items-center gap-2 px-3 py-1.5 rounded-xl bg-[#121212] border border-slate-800/80 text-xs text-gray-400 max-w-md truncate">
              <Sparkles className="w-3.5 h-3.5 text-blue-400 shrink-0" />
              <span className="truncate">{activeProfileObj.description}</span>
            </div>
          )}
        </div>

        {/* Primary Run / Stop Action */}
        <div className="flex items-center gap-3 shrink-0">
          {isRunning ? (
            <button
              onClick={handleStopTests}
              className="flex items-center gap-2 px-5 py-2.5 rounded-xl font-bold text-sm transition-all shadow-lg bg-red-600 hover:bg-red-500 text-white hover:shadow-red-500/20 cursor-pointer animate-pulse"
            >
              <Square className="w-4 h-4 fill-current" />
              <span>Stop Test Suite</span>
            </button>
          ) : (
            <button
              onClick={handleRunTests}
              disabled={loadingProfiles}
              className="flex items-center gap-2 px-6 py-2.5 rounded-xl font-bold text-sm transition-all shadow-[0_0_15px_rgba(59,130,246,0.25)] bg-blue-600 hover:bg-blue-500 text-white hover:shadow-[0_0_20px_rgba(59,130,246,0.4)] disabled:opacity-50 cursor-pointer"
            >
              <Play className="w-4 h-4 fill-current" />
              <span>Run Test Suite</span>
            </button>
          )}
        </div>
      </header>

      {/* Test scenario status cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Test 1 Card */}
        <div className={`p-4 rounded-xl border transition-all ${testsStatus.test_1_excel.status === "running"
          ? "border-blue-500/60 bg-blue-950/10 shadow-lg shadow-blue-500/5"
          : testsStatus.test_1_excel.status === "completed"
            ? "border-emerald-500/40 bg-[#141414]/90"
            : testsStatus.test_1_excel.status === "failed"
              ? "border-red-500/40 bg-[#141414]/90"
              : "border-[#262626] bg-[#141414]/60"
          }`}>
          <div className="flex items-start justify-between gap-2">
            <div className="flex items-center gap-2.5">
              <span className="p-2 rounded-lg bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                <FileSpreadsheet className="w-4 h-4" />
              </span>
              <div>
                <h3 className="text-sm font-semibold text-white">1. Excel Data Analysis</h3>
                <span className="text-[11px] text-gray-400">KPIs, Pareto 80/20 & Trends</span>
              </div>
            </div>
            {testsStatus.test_1_excel.status === "running" && (
              <span className="flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] font-medium bg-blue-500/10 text-blue-400 border border-blue-500/30 animate-pulse">
                <RefreshCw className="w-3 h-3 animate-spin" /> Running
              </span>
            )}
            {testsStatus.test_1_excel.status === "completed" && (
              <div className="flex items-center gap-1.5">
                {getScoreBadge(testsStatus.test_1_excel.score, testsStatus.test_1_excel.rating)}
                <span className="flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">
                  <CheckCircle2 className="w-3 h-3" /> {testsStatus.test_1_excel.duration_sec}s
                </span>
              </div>
            )}
            {testsStatus.test_1_excel.status === "failed" && (
              <div className="flex items-center gap-1.5">
                {getScoreBadge(testsStatus.test_1_excel.score, testsStatus.test_1_excel.rating)}
                <span className="flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium bg-red-500/10 text-red-400 border border-red-500/30">
                  <XCircle className="w-3 h-3" /> Failed
                </span>
              </div>
            )}
            {testsStatus.test_1_excel.status === "idle" && (
              <span className="px-2 py-0.5 rounded-full text-[11px] text-gray-500 bg-gray-800/40 border border-gray-700/40">
                Pending
              </span>
            )}
          </div>
          <div className="mt-3 pt-3 border-t border-[#262626] flex items-center justify-between text-xs text-gray-400">
            <span>Attachment: <code className="text-gray-300 bg-black/40 px-1 py-0.5 rounded text-[10px]">dataset_vendite.xlsx</code></span>
            <div className="flex items-center gap-2">
              <span className="flex items-center gap-1 text-[11px] text-gray-400" title="Tools Called">
                <Wrench className="w-3 h-3 text-gray-500" /> {testsStatus.test_1_excel.tool_count} tools
              </span>
            </div>
          </div>
          {testsStatus.test_1_excel.status === "completed" && (
            <button
              type="button"
              onClick={() => {
                setSelectedTestModal(testsStatus.test_1_excel);
                setModalActiveTab("final");
              }}
              className="mt-3 w-full flex items-center justify-center gap-1.5 py-1.5 px-3 rounded-lg bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-300 text-xs font-semibold border border-emerald-500/30 transition-all cursor-pointer"
            >
              <Eye className="w-3.5 h-3.5" />
              <span>View Result & Deliverables</span>
            </button>
          )}
        </div>

        {/* Test 2 Card */}
        <div className={`p-4 rounded-xl border transition-all ${testsStatus.test_2_pdf.status === "running"
          ? "border-blue-500/60 bg-blue-950/10 shadow-lg shadow-blue-500/5"
          : testsStatus.test_2_pdf.status === "completed"
            ? "border-emerald-500/40 bg-[#141414]/90"
            : testsStatus.test_2_pdf.status === "failed"
              ? "border-red-500/40 bg-[#141414]/90"
              : "border-[#262626] bg-[#141414]/60"
          }`}>
          <div className="flex items-start justify-between gap-2">
            <div className="flex items-center gap-2.5">
              <span className="p-2 rounded-lg bg-red-500/10 text-red-400 border border-red-500/20">
                <FileText className="w-4 h-4" />
              </span>
              <div>
                <h3 className="text-sm font-semibold text-white">2. Long PDF Document RAG</h3>
                <span className="text-[11px] text-gray-400">Tesla Manual: Door & Braking Ops</span>
              </div>
            </div>
            {testsStatus.test_2_pdf.status === "running" && (
              <span className="flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] font-medium bg-blue-500/10 text-blue-400 border border-blue-500/30 animate-pulse">
                <RefreshCw className="w-3 h-3 animate-spin" /> Running
              </span>
            )}
            {testsStatus.test_2_pdf.status === "completed" && (
              <div className="flex items-center gap-1.5">
                {getScoreBadge(testsStatus.test_2_pdf.score, testsStatus.test_2_pdf.rating)}
                <span className="flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">
                  <CheckCircle2 className="w-3 h-3" /> {testsStatus.test_2_pdf.duration_sec}s
                </span>
              </div>
            )}
            {testsStatus.test_2_pdf.status === "failed" && (
              <div className="flex items-center gap-1.5">
                {getScoreBadge(testsStatus.test_2_pdf.score, testsStatus.test_2_pdf.rating)}
                <span className="flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium bg-red-500/10 text-red-400 border border-red-500/30">
                  <XCircle className="w-3 h-3" /> Failed
                </span>
              </div>
            )}
            {testsStatus.test_2_pdf.status === "idle" && (
              <span className="px-2 py-0.5 rounded-full text-[11px] text-gray-500 bg-gray-800/40 border border-gray-700/40">
                Pending
              </span>
            )}
          </div>
          <div className="mt-3 pt-3 border-t border-[#262626] flex items-center justify-between text-xs text-gray-400">
            <span>Attachment: <code className="text-gray-300 bg-black/40 px-1 py-0.5 rounded text-[10px]">manuale_tesla.pdf</code></span>
            <div className="flex items-center gap-2">
              <span className="flex items-center gap-1 text-[11px] text-gray-400">
                <Wrench className="w-3 h-3 text-gray-500" /> {testsStatus.test_2_pdf.tool_count} tools
              </span>
            </div>
          </div>
          {testsStatus.test_2_pdf.status === "completed" && (
            <button
              type="button"
              onClick={() => {
                setSelectedTestModal(testsStatus.test_2_pdf);
                setModalActiveTab("final");
              }}
              className="mt-3 w-full flex items-center justify-center gap-1.5 py-1.5 px-3 rounded-lg bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-300 text-xs font-semibold border border-emerald-500/30 transition-all cursor-pointer"
            >
              <Eye className="w-3.5 h-3.5" />
              <span>View Result & Deliverables</span>
            </button>
          )}
        </div>

        {/* Test 3 Card */}
        <div className={`p-4 rounded-xl border transition-all ${testsStatus.test_3_word.status === "running"
          ? "border-blue-500/60 bg-blue-950/10 shadow-lg shadow-blue-500/5"
          : testsStatus.test_3_word.status === "completed"
            ? "border-emerald-500/40 bg-[#141414]/90"
            : testsStatus.test_3_word.status === "failed"
              ? "border-red-500/40 bg-[#141414]/90"
              : "border-[#262626] bg-[#141414]/60"
          }`}>
          <div className="flex items-start justify-between gap-2">
            <div className="flex items-center gap-2.5">
              <span className="p-2 rounded-lg bg-blue-500/10 text-blue-400 border border-blue-500/20">
                <FileText className="w-4 h-4" />
              </span>
              <div>
                <h3 className="text-sm font-semibold text-white">3. Structured Word Generation</h3>
                <span className="text-[11px] text-gray-400">Project Kickoff Meeting Agenda</span>
              </div>
            </div>
            {testsStatus.test_3_word.status === "running" && (
              <span className="flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] font-medium bg-blue-500/10 text-blue-400 border border-blue-500/30 animate-pulse">
                <RefreshCw className="w-3 h-3 animate-spin" /> Running
              </span>
            )}
            {testsStatus.test_3_word.status === "completed" && (
              <div className="flex items-center gap-1.5">
                {getScoreBadge(testsStatus.test_3_word.score, testsStatus.test_3_word.rating)}
                <span className="flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">
                  <CheckCircle2 className="w-3 h-3" /> {testsStatus.test_3_word.duration_sec}s
                </span>
              </div>
            )}
            {testsStatus.test_3_word.status === "failed" && (
              <div className="flex items-center gap-1.5">
                {getScoreBadge(testsStatus.test_3_word.score, testsStatus.test_3_word.rating)}
                <span className="flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium bg-red-500/10 text-red-400 border border-red-500/30">
                  <XCircle className="w-3 h-3" /> Failed
                </span>
              </div>
            )}
            {testsStatus.test_3_word.status === "idle" && (
              <span className="px-2 py-0.5 rounded-full text-[11px] text-gray-500 bg-gray-800/40 border border-gray-700/40">
                Pending
              </span>
            )}
          </div>
          <div className="mt-3 pt-3 border-t border-[#262626] flex items-center justify-between text-xs text-gray-400">
            <span>Output: <code className="text-gray-300 bg-black/40 px-1 py-0.5 rounded text-[10px]">agenda_kickoff.docx</code></span>
            <div className="flex items-center gap-2">
              <span className="flex items-center gap-1 text-[11px] text-gray-400">
                <Wrench className="w-3 h-3 text-gray-500" /> {testsStatus.test_3_word.tool_count} tools
              </span>
            </div>
          </div>
          {testsStatus.test_3_word.status === "completed" && (
            <button
              type="button"
              onClick={() => {
                setSelectedTestModal(testsStatus.test_3_word);
                setModalActiveTab("final");
              }}
              className="mt-3 w-full flex items-center justify-center gap-1.5 py-1.5 px-3 rounded-lg bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-300 text-xs font-semibold border border-emerald-500/30 transition-all cursor-pointer"
            >
              <Eye className="w-3.5 h-3.5" />
              <span>View Result & Deliverables</span>
            </button>
          )}
        </div>
      </div>

      {/* Main navigation tabs */}
      <div className="flex items-center justify-between border-b border-[#262626]">
        <div className="flex gap-1">
          <button
            onClick={() => setActiveTab("stream")}
            className={`flex items-center gap-2 px-4 py-2.5 text-xs font-semibold border-b-2 transition-all cursor-pointer ${activeTab === "stream"
              ? "border-blue-500 text-blue-400 bg-blue-500/5"
              : "border-transparent text-gray-400 hover:text-gray-200"
              }`}
          >
            <Terminal className="w-3.5 h-3.5" />
            <span>Live Stream Feed</span>
          </button>

          <button
            onClick={() => setActiveTab("report")}
            className={`flex items-center gap-2 px-4 py-2.5 text-xs font-semibold border-b-2 transition-all cursor-pointer ${activeTab === "report"
              ? "border-blue-500 text-blue-400 bg-blue-500/5"
              : "border-transparent text-gray-400 hover:text-gray-200"
              }`}
          >
            <FileText className="w-3.5 h-3.5" />
            <span>Markdown Report</span>
            {currentReport && (
              <span className="w-2 h-2 rounded-full bg-emerald-400"></span>
            )}
          </button>

          <button
            onClick={() => {
              setActiveTab("history");
              fetchHistoryReports();
            }}
            className={`flex items-center gap-2 px-4 py-2.5 text-xs font-semibold border-b-2 transition-all cursor-pointer ${activeTab === "history"
              ? "border-blue-500 text-blue-400 bg-blue-500/5"
              : "border-transparent text-gray-400 hover:text-gray-200"
              }`}
          >
            <Clock className="w-3.5 h-3.5" />
            <span>Report History ({historyReports.length})</span>
          </button>
        </div>

        {activeTab === "stream" && (
          <div className="flex items-center gap-2 pb-2">
            <select
              value={filterTest}
              onChange={(e) => setFilterTest(e.target.value)}
              className="bg-[#141414] border border-[#262626] rounded-md px-2.5 py-1 text-xs text-gray-300 focus:outline-none focus:border-blue-500"
            >
              <option value="all">All Tests</option>
              <option value="test_1_excel">Test 1 (Excel)</option>
              <option value="test_2_pdf">Test 2 (PDF RAG)</option>
              <option value="test_3_word">Test 3 (Word)</option>
            </select>

            <button
              onClick={() => setAutoScroll(!autoScroll)}
              className={`px-2 py-1 rounded text-xs border cursor-pointer transition-all ${autoScroll
                ? "bg-blue-500/10 border-blue-500/30 text-blue-400"
                : "bg-[#141414] border-[#262626] text-gray-400"
                }`}
            >
              Auto-scroll: {autoScroll ? "ON" : "OFF"}
            </button>
          </div>
        )}
      </div>

      {/* Tab 1: Live Streaming Feed (Chat-UI style) */}
      {activeTab === "stream" && (
        <div className="rounded-xl border border-[#262626] bg-[#0c0c0c] overflow-hidden flex flex-col h-[560px]">
          {/* Terminal stream bar */}
          <div className="flex items-center justify-between px-4 py-2.5 bg-[#141414] border-b border-[#262626] text-xs font-mono text-gray-400">
            <div className="flex items-center gap-2">
              <span className="w-2.5 h-2.5 rounded-full bg-red-500/80 inline-block"></span>
              <span className="w-2.5 h-2.5 rounded-full bg-yellow-500/80 inline-block"></span>
              <span className="w-2.5 h-2.5 rounded-full bg-green-500/80 inline-block"></span>
              <span className="ml-2 text-gray-300 font-sans font-medium">Agent Activity Stream</span>
            </div>
            {isRunning && (
              <span className="flex items-center gap-1.5 text-blue-400">
                <Sparkles className="w-3.5 h-3.5 animate-pulse" /> Active Stream
              </span>
            )}
          </div>

          <div className="flex-1 p-4 overflow-y-auto space-y-3">
            {filteredLogs.length === 0 ? (
              <div className="h-full flex flex-col items-center justify-center text-gray-500 font-sans space-y-3">
                <Terminal className="w-10 h-10 text-gray-600 stroke-[1.5]" />
                <p>No events recorded yet. Click on <strong>"Run Test Suite"</strong> to begin.</p>
              </div>
            ) : (
              filteredLogs.map((log) => {
                const isReasoningOpen = isLogExpanded(log.id, true);
                const isToolOpen = isLogExpanded(log.id, false);

                return (
                  <div key={log.id} className="transition-all">
                    {/* 1. Reasoning Block */}
                    {log.step === "reasoning" && log.content && (
                      <div className="py-1">
                        <button
                          type="button"
                          onClick={() => toggleExpand(log.id, true)}
                          className="flex items-center gap-2 text-xs text-gray-400 hover:text-gray-200 font-medium cursor-pointer transition-colors py-1 w-full text-left"
                        >
                          <Brain className="w-3.5 h-3.5 opacity-70 text-gray-400 shrink-0" />
                          <span className="text-xs">Reasoning</span>
                          <ChevronRight
                            className={`w-3.5 h-3.5 text-gray-500 transition-transform duration-200 ml-auto shrink-0 ${isReasoningOpen ? "rotate-90" : ""
                              }`}
                          />
                        </button>
                        {isReasoningOpen && (
                          <div className="mt-1.5 rounded-lg bg-white/[0.02] border border-white/[0.05] p-3 text-gray-400 font-sans text-xs whitespace-pre-wrap leading-relaxed">
                            {log.content}
                          </div>
                        )}
                      </div>
                    )}

                    {/* 2. Tool Call & Execution Block */}
                    {log.step === "tool_call" && (
                      <div className="rounded-lg border border-[#262626] bg-[#111] p-2.5 text-xs shadow-sm space-y-2">
                        <div className="flex items-center justify-between gap-2 flex-wrap">
                          <div className="flex items-center gap-2 min-w-0">
                            {getToolIcon(log.tool)}
                            <span className="font-semibold text-gray-200 font-mono text-xs">{log.tool}</span>
                            {log.params && typeof log.params === "object" && (
                              <span className="text-gray-400 text-[11px] font-mono truncate max-w-[280px]">
                                {log.params.relative_path || log.params.file_name || log.params.command || log.params.title || ""}
                              </span>
                            )}
                          </div>

                          <div className="flex items-center gap-2 shrink-0">
                            {log.status === "success" && (
                              <span className="flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">
                                <Check className="w-3 h-3" /> Executed
                              </span>
                            )}
                            {log.status === "error" && (
                              <span className="flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-amber-500/10 text-amber-400 border border-amber-500/30">
                                <AlertCircle className="w-3 h-3" /> Tool Error
                              </span>
                            )}
                            {log.status === "running" && (
                              <span className="flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-blue-500/10 text-blue-400 border border-blue-500/30 animate-pulse">
                                <RefreshCw className="w-3 h-3 animate-spin" /> In progress
                              </span>
                            )}

                            <button
                              type="button"
                              onClick={() => toggleExpand(log.id, false)}
                              className="px-2 py-0.5 rounded bg-[#1a1a1a] hover:bg-[#252525] text-gray-400 hover:text-gray-200 border border-[#333] cursor-pointer text-[10px] font-medium transition-colors"
                            >
                              {isToolOpen ? "Collapse" : "Expand"}
                            </button>
                            <span className="text-[10px] text-gray-600 font-mono">
                              {new Date(log.timestamp).toLocaleTimeString()}
                            </span>
                          </div>
                        </div>

                        {/* Interactive Chart if tool is render_chart */}
                        {log.tool === "render_chart" && log.params && (
                          <div className="pt-2">
                            <SessionCharts charts={[log.params]} />
                          </div>
                        )}

                        {/* Collapsible Tool Payload & Result */}
                        {isToolOpen && (
                          <div className="space-y-2 pt-2 border-t border-[#222]">
                            {log.params && (
                              <div>
                                <span className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider block mb-1">
                                  Input Parameters (JSON):
                                </span>
                                <pre className="p-2.5 rounded bg-black/60 border border-[#222] text-amber-200/90 font-mono text-[11px] overflow-x-auto max-h-[200px]">
                                  {JSON.stringify(log.params, null, 2)}
                                </pre>
                              </div>
                            )}

                            {log.result && (
                              <div>
                                <span className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider block mb-1">
                                  Tool Output / Result:
                                </span>
                                <pre className="p-2.5 rounded bg-black/60 border border-[#222] text-gray-300 font-mono text-[11px] overflow-x-auto max-h-[200px]">
                                  {typeof log.result === "object" ? JSON.stringify(log.result, null, 2) : String(log.result)}
                                </pre>
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    )}

                    {/* 3. Active Token Stream */}
                    {log.step === "token" && log.content && isRunning && (
                      <div className="py-2 text-sm text-gray-100 font-sans leading-relaxed">
                        <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
                          {log.content}
                        </ReactMarkdown>
                      </div>
                    )}

                    {/* 4. Test Complete */}
                    {log.step === "test_complete" && (
                      <div className="pt-3 pb-2 space-y-3">
                        <div className="flex items-center justify-between pb-2 border-b border-[#262626]">
                          <div className="flex items-center gap-2">
                            <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
                            <span className="font-semibold text-xs text-gray-200">
                              {log.test_name || log.test} completed ({log.duration_sec}s &bull; {log.tool_count} tools)
                            </span>
                          </div>

                          {log.final_output && (
                            <button
                              type="button"
                              onClick={() => copyToClipboard(log.final_output || "", log.id)}
                              className="flex items-center gap-1.5 text-xs text-gray-400 hover:text-white px-2.5 py-1 rounded bg-[#181818] border border-[#2e2e2e] cursor-pointer transition-all shadow-sm"
                            >
                              {copiedId === log.id ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                              <span>{copiedId === log.id ? "Copied!" : "Copy Response"}</span>
                            </button>
                          )}
                        </div>

                        {/* Generated Documents Pills */}
                        {log.generated_files && log.generated_files.length > 0 && (
                          <div className="flex flex-wrap gap-2 py-1">
                            {log.generated_files.map((gf: any, idx: number) => (
                              <div key={idx} className="px-2.5 py-1 rounded-lg bg-[#141414] border border-[#262626] flex items-center gap-2 text-xs">
                                {getToolIcon(gf.name)}
                                <span className="font-medium text-gray-200">{gf.name}</span>
                                <span className="text-[10px] text-gray-500 font-mono">
                                  ({(gf.size_bytes / 1024).toFixed(1)} KB)
                                </span>
                              </div>
                            ))}
                          </div>
                        )}

                        {/* Pure Final Output */}
                        {log.final_output ? (
                          <div className="py-2 text-gray-100 font-sans text-sm leading-relaxed prose prose-invert max-w-none">
                            <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
                              {log.final_output}
                            </ReactMarkdown>
                          </div>
                        ) : null}
                      </div>
                    )}

                    {/* 5. Test Error */}
                    {log.step === "test_error" && (
                      <div className="rounded-xl border border-red-500/30 bg-red-950/20 p-3 text-xs text-red-300 flex items-start gap-2.5">
                        <XCircle className="w-4 h-4 text-red-400 shrink-0 mt-0.5" />
                        <div>
                          <span className="font-bold text-red-200">Error during test execution</span>
                          <p className="mt-1 font-mono text-[11px] text-red-300">{log.error || log.message}</p>
                        </div>
                      </div>
                    )}
                  </div>
                );
              })
            )}
            <div ref={logsEndRef} />
          </div>
        </div>
      )}

      {/* Tab 2: Rendered Markdown Report Reader */}
      {activeTab === "report" && (
        <MarkdownReportReader
          content={currentReport}
          reportName={currentReportName || "Smoke Test Execution Report"}
          onDownload={downloadMarkdown}
        />
      )}

      {/* Tab 3: History Reports */}
      {activeTab === "history" && (
        <div className="rounded-xl border border-[#262626] bg-[#141414] overflow-hidden">
          <div className="px-5 py-3 border-b border-[#262626] bg-[#181818] flex items-center justify-between">
            <span className="font-semibold text-sm text-white">Generated Reports in File System (`evals/agent_smoke_tests/outputs/`)</span>
            <button
              onClick={fetchHistoryReports}
              className="p-1.5 hover:bg-[#222] rounded border border-[#333] text-gray-400 hover:text-white transition-all cursor-pointer"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loadingHistory ? "animate-spin" : ""}`} />
            </button>
          </div>

          <div className="divide-y divide-[#262626]">
            {historyReports.length === 0 ? (
              <div className="py-12 text-center text-gray-500 text-sm">
                No reports saved in <code>evals/agent_smoke_tests/outputs/</code>.
              </div>
            ) : (
              historyReports.map((item) => {
                const isSingle = item.filename.startsWith("report_test_");
                return (
                  <div key={item.filename} className="p-4 flex items-center justify-between hover:bg-[#1a1a1a] transition-all">
                    <div className="flex items-center gap-3">
                      <span className={`p-2 rounded-lg border ${isSingle ? "bg-purple-500/10 text-purple-400 border-purple-500/20" : "bg-blue-500/10 text-blue-400 border-blue-500/20"
                        }`}>
                        <FileText className="w-4 h-4" />
                      </span>
                      <div>
                        <div className="flex items-center gap-2">
                          <h4 className="text-sm font-semibold text-white">{item.filename}</h4>
                          <span className={`text-[10px] px-1.5 py-0.2 rounded font-mono font-semibold ${isSingle ? "bg-purple-950 text-purple-300 border border-purple-800/40" : "bg-blue-950 text-blue-300 border border-blue-800/40"
                            }`}>
                            {isSingle ? "Single Test" : "Full Suite"}
                          </span>
                        </div>
                        <p className="text-xs text-gray-400 mt-0.5">
                          {new Date(item.modified_at).toLocaleString()} &bull; {(item.size_bytes / 1024).toFixed(1)} KB
                        </p>
                      </div>
                    </div>

                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => loadReportContent(item.filename)}
                        className="px-3 py-1.5 rounded-lg text-xs font-medium bg-blue-600/10 hover:bg-blue-600/20 text-blue-400 border border-blue-500/30 transition-all cursor-pointer"
                      >
                        View Report
                      </button>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>
      )}

      {/* Detailed Result Modal Drawer */}
      {selectedTestModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4 animate-in fade-in duration-200">
          <div className="bg-[#141414] border border-[#2e2e2e] rounded-2xl w-full max-w-5xl h-[88vh] max-h-[88vh] flex flex-col shadow-2xl overflow-hidden">
            {/* Modal Header */}
            <div className="shrink-0 flex items-center justify-between px-6 py-4 border-b border-[#262626] bg-[#181818]">
              <div className="flex items-center gap-3">
                <span className="p-2 rounded-lg bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                  <CheckCircle2 className="w-5 h-5" />
                </span>
                <div>
                  <h3 className="text-base font-bold text-white">{selectedTestModal.name}</h3>
                  <p className="text-xs text-gray-400 flex items-center gap-2 flex-wrap mt-0.5">
                    <span>ID: <code className="text-emerald-400 font-mono">{selectedTestModal.id}</code></span>
                    <span>&bull;</span>
                    <span>Profilo: <code className="text-blue-400 bg-blue-950/40 px-1 py-0.5 rounded text-[11px] border border-blue-800/40">{selectedTestModal.assistant || selectedProfile}</code></span>
                    <span>&bull;</span>
                    <span>Duration: {selectedTestModal.duration_sec}s</span>
                    <span>&bull;</span>
                    <span>Tools used: {selectedTestModal.tool_count}</span>
                  </p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setSelectedTestModal(null)}
                className="p-1.5 hover:bg-[#262626] rounded-lg text-gray-400 hover:text-white transition-colors cursor-pointer"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Modal Sub-Tabs Bar */}
            <div className="shrink-0 flex items-center gap-1.5 px-6 bg-[#111] border-b border-[#262626] text-xs font-semibold overflow-x-auto min-h-[46px] select-none">
              <button
                type="button"
                onClick={() => setModalActiveTab("final")}
                className={`px-3.5 py-2.5 border-b-2 cursor-pointer transition-all shrink-0 whitespace-nowrap text-xs font-semibold flex items-center gap-1.5 ${modalActiveTab === "final"
                  ? "border-emerald-500 text-emerald-400 bg-emerald-500/5"
                  : "border-transparent text-gray-400 hover:text-gray-200 hover:bg-white/[0.02]"
                  }`}
              >
                <span>📝 Final Response Deliverable</span>
              </button>
              {selectedTestModal.score !== undefined && (
                <button
                  type="button"
                  onClick={() => setModalActiveTab("eval")}
                  className={`px-3.5 py-2.5 border-b-2 cursor-pointer transition-all shrink-0 whitespace-nowrap text-xs font-semibold flex items-center gap-1.5 ${modalActiveTab === "eval"
                    ? "border-amber-500 text-amber-400 bg-amber-500/5"
                    : "border-transparent text-gray-400 hover:text-gray-200 hover:bg-white/[0.02]"
                    }`}
                >
                  <span>🎯 Evaluation & Criteria</span>
                  <span className="px-1.5 py-0.5 rounded text-[10px] font-mono font-bold bg-amber-500/20 text-amber-300">
                    {selectedTestModal.score}/100
                  </span>
                </button>
              )}
              {selectedTestModal.charts && selectedTestModal.charts.length > 0 && (
                <button
                  type="button"
                  onClick={() => setModalActiveTab("charts")}
                  className={`px-3.5 py-2.5 border-b-2 cursor-pointer transition-all shrink-0 whitespace-nowrap text-xs font-semibold flex items-center gap-1.5 ${modalActiveTab === "charts"
                    ? "border-emerald-500 text-emerald-400 bg-emerald-500/5"
                    : "border-transparent text-gray-400 hover:text-gray-200 hover:bg-white/[0.02]"
                    }`}
                >
                  <span>📊 Rendered Charts</span>
                  <span className="px-1.5 py-0.2 rounded-full bg-emerald-950 text-emerald-400 text-[10px] font-mono border border-emerald-800/40">
                    {selectedTestModal.charts.length}
                  </span>
                </button>
              )}
              {selectedTestModal.generated_files && selectedTestModal.generated_files.length > 0 && (
                <button
                  type="button"
                  onClick={() => setModalActiveTab("files")}
                  className={`px-3.5 py-2.5 border-b-2 cursor-pointer transition-all shrink-0 whitespace-nowrap text-xs font-semibold flex items-center gap-1.5 ${modalActiveTab === "files"
                    ? "border-emerald-500 text-emerald-400 bg-emerald-500/5"
                    : "border-transparent text-gray-400 hover:text-gray-200 hover:bg-white/[0.02]"
                    }`}
                >
                  <span>📁 Generated Files</span>
                  <span className="px-1.5 py-0.2 rounded-full bg-emerald-950 text-emerald-400 text-[10px] font-mono border border-emerald-800/40">
                    {selectedTestModal.generated_files.length}
                  </span>
                </button>
              )}
              {selectedTestModal.timeline && selectedTestModal.timeline.length > 0 && (
                <button
                  type="button"
                  onClick={() => setModalActiveTab("timeline")}
                  className={`px-3.5 py-2.5 border-b-2 cursor-pointer transition-all shrink-0 whitespace-nowrap text-xs font-semibold flex items-center gap-1.5 ${modalActiveTab === "timeline"
                    ? "border-emerald-500 text-emerald-400 bg-emerald-500/5"
                    : "border-transparent text-gray-400 hover:text-gray-200 hover:bg-white/[0.02]"
                    }`}
                >
                  <span>⏱️ Execution Timeline</span>
                </button>
              )}
              {selectedTestModal.reasoning && (
                <button
                  type="button"
                  onClick={() => setModalActiveTab("reasoning")}
                  className={`px-3.5 py-2.5 border-b-2 cursor-pointer transition-all shrink-0 whitespace-nowrap text-xs font-semibold flex items-center gap-1.5 ${modalActiveTab === "reasoning"
                    ? "border-emerald-500 text-emerald-400 bg-emerald-500/5"
                    : "border-transparent text-gray-400 hover:text-gray-200 hover:bg-white/[0.02]"
                    }`}
                >
                  <span>🧠 Reasoning</span>
                </button>
              )}
            </div>

            {/* Modal Body */}
            <div className="flex-1 overflow-y-auto p-6 font-sans min-h-0">
              {/* Tab 0: Evaluation & Criteria */}
              {modalActiveTab === "eval" && (
                <div className="space-y-5">
                  {/* Score banner card */}
                  <div className="p-4 rounded-xl bg-black/60 border border-[#262626] flex flex-col md:flex-row md:items-center justify-between gap-4">
                    <div className="space-y-1">
                      <div className="flex items-center gap-2">
                        <span className="text-xl font-bold text-white">
                          Test Score: <span className="text-amber-400">{selectedTestModal.score ?? 0}</span> / {selectedTestModal.max_score ?? 100}
                        </span>
                        {selectedTestModal.rating && (
                          <span className="px-2 py-0.5 rounded text-xs font-bold bg-amber-500/20 text-amber-300 border border-amber-500/30">
                            Grade {selectedTestModal.rating}
                          </span>
                        )}
                        <span className={`px-2 py-0.5 rounded text-xs font-semibold ${selectedTestModal.passed
                          ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/30"
                          : "bg-red-500/20 text-red-300 border border-red-500/30"
                          }`}>
                          {selectedTestModal.passed ? "✅ Passed (Threshold ≥ 60)" : "❌ Failed"}
                        </span>
                      </div>
                      <p className="text-xs text-gray-400">
                        {selectedTestModal.eval_summary || "Deterministic 10-criteria evaluation (zero LLM-as-a-judge variance)."}
                      </p>
                    </div>

                    {/* Progress Bar */}
                    <div className="w-full md:w-64 space-y-1.5">
                      <div className="flex justify-between text-[11px] text-gray-400 font-mono">
                        <span>Criteria Adherence</span>
                        <span className="font-bold text-white">{selectedTestModal.score ?? 0}%</span>
                      </div>
                      <div className="w-full bg-[#202020] rounded-full h-2.5 overflow-hidden border border-[#333]">
                        <div
                          className={`h-full transition-all duration-500 rounded-full ${(selectedTestModal.score ?? 0) >= 80
                            ? "bg-gradient-to-r from-emerald-500 to-teal-400"
                            : (selectedTestModal.score ?? 0) >= 60
                              ? "bg-gradient-to-r from-amber-500 to-yellow-400"
                              : "bg-gradient-to-r from-red-500 to-rose-400"
                            }`}
                          style={{ width: `${Math.min(100, Math.max(0, selectedTestModal.score ?? 0))}%` }}
                        />
                      </div>
                    </div>
                  </div>

                  {/* Criteria Checklist Table */}
                  <div className="border border-[#262626] rounded-xl overflow-hidden bg-black/40">
                    <div className="px-4 py-2.5 bg-[#181818] border-b border-[#262626] flex items-center justify-between">
                      <span className="text-xs font-semibold text-gray-200">
                        Verification Micro-Criteria Breakdown (10/10)
                      </span>
                      <span className="text-[11px] text-gray-400">
                        {(Array.isArray(selectedTestModal.eval_criteria) ? selectedTestModal.eval_criteria : []).filter((c: any) => c?.passed).length} / {(Array.isArray(selectedTestModal.eval_criteria) ? selectedTestModal.eval_criteria : []).length || 10} Criteria Satisfied
                      </span>
                    </div>

                    <div className="divide-y divide-[#222]">
                      {Array.isArray(selectedTestModal.eval_criteria) && selectedTestModal.eval_criteria.length > 0 ? (
                        selectedTestModal.eval_criteria.map((crit: any, idx: number) => (
                          <div key={idx} className="p-3.5 flex flex-col sm:flex-row sm:items-center justify-between gap-3 text-xs hover:bg-white/[0.01]">
                            <div className="space-y-1 flex-1">
                              <div className="flex items-center gap-2">
                                <span className="font-mono text-gray-500 text-[11px]">#{idx + 1}</span>
                                <span className="font-semibold text-white">{crit.name}</span>
                                <span className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-[#202020] text-gray-400 border border-[#303030]">
                                  {crit.category}
                                </span>
                              </div>
                              {crit.description && (
                                <p className="text-[11px] text-gray-400 pl-5">
                                  {crit.description}
                                </p>
                              )}
                              {crit.details && (
                                <p className="text-[11px] text-gray-400 pl-5 font-mono">
                                  🔍 {crit.details}
                                </p>
                              )}
                            </div>

                            <div className="flex items-center gap-3 sm:self-center pl-5 sm:pl-0">
                              <span className="font-mono text-[11px] font-semibold text-gray-300">
                                {crit.points !== undefined
                                  ? crit.points
                                  : crit.points_awarded !== undefined
                                    ? crit.points_awarded
                                    : crit.passed
                                      ? (crit.max_points ?? crit.points_max ?? 10)
                                      : 0}{" "}
                                / {crit.max_points ?? crit.points_max ?? 10} pt
                              </span>
                              <span className={`px-2.5 py-1 rounded-md text-xs font-bold flex items-center gap-1 ${crit.passed
                                ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/30"
                                : "bg-red-500/10 text-red-400 border border-red-500/30"
                                }`}>
                                {crit.passed ? <CheckCircle2 className="w-3.5 h-3.5" /> : <XCircle className="w-3.5 h-3.5" />}
                                <span>{crit.passed ? "PASSED" : "FAILED"}</span>
                              </span>
                            </div>
                          </div>
                        ))
                      ) : (
                        <div className="p-6 text-center text-xs text-gray-500">
                          No criteria breakdown available for this test.
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              )}
              {/* Tab 1: Final Output */}
              {modalActiveTab === "final" && (
                <div className="space-y-4">
                  <div className="flex items-center justify-between pb-2 border-b border-[#262626]">
                    <span className="text-xs font-semibold text-emerald-400">
                      Final Deliverable & Response Delivered to User
                    </span>
                    {selectedTestModal.final_output && (
                      <button
                        type="button"
                        onClick={() => copyToClipboard(selectedTestModal.final_output || "", "modal_final")}
                        className="flex items-center gap-1.5 text-xs text-gray-300 hover:text-white px-2.5 py-1 rounded-md bg-[#222] border border-[#333] cursor-pointer"
                      >
                        {copiedId === "modal_final" ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}
                        <span>{copiedId === "modal_final" ? "Copied!" : "Copy Text"}</span>
                      </button>
                    )}
                  </div>

                  <div className="p-5 rounded-xl bg-black/60 border border-[#262626] text-gray-200 text-xs leading-relaxed prose prose-invert max-w-none overflow-x-auto">
                    {selectedTestModal.final_output ? (
                      <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
                        {selectedTestModal.final_output}
                      </ReactMarkdown>
                    ) : (
                      <p className="text-gray-500 italic">No final text output recorded for this test.</p>
                    )}
                  </div>
                </div>
              )}

              {/* Tab 2: Charts */}
              {modalActiveTab === "charts" && (
                <div className="space-y-4">
                  <h4 className="text-xs font-semibold text-emerald-400">
                    Interactive Charts Generated by Agent (`render_chart`)
                  </h4>
                  <SessionCharts charts={selectedTestModal.charts || []} />
                </div>
              )}

              {/* Tab 3: Generated Files */}
              {modalActiveTab === "files" && (
                <div className="space-y-4">
                  <div className="flex items-center justify-between pb-1 border-b border-[#262626]">
                    <h4 className="text-xs font-semibold text-emerald-400">
                      Files & Documents Created in Session Sandbox ({selectedTestModal.generated_files?.length || 0})
                    </h4>
                  </div>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5 max-h-[480px] overflow-y-auto pr-1">
                    {selectedTestModal.generated_files?.map((gf: any, idx: number) => {
                      const token = getStoredToken();
                      const downloadUrl = `${apiBase()}/admin/diagnostics/file?path=${encodeURIComponent(gf.name)}&download=1&access_token=${token || ""}`;
                      return (
                        <div key={idx} className="p-2.5 rounded-xl bg-black/60 border border-[#2a2a2a] hover:border-[#383838] flex items-center justify-between text-xs transition-colors">
                          <div className="flex items-center gap-2.5 truncate min-w-0 pr-2">
                            {getToolIcon(gf.name)}
                            <div className="truncate min-w-0">
                              <h5 className="font-semibold text-white truncate text-xs">{gf.name}</h5>
                              <p className="text-[10px] text-gray-500 font-mono truncate">
                                {(gf.size_bytes / 1024).toFixed(1)} KB &bull; {gf.relative_to_outputs || gf.name}
                              </p>
                            </div>
                          </div>
                          <div className="flex items-center gap-1.5 shrink-0">
                            <span className="px-2 py-0.5 rounded text-[10px] bg-emerald-950/80 text-emerald-300 border border-emerald-800/40 font-medium">
                              {gf.category}
                            </span>
                            <a
                              href={downloadUrl}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="p-1 rounded bg-[#1e1e1e] hover:bg-[#2a2a2a] text-gray-400 hover:text-white transition-colors cursor-pointer"
                              title="Download file"
                            >
                              <Download className="w-3.5 h-3.5" />
                            </a>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* Tab 4: Timeline */}
              {modalActiveTab === "timeline" && (
                <div className="space-y-3">
                  <h4 className="text-xs font-semibold text-gray-300 pb-2 border-b border-[#262626]">
                    Chronological Execution Sequence
                  </h4>
                  {selectedTestModal.timeline?.map((ev: any, idx: number) => (
                    <div key={idx} className="p-3 rounded-xl bg-black/50 border border-[#262626] text-xs space-y-2">
                      <div className="flex items-center justify-between">
                        <span className="font-semibold text-gray-200">
                          Step {idx + 1} — {ev.type === "reasoning" ? "🧠 Reasoning" : `🛠️ Tool: ${ev.name}`}
                        </span>
                        <span className="text-[10px] text-gray-500 font-mono">
                          {new Date(ev.timestamp).toLocaleTimeString()}
                        </span>
                      </div>
                      {ev.content && (
                        <div className="p-2.5 rounded bg-white/[0.02] border border-white/[0.05] text-gray-400 text-xs whitespace-pre-wrap font-sans leading-relaxed">
                          {ev.content}
                        </div>
                      )}
                      {ev.parameters && (
                        <pre className="p-2.5 rounded bg-black/60 border border-[#222] text-amber-200/90 text-[11px] overflow-x-auto font-mono">
                          {JSON.stringify(ev.parameters, null, 2)}
                        </pre>
                      )}
                      {ev.result && (
                        <pre className="p-2.5 rounded bg-black/60 border border-[#222] text-gray-300 text-[11px] overflow-x-auto font-mono">
                          {typeof ev.result === "object" ? JSON.stringify(ev.result, null, 2) : String(ev.result)}
                        </pre>
                      )}
                    </div>
                  ))}
                </div>
              )}

              {/* Tab 5: Reasoning */}
              {modalActiveTab === "reasoning" && (
                <div className="space-y-4">
                  <h4 className="text-xs font-semibold text-gray-300 flex items-center gap-1.5 pb-2 border-b border-[#262626]">
                    <Brain className="w-4 h-4 text-gray-400" /> Reasoning Chain
                  </h4>
                  <div className="p-4 rounded-xl bg-white/[0.02] border border-white/[0.05] text-gray-400 text-xs whitespace-pre-wrap leading-relaxed max-h-[400px] overflow-y-auto font-sans">
                    {selectedTestModal.reasoning}
                  </div>
                </div>
              )}
            </div>

            {/* Modal Footer */}
            <div className="shrink-0 flex items-center justify-between px-6 py-3 border-t border-[#262626] bg-[#181818]">
              {selectedTestModal.single_report_filename ? (
                <span className="text-[11px] text-gray-400 font-mono">
                  Report File: <code>outputs/{selectedTestModal.single_report_filename}</code>
                </span>
              ) : (
                <div />
              )}
              <button
                type="button"
                onClick={() => setSelectedTestModal(null)}
                className="px-4 py-2 rounded-lg text-xs font-semibold bg-[#262626] hover:bg-[#333] text-white transition-colors cursor-pointer"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
