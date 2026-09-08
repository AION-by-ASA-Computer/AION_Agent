"use client";

/* ==============================================================================
 * METRICS SCOPE & TARGET AUDIENCE REFERENCE:
 * 📊 BOTH (Grafana Dashboard + Admin UI):
 *    - Token Generati (Input/Prompt vs Output/Completion)
 *    - Durata Turni di Esecuzione (Media + Ultimo Turno + P95 Latency)
 *    - Totale Invocazioni Tool & Tasso di Successo %
 *    - Totale Turni Completati & Fallimenti
 *
 * 📈 GRAFANA EXCLUSIVE (Available in Grafana Dashboards):
 *    - Latenza esecuzione singoli tool (Histogram buckets)
 *    - Session workspace disk cache footprint (aion_session_cache_size_bytes)
 *    - Health binary gauges MCP server (aion_mcp_server_healthy: 1=up, 0=down)
 *    - Worker pool size (aion_mcp_pool_workers)
 *
 * 💻 ADMIN UI EXCLUSIVE (Calculated dynamically or via API):
 *    - Ripartizione metriche per singolo profilo agente (ProfileMetricSummary)
 *    - Tool ed MCP chiamati nell'Ultimo Turno (Last turn tool calls snapshot)
 *    - Diagnostica dettagliata chiamate MCP fallite (MCPCallError list)
 *    - Grafico andamento utilizzo tool nel tempo (Time series timeline chart)
 * ============================================================================== */

import React, { useEffect, useState } from "react";
import {
  BarChart3,
  RefreshCw,
  Activity,
  Cpu,
  Layers,
  Sparkles,
  Zap,
  TrendingUp,
  Clock,
  AlertTriangle,
  CheckCircle2,
  Filter,
  Wrench,
  ArrowUpRight,
  ArrowDownLeft,
  Bot,
  ListFilter,
  Maximize2,
  Minimize2,
  Search,
  Brain,
  User,
  Users,
  ChevronDown,
  ChevronRight,
  Sliders,
  Radio,
  Server,
  Network,
  Save,
  X,
  Eye,
  EyeOff,
  ShieldCheck,
  Check,
  Globe,
  HelpCircle,
  Loader2,
  Play,
  Info,
  AlertCircle,
} from "lucide-react";
import { apiFetch } from "@/lib/api/headers";
import { apiBase } from "@/lib/api";

interface ProfileItem {
  name: string;
  slug?: string;
  description?: string;
}

interface UserItem {
  id: string;
  tenant_id?: string;
  identifier?: string;
  display_name?: string;
}

interface ToolMetricSummary {
  tool_name: string;
  mcp_server: string;
  call_count: number;
  error_count: number;
  success_rate: number;
  avg_duration_seconds: number;
}

interface LastTurnToolCall {
  tool_name: string;
  mcp_server: string;
  status: string;
  count: number;
}

interface ToolUsageTimeSeriesPoint {
  timestamp: string;
  calls: number;
}

interface TimeSeriesDataPoint {
  timestamp: string;
  value: number;
}

interface ProfileMetricSummary {
  profile: string;
  total_tokens: number;
  prompt_tokens: number;
  completion_tokens: number;
  reasoning_tokens: number;
  total_turns: number;
  total_tool_calls: number;
  tool_success_rate: number;
  avg_turn_duration_seconds: number;
}

interface UserToolCallSummary {
  tool_name: string;
  mcp_server: string;
  call_count: number;
  error_count: number;
}

interface UserProfileUsageSummary {
  profile: string;
  total_turns: number;
  prompt_tokens?: number;
  completion_tokens?: number;
  reasoning_tokens?: number;
  total_tokens: number;
  total_tool_calls: number;
  usage_frequency_percent: number;
  tools_breakdown?: UserToolCallSummary[];
}

interface UserMetricSummary {
  user_id: string;
  total_tokens: number;
  prompt_tokens: number;
  completion_tokens: number;
  reasoning_tokens: number;
  total_turns: number;
  total_tool_calls: number;
  tool_success_rate: number;
  avg_turn_duration_seconds: number;
  profile_breakdown: UserProfileUsageSummary[];
}

interface MCPCallError {
  timestamp?: string;
  tool_name: string;
  mcp_server: string;
  profile: string;
  status: string;
  error_count: number;
  error_message?: string;
}

interface MetricsOverviewData {
  prometheus_connected: boolean;
  prometheus_url: string;
  profile?: string;
  user_id?: string;
  time_range: string;
  total_tokens: number;
  prompt_tokens: number; // Input tokens
  completion_tokens: number; // Output tokens
  reasoning_tokens: number;
  last_turn_prompt_tokens: number;
  last_turn_completion_tokens: number;
  last_turn_reasoning_tokens: number;
  total_turns: number;
  avg_turn_duration_seconds: number;
  p95_turn_duration_seconds: number;
  last_turn_duration_seconds: number;
  total_tool_calls: number;
  tool_success_rate: number;
  total_failures: number;
  failure_breakdown: Record<string, number>;
  tool_metrics: ToolMetricSummary[];
  last_turn_tool_calls: LastTurnToolCall[];
  last_turn_tools_by_profile: Record<string, LastTurnToolCall[]>;
  tool_usage_series: ToolUsageTimeSeriesPoint[];
  profile_metrics: ProfileMetricSummary[];
  user_metrics?: UserMetricSummary[];
  mcp_call_errors: MCPCallError[];
  token_usage_by_model: Record<string, Record<string, number>>;
  tokens_series?: TimeSeriesDataPoint[];
  turn_duration_series?: TimeSeriesDataPoint[];
  turns_series?: TimeSeriesDataPoint[];
  tool_calls_series?: TimeSeriesDataPoint[];
}

interface SparklineProps {
  data?: TimeSeriesDataPoint[];
  color?: string;
  height?: number;
  timeRange?: string;
  formatVal?: (v: number) => string;
}

const formatTimestamp = (ts: string | undefined, timeRange: string = "1h") => {
  if (!ts) return "";
  const d = new Date(ts);
  if (!isNaN(d.getTime())) {
    if (timeRange === "7d" || timeRange === "30d" || timeRange === "all") {
      return d.toLocaleDateString(undefined, {
        day: "2-digit",
        month: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      });
    }
    return d.toLocaleTimeString(undefined, {
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    });
  }
  return ts;
};

const SparklineArea: React.FC<SparklineProps> = ({
  data = [],
  color = "#a855f7",
  height = 38,
  timeRange = "1h",
  formatVal = (v) => (v >= 1000 ? `${(v / 1000).toFixed(1)}k` : `${v}`),
}) => {
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);

  if (!data || data.length === 0) {
    return <div style={{ height }} className="w-full bg-white/5 rounded-lg animate-pulse" />;
  }

  const values = data.map((d) => d.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;

  const width = 280;
  const padding = 4;
  const graphHeight = height - padding * 2;

  const points = data.map((d, i) => {
    const x = padding + (i / (data.length - 1 || 1)) * (width - padding * 2);
    const y = height - padding - ((d.value - min) / range) * graphHeight;
    return { x, y, ...d };
  });

  let pathD = `M ${points[0].x} ${points[0].y}`;
  for (let i = 0; i < points.length - 1; i++) {
    const curr = points[i];
    const next = points[i + 1];
    const mx = (curr.x + next.x) / 2;
    pathD += ` C ${mx} ${curr.y}, ${mx} ${next.y}, ${next.x} ${next.y}`;
  }

  const areaD = `${pathD} L ${points[points.length - 1].x} ${height} L ${points[0].x} ${height} Z`;
  const gradId = `grad-${color.replace("#", "")}`;
  const activePoint = hoverIdx !== null && points[hoverIdx] ? points[hoverIdx] : null;

  return (
    <div className="relative w-full group mt-2" style={{ height }}>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="w-full h-full overflow-visible"
        onMouseLeave={() => setHoverIdx(null)}
      >
        <defs>
          <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity="0.4" />
            <stop offset="100%" stopColor={color} stopOpacity="0.0" />
          </linearGradient>
        </defs>

        <path d={areaD} fill={`url(#${gradId})`} />
        <path d={pathD} fill="none" stroke={color} strokeWidth="1.8" strokeLinecap="round" />

        {points.map((p, i) => (
          <rect
            key={i}
            x={p.x - width / (data.length * 2)}
            y={0}
            width={width / data.length}
            height={height}
            fill="transparent"
            className="cursor-pointer"
            onMouseEnter={() => setHoverIdx(i)}
          />
        ))}

        {activePoint && (
          <g>
            <line
              x1={activePoint.x}
              y1={0}
              x2={activePoint.x}
              y2={height}
              stroke={color}
              strokeWidth="1"
              strokeDasharray="2 2"
              opacity="0.6"
            />
            <circle
              cx={activePoint.x}
              cy={activePoint.y}
              r="3"
              fill="#0e0e12"
              stroke={color}
              strokeWidth="2"
            />
          </g>
        )}
      </svg>

      {activePoint && (
        <div
          className="absolute -top-8 z-20 -translate-x-1/2 bg-[#181824] border border-white/20 text-white text-[10px] font-mono font-bold px-2 py-0.5 rounded shadow-xl pointer-events-none whitespace-nowrap"
          style={{ left: `${(activePoint.x / width) * 100}%` }}
        >
          <span className="text-slate-400 font-sans mr-1.5">{formatTimestamp(activePoint.timestamp, timeRange)}:</span>
          <span style={{ color }}>{formatVal(activePoint.value)}</span>
        </div>
      )}
    </div>
  );
};

const MiniBarChart: React.FC<SparklineProps> = ({
  data = [],
  color = "#f59e0b",
  height = 38,
  timeRange = "1h",
  formatVal = (v) => `${v}`,
}) => {
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);

  if (!data || data.length === 0) {
    return <div style={{ height }} className="w-full bg-white/5 rounded-lg animate-pulse" />;
  }

  const values = data.map((d) => d.value);
  const max = Math.max(...values, 1);

  const width = 280;
  const gap = 2;
  const barWidth = Math.max(2, (width - gap * (data.length - 1)) / data.length);

  const activePoint = hoverIdx !== null && data[hoverIdx] ? data[hoverIdx] : null;
  const activeX = hoverIdx !== null ? hoverIdx * (barWidth + gap) + barWidth / 2 : 0;

  return (
    <div className="relative w-full group mt-2" style={{ height }}>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="w-full h-full overflow-visible"
        onMouseLeave={() => setHoverIdx(null)}
      >
        {data.map((d, i) => {
          const barHeight = Math.max(2, (d.value / max) * (height - 4));
          const x = i * (barWidth + gap);
          const y = height - barHeight;
          const isHovered = hoverIdx === i;

          return (
            <rect
              key={i}
              x={x}
              y={y}
              width={barWidth}
              height={barHeight}
              rx={1.5}
              fill={isHovered ? "#ffffff" : color}
              opacity={isHovered ? 1 : 0.75}
              className="transition-all cursor-pointer"
              onMouseEnter={() => setHoverIdx(i)}
            />
          );
        })}
      </svg>

      {activePoint && (
        <div
          className="absolute -top-8 z-20 -translate-x-1/2 bg-[#181824] border border-white/20 text-white text-[10px] font-mono font-bold px-2 py-0.5 rounded shadow-xl pointer-events-none whitespace-nowrap"
          style={{ left: `${(activeX / width) * 100}%` }}
        >
          <span className="text-slate-400 font-sans mr-1.5">{formatTimestamp(activePoint.timestamp, timeRange)}:</span>
          <span style={{ color }}>{formatVal(activePoint.value)}</span>
        </div>
      )}
    </div>
  );
};

export default function MetricsEvaluationPage() {
  const [profiles, setProfiles] = useState<ProfileItem[]>([]);
  const [selectedProfile, setSelectedProfile] = useState<string>("");
  const [users, setUsers] = useState<UserItem[]>([]);
  const [selectedUser, setSelectedUser] = useState<string>("");
  const [expandedUsers, setExpandedUsers] = useState<Record<string, boolean>>({});
  const [timeRange, setTimeRange] = useState<string>("1h");
  const [autoRefresh, setAutoRefresh] = useState<boolean>(true);
  const [metrics, setMetrics] = useState<MetricsOverviewData | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // Controls for MCP errors list & Tool Search
  const [errorLimit, setErrorLimit] = useState<number>(5);
  const [showAllErrors, setShowAllErrors] = useState<boolean>(false);
  const [toolSearch, setToolSearch] = useState<string>("");

  // Observability & Telemetry configuration state
  const [showConfigModal, setShowConfigModal] = useState<boolean>(false);
  const [configTab, setConfigTab] = useState<"prometheus" | "otel" | "opik">("prometheus");
  const [configSettings, setConfigSettings] = useState<Record<string, string>>({});
  const [configLoading, setConfigLoading] = useState<boolean>(false);
  const [configSaving, setConfigSaving] = useState<boolean>(false);
  const [configMessage, setConfigMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);
  const [configProbing, setConfigProbing] = useState<Record<string, boolean>>({});
  const [configProbeResults, setConfigProbeResults] = useState<Record<string, { success: boolean; message: string; latency_ms?: number } | null>>({});
  const [showOpikApiKey, setShowOpikApiKey] = useState<boolean>(false);
  const [restarting, setRestarting] = useState<boolean>(false);

  const handleOpenConfigModal = async () => {
    setConfigMessage(null);
    setConfigProbeResults({});
    setShowConfigModal(true);
    setConfigLoading(true);
    try {
      const res = await apiFetch(`${apiBase()}/admin/settings`);
      if (res.ok) {
        const data = await res.json();
        const cur = data.settings || {};
        setConfigSettings({
          AION_PROMETHEUS_URL: cur.AION_PROMETHEUS_URL || "http://localhost:9090",
          AION_METRICS_ENABLED: cur.AION_METRICS_ENABLED !== undefined ? String(cur.AION_METRICS_ENABLED) : "1",
          AION_METRICS_PATH: cur.AION_METRICS_PATH || "/metrics",
          AION_OTEL_ENABLED: cur.AION_OTEL_ENABLED !== undefined ? String(cur.AION_OTEL_ENABLED) : "0",
          AION_OTEL_ENDPOINT: cur.AION_OTEL_ENDPOINT || "http://localhost:4317",
          AION_OTEL_PROTOCOL: cur.AION_OTEL_PROTOCOL || "grpc",
          AION_OTEL_SERVICE_NAME: cur.AION_OTEL_SERVICE_NAME || "aion-agent",
          AION_OTEL_TRACE_CONTENT: cur.AION_OTEL_TRACE_CONTENT !== undefined ? String(cur.AION_OTEL_TRACE_CONTENT) : "1",
          AION_OTEL_METRIC_EXPORT_INTERVAL: cur.AION_OTEL_METRIC_EXPORT_INTERVAL || "5000",
          AION_OPIK_ENABLED: cur.AION_OPIK_ENABLED !== undefined ? String(cur.AION_OPIK_ENABLED) : "0",
          OPIK_URL_OVERRIDE: cur.OPIK_URL_OVERRIDE || "http://localhost:5173/api",
          OPIK_PROJECT_NAME: cur.OPIK_PROJECT_NAME || "AION-Agent",
          OPIK_API_KEY: cur.OPIK_API_KEY || "",
        });
      }
    } catch (err: any) {
      console.error("Failed to load settings:", err);
      setConfigMessage({ type: "error", text: "Failed to load current configuration from server." });
    } finally {
      setConfigLoading(false);
    }
  };

  const handleProbeConnection = async (target: "prometheus" | "otel" | "opik") => {
    setConfigProbing((prev) => ({ ...prev, [target]: true }));
    setConfigProbeResults((prev) => ({ ...prev, [target]: null }));
    try {
      const payload: any = { target };
      if (target === "prometheus") {
        payload.url = configSettings.AION_PROMETHEUS_URL || "http://localhost:9090";
      } else if (target === "otel") {
        payload.endpoint = configSettings.AION_OTEL_ENDPOINT || "http://localhost:4317";
        payload.protocol = configSettings.AION_OTEL_PROTOCOL || "grpc";
      } else if (target === "opik") {
        payload.url = configSettings.OPIK_URL_OVERRIDE || "http://localhost:5173/api";
        payload.api_key = configSettings.OPIK_API_KEY;
      }

      const res = await apiFetch(`${apiBase()}/admin/metrics/test-connection`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      const data = await res.json();
      setConfigProbeResults((prev) => ({
        ...prev,
        [target]: {
          success: !!data.success,
          message: data.message || (data.success ? "Connected successfully" : "Connection failed"),
          latency_ms: data.latency_ms,
        },
      }));
    } catch (err: any) {
      setConfigProbeResults((prev) => ({
        ...prev,
        [target]: {
          success: false,
          message: err.message || "Network error while probing connection.",
        },
      }));
    } finally {
      setConfigProbing((prev) => ({ ...prev, [target]: false }));
    }
  };

  const pollHealth = async () => {
    const maxAttempts = 30;
    let attempt = 0;

    await new Promise((resolve) => setTimeout(resolve, 2000));

    const interval = setInterval(async () => {
      attempt++;
      try {
        const res = await fetch(`${apiBase()}/health`);
        if (res.ok) {
          const data = await res.json();
          if (data.status === "ok") {
            clearInterval(interval);
            setRestarting(false);
            setConfigMessage({
              type: "success",
              text: "API Container restarted and telemetry configuration applied successfully.",
            });
            fetchMetrics(false);
          }
        }
      } catch (err) {
        console.log("Waiting for backend to come back online...", err);
      }

      if (attempt >= maxAttempts) {
        clearInterval(interval);
        setRestarting(false);
        setConfigMessage({
          type: "error",
          text: "API Container took too long to restart. Please verify manually.",
        });
        fetchMetrics(false);
      }
    }, 1500);
  };

  const handleSaveConfig = async () => {
    setConfigSaving(true);
    setConfigMessage(null);
    try {
      const res = await apiFetch(`${apiBase()}/admin/settings`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ settings: configSettings }),
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `Failed to save settings (${res.status})`);
      }

      const resData = await res.json();
      if (resData.restarting) {
        setRestarting(true);
        setShowConfigModal(false);
        pollHealth();
      } else {
        setConfigMessage({
          type: "success",
          text: resData.message || "Observability settings saved successfully!",
        });
        // Refetch metrics immediately to update Prometheus status badge and data
        fetchMetrics(false);
      }
    } catch (err: any) {
      setConfigMessage({
        type: "error",
        text: err.message || "Failed to update configuration settings.",
      });
    } finally {
      setConfigSaving(false);
    }
  };

  // Fetch available profiles
  useEffect(() => {
    async function loadProfiles() {
      try {
        const res = await apiFetch(`${apiBase()}/admin/profiles`);
        if (res.ok) {
          const data = await res.json();
          if (Array.isArray(data)) {
            setProfiles(data);
          }
        }
      } catch (err) {
        console.error("Failed to load profiles:", err);
      }
    }
    loadProfiles();
  }, []);

  // Fetch available users
  useEffect(() => {
    async function loadUsers() {
      try {
        const res = await apiFetch(`${apiBase()}/admin/users`);
        if (res.ok) {
          const data = await res.json();
          if (data && Array.isArray(data.users)) {
            setUsers(data.users);
          }
        }
      } catch (err) {
        console.error("Failed to load users:", err);
      }
    }
    loadUsers();
  }, []);

  // Fetch metrics data whenever profile, user, or timeRange changes
  const fetchMetrics = async (silent = false) => {
    if (!silent) setLoading(true);
    setError(null);
    try {
      const queryParams = new URLSearchParams();
      if (selectedProfile) queryParams.set("profile", selectedProfile);
      if (selectedUser) queryParams.set("user_id", selectedUser);
      queryParams.set("time_range", timeRange);

      const res = await apiFetch(`${apiBase()}/admin/metrics/overview?${queryParams.toString()}`);
      if (!res.ok) {
        throw new Error(`Failed to load metrics (${res.status})`);
      }
      const data: MetricsOverviewData = await res.json();
      setMetrics(data);
    } catch (err: any) {
      setError(err.message || "Failed to fetch evaluation metrics");
    } finally {
      if (!silent) setLoading(false);
    }
  };

  // Initial fetch and dependency update
  useEffect(() => {
    fetchMetrics(false);
  }, [selectedProfile, selectedUser, timeRange]);

  // Real-time polling every 3 seconds when autoRefresh is active
  useEffect(() => {
    if (!autoRefresh) return;
    const interval = setInterval(() => {
      fetchMetrics(true);
    }, 3000);
    return () => clearInterval(interval);
  }, [autoRefresh, selectedProfile, selectedUser, timeRange]);

  const toggleUserExpand = (userId: string) => {
    setExpandedUsers((prev) => ({
      ...prev,
      [userId]: !prev[userId],
    }));
  };

  const formatNumber = (num: number) => {
    if (num >= 1000000) return `${(num / 1000000).toFixed(1)}M`;
    if (num >= 1000) return `${(num / 1000).toFixed(1)}k`;
    return num.toString();
  };

  // Process filtered list of MCP errors
  const rawErrors = metrics?.mcp_call_errors || [];
  const displayedErrors = showAllErrors ? rawErrors : rawErrors.slice(0, errorLimit);

  // Filtered tool metrics for search box
  const filteredToolMetrics = (metrics?.tool_metrics || []).filter(
    (tool) =>
      tool.tool_name.toLowerCase().includes(toolSearch.toLowerCase()) ||
      tool.mcp_server.toLowerCase().includes(toolSearch.toLowerCase())
  );



  return (
    <div className="flex flex-col min-h-screen bg-[#0a0a0d] text-slate-100 font-sans">
      {/* HEADER BAR */}
      <header className="sticky top-0 z-20 bg-[#0e0e12]/95 backdrop-blur-xl border-b border-white/10 px-6 py-5 shadow-2xl">
        <div className="max-w-[1600px] mx-auto w-full space-y-4">
          {/* TOP ROW: TITLE & PROMETHEUS COMPACT BADGE */}
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
            <div className="flex items-center gap-3.5">
              <div className="p-3 rounded-2xl bg-purple-950/50 border border-purple-500/40 text-purple-400 shadow-xl shadow-purple-950/30">
                <BarChart3 className="w-6 h-6 animate-pulse" />
              </div>
              <div>
                <h1 className="text-2xl font-extrabold tracking-tight text-white flex items-center gap-2">
                  Evaluation & Metrics
                </h1>
                <p className="text-xs sm:text-sm text-slate-400 mt-0.5">
                  Real-time telemetry, LLM token consumption, and AI Agent performance
                </p>
              </div>
            </div>

            {/* TOP RIGHT: PROMETHEUS STATUS & CONFIGURE OBSERVABILITY BUTTON */}
            <div className="flex items-center gap-2.5 flex-wrap">
              {/* PROMETHEUS STATUS BADGE (COMPACT) */}
              {metrics && (
                <div
                  className={`flex items-center gap-2.5 px-3.5 py-1.5 rounded-xl border text-xs font-semibold backdrop-blur-md shrink-0 shadow-lg ${metrics.prometheus_connected
                    ? "bg-emerald-950/30 border-emerald-500/30 text-emerald-300 shadow-emerald-950/20"
                    : "bg-amber-950/30 border-amber-500/30 text-amber-300 shadow-amber-950/20"
                    }`}
                  title={
                    metrics.prometheus_connected
                      ? `Connected to Prometheus (${metrics.prometheus_url})`
                      : "Prometheus Offline — Falling back to in-process local metrics"
                  }
                >
                  <span className="relative flex h-2.5 w-2.5">
                    <span
                      className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 ${metrics.prometheus_connected ? "bg-emerald-400" : "bg-amber-400"
                        }`}
                    />
                    <span
                      className={`relative inline-flex rounded-full h-2.5 w-2.5 ${metrics.prometheus_connected ? "bg-emerald-500" : "bg-amber-500"
                        }`}
                    />
                  </span>
                  <span className="font-bold">
                    {metrics.prometheus_connected ? "Prometheus Online" : "Local Metrics (Fallback)"}
                  </span>
                  <span className="font-mono text-[10px] opacity-75 hidden md:inline">
                    ({metrics.prometheus_url})
                  </span>
                </div>
              )}

              {/* CONFIGURE OBSERVABILITY BUTTON */}
              <button
                onClick={handleOpenConfigModal}
                className="flex items-center gap-2 px-3.5 py-1.5 rounded-xl border border-purple-500/40 bg-purple-950/40 hover:bg-purple-900/60 text-purple-200 hover:text-white text-xs font-bold transition-all shadow-lg shadow-purple-950/30 cursor-pointer group"
                title="Configure Prometheus, OpenTelemetry (OTel) & Opik Telemetry"
              >
                <Sliders className="w-3.5 h-3.5 text-purple-400 group-hover:text-purple-300 transition-transform group-hover:rotate-45" />
                <span>Configure Observability</span>
              </button>
            </div>
          </div>

          {/* SECOND ROW: CONTROLS TOOLBAR (USER & PROFILE SELECTOR, TIME RANGE, REALTIME & MANUAL REFRESH) */}
          <div className="flex items-center justify-between gap-3 flex-wrap pt-3 border-t border-white/5">
            {/* LEFT CONTROLS: USER & PROFILE SELECTORS & TIME RANGE BUTTONS */}
            <div className="flex items-center gap-3 flex-wrap">
              {/* USER SELECTOR DROPDOWN */}
              <div className="flex items-center gap-2 bg-[#16161d] border border-white/10 rounded-xl px-3 py-1.5 shadow-inner">
                <User className="w-3.5 h-3.5 text-indigo-400" />
                <select
                  value={selectedUser}
                  onChange={(e) => setSelectedUser(e.target.value)}
                  className="bg-transparent text-xs text-slate-200 font-medium outline-none cursor-pointer pr-2"
                >
                  <option value="" className="bg-[#16161d] text-slate-300">
                    All Users
                  </option>
                  {users.map((u) => {
                    const val = u.identifier || u.id || "";
                    const label = u.identifier || u.display_name || u.id;
                    return (
                      <option key={val} value={val} className="bg-[#16161d] text-slate-300">
                        👤 {label}
                      </option>
                    );
                  })}
                </select>
              </div>

              {/* PROFILE SELECTOR DROPDOWN */}
              <div className="flex items-center gap-2 bg-[#16161d] border border-white/10 rounded-xl px-3 py-1.5 shadow-inner">
                <Filter className="w-3.5 h-3.5 text-purple-400" />
                <select
                  value={selectedProfile}
                  onChange={(e) => setSelectedProfile(e.target.value)}
                  className="bg-transparent text-xs text-slate-200 font-medium outline-none cursor-pointer pr-2"
                >
                  <option value="" className="bg-[#16161d] text-slate-300">
                    All Profiles
                  </option>
                  {profiles.map((p) => {
                    const val = p.slug || p.name;
                    return (
                      <option key={val} value={val} className="bg-[#16161d] text-slate-300">
                        🤖 {p.name}
                      </option>
                    );
                  })}
                </select>
              </div>

              {/* TIME RANGE SELECTOR BUTTONS */}
              <div className="flex items-center bg-[#16161d] border border-white/10 rounded-xl p-1">
                {[
                  { id: "1h", label: "1h" },
                  { id: "6h", label: "6h" },
                  { id: "24h", label: "24h" },
                  { id: "7d", label: "7d" },
                  { id: "30d", label: "30d" },
                  { id: "all", label: "All" },
                ].map((range) => (
                  <button
                    key={range.id}
                    onClick={() => setTimeRange(range.id)}
                    className={`px-3 py-1 rounded-lg text-xs font-bold transition-all cursor-pointer ${timeRange === range.id
                      ? "bg-purple-600 text-white shadow-md shadow-purple-900/30"
                      : "text-slate-400 hover:text-white hover:bg-white/5"
                      }`}
                  >
                    {range.label}
                  </button>
                ))}
              </div>
            </div>

            {/* RIGHT CONTROLS: REALTIME AUTO-REFRESH & REFRESH BUTTON */}
            <div className="flex items-center gap-2">
              <button
                onClick={() => setAutoRefresh(!autoRefresh)}
                className={`px-3 py-1.5 rounded-xl border text-xs font-bold transition-all cursor-pointer flex items-center gap-1.5 ${autoRefresh
                  ? "bg-emerald-950/40 border-emerald-500/30 text-emerald-300 shadow-md shadow-emerald-900/20"
                  : "bg-slate-900/50 border-white/10 text-slate-400 hover:text-slate-200"
                  }`}
                title={autoRefresh ? "Real-time auto-refresh active (3s)" : "Enable auto-refresh (3s)"}
              >
                <span className={`w-2 h-2 rounded-full ${autoRefresh ? "bg-emerald-400 animate-ping" : "bg-slate-500"}`} />
                <span>{autoRefresh ? "⚡ Realtime (3s)" : "⏸ Auto-refresh Paused"}</span>
              </button>

              <button
                onClick={() => fetchMetrics(false)}
                disabled={loading}
                className="px-3 py-1.5 rounded-xl bg-purple-950/40 border border-purple-500/30 text-purple-300 hover:bg-purple-800/40 text-xs font-bold transition-all cursor-pointer disabled:opacity-50 flex items-center gap-1.5"
                title="Refresh metrics manually"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
                <span>Refresh</span>
              </button>
            </div>
          </div>
        </div>
      </header>

      {/* MAIN CONTENT */}
      <main className="flex-1 p-6 lg:p-8 max-w-[1600px] mx-auto w-full space-y-6">

        {/* 4 GLOBAL KPI SUMMARY CARDS */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {/* KPI 1: TOKEN CONSUMPTION & INPUT/OUTPUT/REASONING BREAKDOWN */}
          <div className="bg-[#0e0e12] border border-white/10 rounded-2xl p-5 flex flex-col justify-between shadow-2xl hover:border-purple-500/40 transition-all">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold uppercase tracking-wider text-slate-400">
                Tokens ({timeRange === "all" ? "Total History" : timeRange})
              </span>
            </div>
            <div className="my-2 space-y-2">
              <div className="text-2xl font-black text-white tracking-tight">
                {formatNumber(metrics?.total_tokens || 0)}
              </div>
              <div className="grid grid-cols-3 gap-1.5 text-[11px] text-slate-400">
                <div className="flex items-center gap-1 bg-purple-950/30 border border-purple-500/20 px-2 py-1 rounded-lg">
                  <ArrowDownLeft className="w-3 h-3 text-purple-400 shrink-0" />
                  <div className="truncate">
                    <span className="block text-[9px] text-slate-400 uppercase">Input</span>
                    <strong className="text-purple-300 font-mono text-[11px]">
                      {formatNumber(metrics?.prompt_tokens || 0)}
                    </strong>
                  </div>
                </div>
                <div className="flex items-center gap-1 bg-indigo-950/30 border border-indigo-500/20 px-2 py-1 rounded-lg">
                  <ArrowUpRight className="w-3 h-3 text-indigo-400 shrink-0" />
                  <div className="truncate">
                    <span className="block text-[9px] text-slate-400 uppercase">Output</span>
                    <strong className="text-indigo-300 font-mono text-[11px]">
                      {formatNumber(metrics?.completion_tokens || 0)}
                    </strong>
                  </div>
                </div>
                <div className="flex items-center gap-1 bg-cyan-950/30 border border-cyan-500/20 px-2 py-1 rounded-lg">
                  <Brain className="w-3 h-3 text-cyan-400 shrink-0" />
                  <div className="truncate">
                    <span className="block text-[9px] text-slate-400 uppercase">Reasoning</span>
                    <strong className="text-cyan-300 font-mono text-[11px]">
                      {formatNumber(metrics?.reasoning_tokens || 0)}
                    </strong>
                  </div>
                </div>
              </div>

              {/* LAST TURN TOKEN CONSUMPTION BADGE */}
              <div className="p-2 rounded-lg bg-[#14141d] border border-white/10 text-[10px] space-y-1">
                <div className="flex items-center justify-between font-bold text-slate-300">
                  <span className="flex items-center gap-1 text-cyan-400">
                    Last Turn:
                  </span>
                  <span className="font-mono text-cyan-200">
                    {formatNumber(
                      (metrics?.last_turn_prompt_tokens || 0) +
                      (metrics?.last_turn_completion_tokens || 0) +
                      (metrics?.last_turn_reasoning_tokens || 0)
                    )}{" "}
                    tokens
                  </span>
                </div>
                <div className="flex items-center justify-between text-slate-400 font-mono text-[10px]">
                  <span>Input: <strong className="text-purple-300">{formatNumber(metrics?.last_turn_prompt_tokens || 0)}</strong></span>
                  <span>Output: <strong className="text-indigo-300">{formatNumber(metrics?.last_turn_completion_tokens || 0)}</strong></span>
                  <span>Reasoning: <strong className="text-cyan-300">{formatNumber(metrics?.last_turn_reasoning_tokens || 0)}</strong></span>
                </div>
              </div>
            </div>
            <div className="w-full bg-white/10 h-1.5 rounded-full overflow-hidden flex mt-1">
              <div
                className="bg-purple-500 h-full transition-all duration-500"
                style={{
                  width: `${metrics?.total_tokens
                    ? ((metrics.prompt_tokens / metrics.total_tokens) * 100).toFixed(0)
                    : 40
                    }%`,
                }}
                title={`Input: ${metrics?.prompt_tokens || 0}`}
              />
              <div
                className="bg-indigo-400 h-full transition-all duration-500"
                style={{
                  width: `${metrics?.total_tokens
                    ? ((metrics.completion_tokens / metrics.total_tokens) * 100).toFixed(0)
                    : 40
                    }%`,
                }}
                title={`Output: ${metrics?.completion_tokens || 0}`}
              />
              <div
                className="bg-cyan-400 h-full flex-1 transition-all duration-500"
                style={{
                  width: `${metrics?.total_tokens
                    ? ((metrics.reasoning_tokens / metrics.total_tokens) * 100).toFixed(0)
                    : 20
                    }%`,
                }}
                title={`Reasoning: ${metrics?.reasoning_tokens || 0}`}
              />
            </div>

            {/* TOKENS SPARKLINE AREA CHART */}
            <SparklineArea data={metrics?.tokens_series} timeRange={timeRange} color="#a855f7" formatVal={(v) => formatNumber(v)} />
          </div>

          {/* KPI 2: TURN DURATION (AVG & LAST TURN) */}
          <div className="bg-[#0e0e12] border border-white/10 rounded-2xl p-5 flex flex-col justify-between shadow-2xl hover:border-blue-500/40 transition-all">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold uppercase tracking-wider text-slate-400">Turn Duration</span>
            </div>
            <div className="my-2">
              <div className="flex items-baseline justify-between">
                <div>
                  <span className="text-[10px] uppercase text-slate-400 font-semibold block" title="Media generale non filtrata per profilo">Average (Overall)</span>
                  <div className="text-2xl font-black text-white tracking-tight font-mono">
                    {metrics?.avg_turn_duration_seconds || 0}s
                  </div>
                </div>
                <div className="text-right">
                  <span className="text-[10px] uppercase text-cyan-400 font-bold block">Last Turn</span>
                  <div className="text-xl font-black text-cyan-300 tracking-tight font-mono">
                    {metrics?.last_turn_duration_seconds || 0}s
                  </div>
                </div>
              </div>
              <div className="text-[11px] text-slate-400 mt-2 flex items-center justify-between border-t border-white/5 pt-1.5">
                <span>P95 Latency:</span>
                <span className="text-blue-300 font-mono font-bold">{metrics?.p95_turn_duration_seconds || 0}s</span>
              </div>
            </div>
            <div className="text-[11px] text-slate-500 italic">Overall mean turn response duration across profiles</div>

            {/* TURN DURATION SPARKLINE AREA CHART */}
            <SparklineArea data={metrics?.turn_duration_series} timeRange={timeRange} color="#3b82f6" formatVal={(v) => `${v}s`} />
          </div>

          {/* KPI 3: TOTAL TURNS & FAILURES */}
          <div className="bg-[#0e0e12] border border-white/10 rounded-2xl p-5 flex flex-col justify-between shadow-2xl hover:border-amber-500/40 transition-all">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold uppercase tracking-wider text-slate-400">
                Total Turns ({timeRange === "all" ? "Total History" : timeRange})
              </span>
            </div>
            <div className="my-2">
              <div className="text-2xl font-black text-white tracking-tight">
                {metrics?.total_turns || 0}
              </div>
              <div className="text-[11px] text-slate-400 mt-1 flex items-center justify-between">
                <span>Total Failures ({timeRange}):</span>
                <span className="text-red-400 font-bold font-mono">{metrics?.total_failures || 0}</span>
              </div>
            </div>
            <div className="text-[11px] text-slate-500 italic">Completed user interactions ({timeRange})</div>

            {/* TOTAL TURNS MINI BAR CHART */}
            <MiniBarChart data={metrics?.turns_series} timeRange={timeRange} color="#f59e0b" formatVal={(v) => `${v} turns`} />
          </div>

          {/* KPI 4: TOOL INVOCATIONS */}
          <div className="bg-[#0e0e12] border border-white/10 rounded-2xl p-5 flex flex-col justify-between shadow-2xl hover:border-cyan-500/40 transition-all">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold uppercase tracking-wider text-slate-400">
                Tool Calls ({timeRange === "all" ? "Total History" : timeRange})
              </span>
            </div>
            <div className="my-2">
              <div className="text-2xl font-black text-white tracking-tight">
                {metrics?.total_tool_calls || 0}
              </div>
              <div className="text-[11px] text-slate-400 mt-1 flex items-center justify-between">
                <span>Success Rate:</span>
                <span className="text-emerald-400 font-bold font-mono">{metrics?.tool_success_rate || 100}%</span>
              </div>
            </div>
            <div className="text-[11px] text-slate-500 italic">MCP integration and skill invocations ({timeRange})</div>

            {/* TOOL CALLS MINI BAR CHART */}
            <MiniBarChart data={metrics?.tool_calls_series} timeRange={timeRange} color="#06b6d4" formatVal={(v) => `${v} calls`} />
          </div>
        </div>

        {/* SECTION: AGENT PROFILE BREAKDOWN TABLE */}
        <div className="bg-[#0e0e12] border border-white/10 rounded-2xl p-6 space-y-4 shadow-2xl">
          <div className="flex items-center justify-between pb-3 border-b border-white/5">
            <div className="flex items-center gap-2 text-purple-400 font-bold text-xs uppercase tracking-wider">
              <Bot className="w-4 h-4" />
              <span>Agent Profile Breakdown ({timeRange === "all" ? "Total History" : timeRange})</span>
            </div>
            <span className="text-xs text-slate-400 font-mono">
              {metrics?.profile_metrics?.length || 0} active profiles
            </span>
          </div>

          {!metrics?.profile_metrics || metrics.profile_metrics.length === 0 ? (
            <div className="py-8 text-center text-slate-500 text-xs italic">
              No profile metrics recorded for the selected time range ({timeRange}).
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs border-collapse">
                <thead>
                  <tr className="border-b border-white/10 text-slate-400 uppercase tracking-wider font-bold">
                    <th className="py-3 px-4">Agent Profile</th>
                    <th className="py-3 px-4 text-right">Tokens ({timeRange})</th>
                    <th className="py-3 px-4 text-right">Input / Output / Reasoning</th>
                    <th className="py-3 px-4 text-center">Turns</th>
                    <th className="py-3 px-4 text-center">Tool Calls</th>
                    <th className="py-3 px-4 text-center">Success %</th>
                    <th className="py-3 px-4 text-right">Avg Duration</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/5">
                  {metrics.profile_metrics.map((pm, idx) => (
                    <tr
                      key={idx}
                      className="hover:bg-white/5 transition-all"
                    >
                      <td className="py-3 px-4 font-bold text-white font-mono flex items-center gap-2">
                        <span>{pm.profile}</span>
                      </td>
                      <td className="py-3 px-4 text-right font-mono font-bold text-purple-300">
                        {formatNumber(pm.total_tokens)}
                      </td>
                      <td className="py-3 px-4 text-right font-mono text-slate-300">
                        <span className="text-purple-400" title="Input Tokens">{formatNumber(pm.prompt_tokens)}</span>
                        <span className="text-slate-500 mx-1">/</span>
                        <span className="text-indigo-400" title="Output Tokens">{formatNumber(pm.completion_tokens)}</span>
                        <span className="text-slate-500 mx-1">/</span>
                        <span className="text-cyan-400" title="Reasoning Tokens">{formatNumber(pm.reasoning_tokens || 0)}</span>
                      </td>
                      <td className="py-3 px-4 text-center font-mono font-bold text-white">
                        {pm.total_turns}
                      </td>
                      <td className="py-3 px-4 text-center font-mono text-cyan-300 font-bold">
                        {pm.total_tool_calls}
                      </td>
                      <td className="py-3 px-4 text-center font-mono">
                        <span
                          className={`px-2 py-0.5 rounded-full text-[11px] font-bold ${pm.tool_success_rate >= 95
                            ? "bg-emerald-950/40 text-emerald-400 border border-emerald-500/30"
                            : pm.tool_success_rate >= 80
                              ? "bg-amber-950/40 text-amber-400 border border-amber-500/30"
                              : "bg-red-950/40 text-red-400 border border-red-500/30"
                            }`}
                        >
                          {pm.tool_success_rate}%
                        </span>
                      </td>
                      <td className="py-3 px-4 text-right font-mono text-slate-300">
                        {pm.avg_turn_duration_seconds}s
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* SECTION: USER BREAKDOWN TABLE WITH EXPANDABLE PROFILE DETAILS */}
        <div className="bg-[#0e0e12] border border-white/10 rounded-2xl p-6 space-y-4 shadow-2xl">
          <div className="flex items-center justify-between pb-3 border-b border-white/5">
            <div className="flex items-center gap-2 text-indigo-400 font-bold text-xs uppercase tracking-wider">
              <Users className="w-4 h-4" />
              <span>User Breakdown ({timeRange === "all" ? "Total History" : timeRange})</span>
            </div>
            <span className="text-xs text-slate-400 font-mono">
              {metrics?.user_metrics?.length || 0} active users
            </span>
          </div>

          {!metrics?.user_metrics || metrics.user_metrics.length === 0 ? (
            <div className="py-8 text-center text-slate-500 text-xs italic">
              No user metrics recorded for the selected time range ({timeRange}).
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs border-collapse">
                <thead>
                  <tr className="border-b border-white/10 text-slate-400 uppercase tracking-wider font-bold">
                    <th className="py-3 px-4">User</th>
                    <th className="py-3 px-4 text-right">Tokens ({timeRange})</th>
                    <th className="py-3 px-4 text-right">Input / Output / Reasoning</th>
                    <th className="py-3 px-4 text-center">Turns</th>
                    <th className="py-3 px-4 text-center">Tool Calls</th>
                    <th className="py-3 px-4 text-center">Success %</th>
                    <th className="py-3 px-4 text-right">Avg Duration</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/5">
                  {metrics.user_metrics.map((um) => {
                    const isExpanded = !!expandedUsers[um.user_id];
                    return (
                      <React.Fragment key={um.user_id}>
                        <tr
                          onClick={() => toggleUserExpand(um.user_id)}
                          className="hover:bg-white/5 transition-all cursor-pointer group"
                        >
                          <td className="py-3 px-4 font-bold text-white font-mono flex items-center gap-2">
                            <button
                              className="p-1 rounded-md bg-white/5 group-hover:bg-white/10 text-slate-400 group-hover:text-white transition-all"
                              title={isExpanded ? "Collapse profiles" : "Expand profile details"}
                            >
                              {isExpanded ? (
                                <ChevronDown className="w-3.5 h-3.5 text-indigo-400" />
                              ) : (
                                <ChevronRight className="w-3.5 h-3.5 text-slate-400" />
                              )}
                            </button>
                            <span className="text-indigo-300 font-semibold">{um.user_id}</span>
                            <span className="text-[10px] text-slate-500 font-normal">
                              ({um.profile_breakdown.length} profiles)
                            </span>
                          </td>
                          <td className="py-3 px-4 text-right font-mono font-bold text-purple-300">
                            {formatNumber(um.total_tokens)}
                          </td>
                          <td className="py-3 px-4 text-right font-mono text-slate-300">
                            <span className="text-purple-400" title="Input Tokens">{formatNumber(um.prompt_tokens)}</span>
                            <span className="text-slate-500 mx-1">/</span>
                            <span className="text-indigo-400" title="Output Tokens">{formatNumber(um.completion_tokens)}</span>
                            <span className="text-slate-500 mx-1">/</span>
                            <span className="text-cyan-400" title="Reasoning Tokens">{formatNumber(um.reasoning_tokens || 0)}</span>
                          </td>
                          <td className="py-3 px-4 text-center font-mono font-bold text-white">
                            {um.total_turns}
                          </td>
                          <td className="py-3 px-4 text-center font-mono text-cyan-300 font-bold">
                            {um.total_tool_calls}
                          </td>
                          <td className="py-3 px-4 text-center font-mono">
                            <span
                              className={`px-2 py-0.5 rounded-full text-[11px] font-bold ${um.tool_success_rate >= 95
                                ? "bg-emerald-950/40 text-emerald-400 border border-emerald-500/30"
                                : um.tool_success_rate >= 80
                                  ? "bg-amber-950/40 text-amber-400 border border-amber-500/30"
                                  : "bg-red-950/40 text-red-400 border border-red-500/30"
                                }`}
                            >
                              {um.tool_success_rate}%
                            </span>
                          </td>
                          <td className="py-3 px-4 text-right font-mono text-slate-300">
                            {um.avg_turn_duration_seconds}s
                          </td>
                        </tr>

                        {/* EXPANDED ROW DETAILS (SCHEMATIC SUB-TABLE) */}
                        {isExpanded && (
                          <tr className="bg-[#12121a]">
                            <td colSpan={7} className="p-4 border-l-2 border-indigo-500">
                              <div className="space-y-3">
                                <div className="flex items-center justify-between text-xs font-bold text-slate-300 pb-2 border-b border-white/10">
                                  <span className="flex items-center gap-1.5 text-indigo-300">
                                    <Bot className="w-3.5 h-3.5" />
                                    Profiles Used by User <strong className="text-white font-mono">{um.user_id}</strong>
                                  </span>
                                  <span className="text-[11px] text-slate-400 font-mono">
                                    {um.profile_breakdown.length} profiles recorded
                                  </span>
                                </div>

                                {um.profile_breakdown.length === 0 ? (
                                  <div className="text-slate-500 text-xs italic py-2">
                                    No profile breakdown recorded for this user.
                                  </div>
                                ) : (
                                  <div className="overflow-x-auto rounded-xl border border-white/10 bg-[#161620]">
                                    <table className="w-full text-left text-xs border-collapse">
                                      <thead>
                                        <tr className="border-b border-white/10 text-slate-400 uppercase tracking-wider font-bold text-[10px] bg-[#1a1a26]">
                                          <th className="py-2 px-3">Agent Profile</th>
                                          <th className="py-2 px-3 text-center">Frequency %</th>
                                          <th className="py-2 px-3">Distribution</th>
                                          <th className="py-2 px-3 text-center">Turns</th>
                                          <th className="py-2 px-3 text-right">Tokens (Total / In / Out / Reas)</th>
                                          <th className="py-2 px-3 text-center">Tool Calls</th>
                                          <th className="py-2 px-3">Tools Executed per Profile</th>
                                        </tr>
                                      </thead>
                                      <tbody className="divide-y divide-white/5 font-mono">
                                        {um.profile_breakdown.map((pb, pidx) => (
                                          <tr key={pidx} className="hover:bg-white/5 transition-all">
                                            <td className="py-2.5 px-3 font-bold text-white flex items-center gap-1.5">
                                              <span>🤖 {pb.profile}</span>
                                            </td>
                                            <td className="py-2.5 px-3 text-center">
                                              <span className="px-2 py-0.5 rounded bg-indigo-950/60 border border-indigo-500/30 text-indigo-300 font-bold text-[11px]">
                                                {pb.usage_frequency_percent}%
                                              </span>
                                            </td>
                                            <td className="py-2.5 px-3 w-36">
                                              <div className="w-full bg-white/10 h-1.5 rounded-full overflow-hidden">
                                                <div
                                                  className="bg-indigo-500 h-full transition-all duration-300"
                                                  style={{ width: `${Math.min(100, Math.max(2, pb.usage_frequency_percent))}%` }}
                                                  title={`Frequency: ${pb.usage_frequency_percent}%`}
                                                />
                                              </div>
                                            </td>
                                            <td className="py-2.5 px-3 text-center text-white font-bold">
                                              {pb.total_turns}
                                            </td>
                                            <td className="py-2.5 px-3 text-right">
                                              <div className="font-bold text-purple-300">
                                                {formatNumber(pb.total_tokens)}
                                              </div>
                                              <div className="text-[10px] text-slate-400 font-mono">
                                                <span className="text-purple-400" title="Input Tokens">{formatNumber(pb.prompt_tokens || 0)}</span>
                                                <span className="text-slate-500 mx-0.5">/</span>
                                                <span className="text-indigo-400" title="Output Tokens">{formatNumber(pb.completion_tokens || 0)}</span>
                                                <span className="text-slate-500 mx-0.5">/</span>
                                                <span className="text-cyan-400" title="Reasoning Tokens">{formatNumber(pb.reasoning_tokens || 0)}</span>
                                              </div>
                                            </td>
                                            <td className="py-2.5 px-3 text-center text-cyan-300 font-bold">
                                              {pb.total_tool_calls}
                                            </td>
                                            <td className="py-2.5 px-3">
                                              {!pb.tools_breakdown || pb.tools_breakdown.length === 0 ? (
                                                <span className="text-slate-500 text-[11px] font-mono italic">No tool calls</span>
                                              ) : (
                                                <div className="flex flex-wrap gap-1 max-w-sm">
                                                  {pb.tools_breakdown.map((tb, tidx) => (
                                                    <span
                                                      key={tidx}
                                                      className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-[#1f1f2e] border border-white/10 text-[10px] font-mono"
                                                      title={`MCP Server: ${tb.mcp_server} | Calls: ${tb.call_count} | Errors: ${tb.error_count}`}
                                                    >
                                                      <span className="text-cyan-300 font-bold">{tb.tool_name}</span>
                                                      <span className="text-slate-500 text-[9px]">({tb.mcp_server})</span>
                                                      <span className="text-white font-bold bg-white/10 px-1 rounded text-[9px]">
                                                        {tb.call_count}
                                                      </span>
                                                      {tb.error_count > 0 && (
                                                        <span className="text-red-400 font-bold text-[9px]">
                                                          ({tb.error_count} err)
                                                        </span>
                                                      )}
                                                    </span>
                                                  ))}
                                                </div>
                                              )}
                                            </td>
                                          </tr>
                                        ))}
                                      </tbody>
                                    </table>
                                  </div>
                                )}
                              </div>
                            </td>
                          </tr>
                        )}
                      </React.Fragment>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* BOTTOM SECTION: TOOL & MCP EXECUTION DETAILS */}
        <div className="bg-[#0e0e12] border border-white/10 rounded-2xl p-6 space-y-4 shadow-2xl">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between pb-3 border-b border-white/5 gap-3">
            <div className="flex items-center gap-2 text-cyan-400 font-bold text-xs uppercase tracking-wider">
              <Layers className="w-4 h-4" />
              <span>Tool & MCP Execution Details ({timeRange === "all" ? "Total History" : timeRange})</span>
            </div>

            {/* PROFILE FILTER & SEARCH CONTROLS */}
            <div className="flex items-center gap-3 flex-wrap">
              {/* PROFILE DROPDOWN SELECTOR */}
              <div className="flex items-center gap-1.5 bg-[#16161d] border border-white/10 rounded-xl px-3 py-1.5 shadow-inner">
                <Filter className="w-3.5 h-3.5 text-cyan-400" />
                <select
                  value={selectedProfile}
                  onChange={(e) => setSelectedProfile(e.target.value)}
                  className="bg-transparent text-xs text-slate-200 font-medium outline-none cursor-pointer pr-1"
                >
                  <option value="" className="bg-[#16161d] text-slate-300">
                    All Profiles
                  </option>
                  {profiles.map((p) => {
                    const val = p.slug || p.name;
                    return (
                      <option key={val} value={val} className="bg-[#16161d] text-slate-300">
                        {p.name}
                      </option>
                    );
                  })}
                </select>
              </div>

              {/* SEARCH INPUT */}
              <div className="flex items-center gap-2 bg-[#16161d] border border-white/10 rounded-xl px-3 py-1.5 w-64 shadow-inner">
                <Search className="w-3.5 h-3.5 text-slate-400 shrink-0" />
                <input
                  type="text"
                  value={toolSearch}
                  onChange={(e) => setToolSearch(e.target.value)}
                  placeholder="Search tool or MCP server..."
                  className="bg-transparent text-xs text-white outline-none w-full placeholder-slate-500 font-mono"
                />
              </div>
              <span className="text-xs text-slate-400 font-mono shrink-0">
                {filteredToolMetrics.length} / {metrics?.tool_metrics?.length || 0}
              </span>
            </div>
          </div>

          {filteredToolMetrics.length === 0 ? (
            <div className="py-8 text-center text-slate-500 text-xs italic">
              No tool invocations found {toolSearch ? `for "${toolSearch}"` : `in range (${timeRange})`}.
            </div>
          ) : (
            <div className="overflow-x-auto max-h-[420px] overflow-y-auto pr-1">
              <table className="w-full text-left text-xs border-collapse">
                <thead className="sticky top-0 z-10 bg-[#0e0e12]">
                  <tr className="border-b border-white/10 text-slate-400 uppercase tracking-wider font-bold">
                    <th className="py-3 px-4">Tool Name</th>
                    <th className="py-3 px-4">MCP Server / Origin</th>
                    <th className="py-3 px-4 text-center">Total Calls ({timeRange})</th>
                    <th className="py-3 px-4 text-center">Errors</th>
                    <th className="py-3 px-4 text-right">Success Rate %</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/5">
                  {filteredToolMetrics.map((tool, idx) => (
                    <tr key={idx} className="hover:bg-white/5 transition-all">
                      <td className="py-3 px-4 font-bold text-white font-mono">{tool.tool_name}</td>
                      <td className="py-3 px-4 text-slate-400 font-mono">{tool.mcp_server}</td>
                      <td className="py-3 px-4 text-center font-mono font-bold text-slate-200">
                        {tool.call_count}
                      </td>
                      <td className="py-3 px-4 text-center font-mono">
                        {tool.error_count > 0 ? (
                          <span className="text-red-400 font-bold">{tool.error_count}</span>
                        ) : (
                          <span className="text-slate-500">0</span>
                        )}
                      </td>
                      <td className="py-3 px-4 text-right font-mono font-bold">
                        <span
                          className={`px-2 py-0.5 rounded-full text-[11px] ${tool.success_rate >= 95
                            ? "bg-emerald-950/40 text-emerald-400 border border-emerald-500/30"
                            : tool.success_rate >= 80
                              ? "bg-amber-950/40 text-amber-400 border border-amber-500/30"
                              : "bg-red-950/40 text-red-400 border border-red-500/30"
                            }`}
                        >
                          {tool.success_rate}%
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* MIDDLE SECTION: TOKEN USAGE BY MODEL & ENHANCED DIAGNOSTICS FOR MCP ERRORS */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          {/* TOKEN BREAKDOWN BY MODEL (6 COLS) */}
          <div className="lg:col-span-6 bg-[#0e0e12] border border-white/10 rounded-2xl p-6 flex flex-col gap-4 shadow-2xl">
            <div className="flex items-center justify-between pb-3 border-b border-white/5">
              <div className="flex items-center gap-2 text-purple-400 font-bold text-xs uppercase tracking-wider">
                <Cpu className="w-4 h-4" />
                <span>LLM Model Token Consumption ({timeRange === "all" ? "Total History" : timeRange})</span>
              </div>
              <span className="text-xs text-slate-400 font-mono">
                {Object.keys(metrics?.token_usage_by_model || {}).length} models detected
              </span>
            </div>

            {Object.keys(metrics?.token_usage_by_model || {}).length === 0 ? (
              <div className="py-8 text-center text-slate-500 text-xs italic">
                No token usage recorded for the selected time range ({timeRange}).
              </div>
            ) : (
              <div className="space-y-4">
                {Object.entries(metrics?.token_usage_by_model || {}).map(([model, usage]) => {
                  const mPrompt = usage.prompt || 0;
                  const mComp = usage.completion || 0;
                  const mReas = usage.reasoning || 0;
                  const mTotal = mPrompt + mComp + mReas;

                  return (
                    <div key={model} className="p-3.5 rounded-xl bg-[#14141a] border border-white/5 space-y-2">
                      <div className="flex items-center justify-between text-xs">
                        <span className="font-bold text-white font-mono">{model}</span>
                        <span className="text-purple-300 font-mono font-semibold">
                          {formatNumber(mTotal)} tokens
                        </span>
                      </div>
                      <div className="w-full bg-white/10 h-2 rounded-full overflow-hidden flex">
                        <div
                          className="bg-purple-500 h-full"
                          style={{ width: `${mTotal ? ((mPrompt / mTotal) * 100).toFixed(0) : 50}%` }}
                          title={`Input (Prompt): ${mPrompt}`}
                        />
                        <div
                          className="bg-indigo-400 h-full"
                          style={{ width: `${mTotal ? ((mComp / mTotal) * 100).toFixed(0) : 50}%` }}
                          title={`Output (Completion): ${mComp}`}
                        />
                        {mReas > 0 && (
                          <div
                            className="bg-cyan-400 h-full"
                            style={{ width: `${mTotal ? ((mReas / mTotal) * 100).toFixed(0) : 0}%` }}
                            title={`Reasoning: ${mReas}`}
                          />
                        )}
                      </div>
                      <div className="flex items-center justify-between text-[11px] text-slate-400 font-mono">
                        <span>Input (Prompt): {formatNumber(mPrompt)}</span>
                        <span>Output (Comp.): {formatNumber(mComp)}</span>
                        {mReas > 0 && <span>Reasoning: {formatNumber(mReas)}</span>}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* ENHANCED DIAGNOSTICS: RECENT MCP CALL ERRORS (6 COLS) */}
          <div className="lg:col-span-6 bg-[#0e0e12] border border-white/10 rounded-2xl p-6 flex flex-col gap-4 shadow-2xl">
            <div className="flex flex-wrap items-center justify-between pb-3 border-b border-white/5 gap-2">
              <div className="flex items-center gap-2 text-red-400 font-bold text-xs uppercase tracking-wider">
                <AlertTriangle className="w-4 h-4" />
                <span>MCP Error & Failure Diagnostics</span>
              </div>

              {/* LIMIT SELECTOR & SHOW ALL BUTTON */}
              <div className="flex items-center gap-2">
                {/* SELECT LIMIT N DROPDOWN */}
                <div className="flex items-center gap-1 bg-[#16161d] border border-white/10 rounded-lg px-2 py-1 text-xs">
                  <ListFilter className="w-3 h-3 text-slate-400" />
                  <select
                    value={showAllErrors ? "all" : errorLimit}
                    onChange={(e) => {
                      if (e.target.value === "all") {
                        setShowAllErrors(true);
                      } else {
                        setShowAllErrors(false);
                        setErrorLimit(Number(e.target.value));
                      }
                    }}
                    className="bg-transparent text-[11px] font-mono text-slate-200 outline-none cursor-pointer"
                  >
                    <option value={5} className="bg-[#16161d]">Last 5</option>
                    <option value={10} className="bg-[#16161d]">Last 10</option>
                    <option value={25} className="bg-[#16161d]">Last 25</option>
                    <option value={50} className="bg-[#16161d]">Last 50</option>
                    <option value="all" className="bg-[#16161d]">Show all ({rawErrors.length})</option>
                  </select>
                </div>

                {/* SHOW ALL TOGGLE BUTTON */}
                <button
                  onClick={() => setShowAllErrors(!showAllErrors)}
                  className={`px-2.5 py-1 rounded-lg border text-[11px] font-bold font-mono transition-all flex items-center gap-1 cursor-pointer ${showAllErrors
                    ? "bg-red-950/60 border-red-500/40 text-red-300 shadow-md shadow-red-900/20"
                    : "bg-slate-900 border-white/10 text-slate-400 hover:text-white"
                    }`}
                  title={showAllErrors ? "Limit to N errors" : "Show all MCP errors"}
                >
                  {showAllErrors ? (
                    <>
                      <Minimize2 className="w-3 h-3" /> Limit
                    </>
                  ) : (
                    <>
                      <Maximize2 className="w-3 h-3" /> Show All ({rawErrors.length})
                    </>
                  )}
                </button>
              </div>
            </div>

            {rawErrors.length === 0 ? (
              <div className="py-12 flex flex-col items-center justify-center text-center gap-2 text-emerald-400">
                <CheckCircle2 className="w-8 h-8 opacity-80" />
                <div className="text-xs font-bold text-slate-200">No MCP Errors Detected</div>
                <p className="text-[11px] text-slate-400">
                  All tool and MCP server invocations completed successfully.
                </p>
              </div>
            ) : (
              <div className="space-y-3 max-h-[380px] overflow-y-auto pr-1">
                {displayedErrors.map((err, idx) => (
                  <div
                    key={idx}
                    className="p-3.5 rounded-xl bg-red-950/20 border border-red-500/30 flex flex-col gap-2 transition-all hover:bg-red-950/30 shadow-sm"
                  >
                    {/* TOOL, SERVER & PROFILE */}
                    <div className="flex items-start justify-between gap-3 text-xs">
                      <div className="flex flex-col gap-0.5">
                        <div className="font-bold text-white font-mono flex items-center gap-1.5 text-xs">
                          <span className="text-white font-bold">Tool: </span>
                          <span className="text-cyan-300 font-semibold">{err.tool_name}</span>
                          <span className="text-slate-500 text-[11px] font-sans">Server: </span>
                          <span className="text-cyan-300 font-semibold">{err.mcp_server}</span>
                        </div>
                        <div className="text-[11px] text-slate-400 font-mono">
                          Profile: <strong className="text-purple-300 font-semibold">{err.profile}</strong>
                        </div>
                      </div>

                      {err.timestamp && (
                        <span className="text-[10px] text-slate-500 font-mono shrink-0">
                          {formatTimestamp(err.timestamp, "1h")}
                        </span>
                      )}
                    </div>

                    {/* ERROR MESSAGE */}
                    {err.error_message && (
                      <p className="text-[11px] font-mono text-red-200/90 bg-black/60 p-2.5 rounded-lg border border-red-900/40 break-words leading-relaxed">
                        {err.error_message}
                      </p>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </main>

      {/* OBSERVABILITY & TELEMETRY CONFIGURATION MODAL */}
      {showConfigModal && (
        <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-md flex items-center justify-center p-4 animate-in fade-in duration-200">
          <div className="bg-[#0e0e12] border border-white/10 rounded-3xl max-w-3xl w-full flex flex-col max-h-[90vh] shadow-2xl overflow-hidden animate-in zoom-in-95 duration-200">
            {/* MODAL HEADER */}
            <div className="px-6 py-5 border-b border-white/10 flex items-center justify-between bg-[#13131a]">
              <div className="flex items-center gap-3">
                <div className="p-2.5 rounded-xl bg-purple-950/50 border border-purple-500/40 text-purple-400 shadow-md shadow-purple-950/30">
                  <Sliders className="w-5 h-5" />
                </div>
                <div>
                  <h2 className="text-lg font-bold text-white tracking-tight flex items-center gap-2">
                    Observability & Telemetry Settings
                  </h2>
                  <p className="text-xs text-slate-400">
                    Configure Prometheus scrapers, OpenTelemetry exporters, and Opik LLM tracking.
                  </p>
                </div>
              </div>
              <button
                onClick={() => setShowConfigModal(false)}
                className="p-2 rounded-xl text-slate-400 hover:text-white hover:bg-white/10 transition-all cursor-pointer"
                title="Close"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* MESSAGE BANNER */}
            {configMessage && (
              <div
                className={`mx-6 mt-4 p-3 rounded-xl border text-xs flex items-center gap-2.5 ${configMessage.type === "success"
                  ? "bg-emerald-950/40 border-emerald-500/40 text-emerald-200"
                  : "bg-red-950/40 border-red-500/40 text-red-200"
                  }`}
              >
                {configMessage.type === "success" ? (
                  <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
                ) : (
                  <AlertCircle className="w-4 h-4 text-red-400 shrink-0" />
                )}
                <span>{configMessage.text}</span>
              </div>
            )}

            {/* TAB NAVIGATION */}
            <div className="px-6 pt-4 border-b border-white/5 flex gap-2 overflow-x-auto bg-[#0e0e12]">
              <button
                onClick={() => setConfigTab("prometheus")}
                className={`pb-3 px-3 text-xs font-bold transition-all border-b-2 flex items-center gap-2 cursor-pointer ${configTab === "prometheus"
                  ? "border-purple-500 text-white"
                  : "border-transparent text-slate-400 hover:text-slate-200"
                  }`}
              >
                <BarChart3 className="w-4 h-4 text-purple-400" />
                <span>Prometheus & Scraping</span>
              </button>

              <button
                onClick={() => setConfigTab("otel")}
                className={`pb-3 px-3 text-xs font-bold transition-all border-b-2 flex items-center gap-2 cursor-pointer ${configTab === "otel"
                  ? "border-indigo-500 text-white"
                  : "border-transparent text-slate-400 hover:text-slate-200"
                  }`}
              >
                <Radio className="w-4 h-4 text-indigo-400" />
                <span>OpenTelemetry (OTel)</span>
              </button>

              <button
                onClick={() => setConfigTab("opik")}
                className={`pb-3 px-3 text-xs font-bold transition-all border-b-2 flex items-center gap-2 cursor-pointer ${configTab === "opik"
                  ? "border-cyan-500 text-white"
                  : "border-transparent text-slate-400 hover:text-slate-200"
                  }`}
              >
                <Brain className="w-4 h-4 text-cyan-400" />
                <span>Opik (LLM Telemetry)</span>
              </button>
            </div>

            {/* MODAL BODY (TAB CONTENT) */}
            <div className="p-6 overflow-y-auto space-y-5 flex-1 custom-scrollbar">
              {configLoading ? (
                <div className="py-16 flex flex-col items-center justify-center gap-3 text-slate-400">
                  <Loader2 className="w-7 h-7 animate-spin text-purple-400" />
                  <span className="text-xs font-mono">Loading current configuration...</span>
                </div>
              ) : (
                <>
                  {/* TAB 1: PROMETHEUS */}
                  {configTab === "prometheus" && (
                    <div className="space-y-4">
                      {/* PROMETHEUS URL */}
                      <div className="space-y-1.5">
                        <div className="flex items-center justify-between">
                          <label className="text-xs font-bold text-slate-200">
                            Remote Prometheus Server URL
                          </label>
                          <span className="text-[10px] font-mono text-purple-400">AION_PROMETHEUS_URL</span>
                        </div>
                        <p className="text-[11px] text-slate-400">
                          URL used by AION to query aggregated PromQL metrics for the Evaluation dashboard and time-series charts.
                        </p>
                        <div className="flex items-center gap-2">
                          <input
                            type="text"
                            value={configSettings.AION_PROMETHEUS_URL || ""}
                            onChange={(e) =>
                              setConfigSettings((prev) => ({
                                ...prev,
                                AION_PROMETHEUS_URL: e.target.value,
                              }))
                            }
                            placeholder="http://localhost:9090"
                            className="bg-[#16161f] border border-white/10 rounded-xl px-3.5 py-2 text-xs font-mono text-white w-full outline-none focus:border-purple-500 transition-all shadow-inner"
                          />
                          <button
                            type="button"
                            onClick={() => handleProbeConnection("prometheus")}
                            disabled={configProbing.prometheus}
                            className="px-3.5 py-2 rounded-xl bg-purple-950/50 border border-purple-500/40 text-purple-300 hover:bg-purple-900/60 text-xs font-bold transition-all whitespace-nowrap cursor-pointer disabled:opacity-50 flex items-center gap-1.5"
                          >
                            {configProbing.prometheus ? (
                              <Loader2 className="w-3.5 h-3.5 animate-spin" />
                            ) : (
                              <Play className="w-3.5 h-3.5" />
                            )}
                            <span>Test Connection</span>
                          </button>
                        </div>

                        {/* PROBE RESULT BADGE */}
                        {configProbeResults.prometheus && (
                          <div
                            className={`mt-2 p-2.5 rounded-xl border text-xs flex items-center justify-between gap-2 ${configProbeResults.prometheus.success
                              ? "bg-emerald-950/30 border-emerald-500/30 text-emerald-300"
                              : "bg-red-950/30 border-red-500/30 text-red-300"
                              }`}
                          >
                            <div className="flex items-center gap-2">
                              {configProbeResults.prometheus.success ? (
                                <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
                              ) : (
                                <AlertTriangle className="w-4 h-4 text-red-400 shrink-0" />
                              )}
                              <span>{configProbeResults.prometheus.message}</span>
                            </div>
                            {configProbeResults.prometheus.latency_ms !== undefined && (
                              <span className="font-mono text-[11px] font-bold">
                                {configProbeResults.prometheus.latency_ms} ms
                              </span>
                            )}
                          </div>
                        )}
                      </div>

                      {/* LOCAL /METRICS SCRAPING EXPOSURE TOGGLE */}
                      <div className="p-4 rounded-2xl bg-[#14141d] border border-white/5 space-y-3">
                        <div className="flex items-center justify-between">
                          <div className="space-y-0.5">
                            <span className="text-xs font-bold text-slate-200">
                              Expose Local Prometheus Scraping Endpoint
                            </span>
                            <p className="text-[11px] text-slate-400">
                              Enables the FastAPI instrumentator endpoint for Prometheus/Grafana Agent scrapers.
                            </p>
                          </div>
                          <button
                            type="button"
                            onClick={() =>
                              setConfigSettings((prev) => ({
                                ...prev,
                                AION_METRICS_ENABLED:
                                  prev.AION_METRICS_ENABLED === "1" ? "0" : "1",
                              }))
                            }
                            className={`w-11 h-6 rounded-full transition-colors relative cursor-pointer ${configSettings.AION_METRICS_ENABLED === "1"
                              ? "bg-purple-600"
                              : "bg-slate-700"
                              }`}
                          >
                            <span
                              className={`w-4 h-4 bg-white rounded-full absolute top-1 transition-transform ${configSettings.AION_METRICS_ENABLED === "1"
                                ? "left-6"
                                : "left-1"
                                }`}
                            />
                          </button>
                        </div>

                        {configSettings.AION_METRICS_ENABLED === "1" && (
                          <div className="pt-2 border-t border-white/5 flex items-center justify-between gap-3">
                            <label className="text-xs text-slate-300">
                              Metrics Path:
                            </label>
                            <input
                              type="text"
                              value={configSettings.AION_METRICS_PATH || "/metrics"}
                              onChange={(e) =>
                                setConfigSettings((prev) => ({
                                  ...prev,
                                  AION_METRICS_PATH: e.target.value,
                                }))
                              }
                              placeholder="/metrics"
                              className="bg-[#16161f] border border-white/10 rounded-lg px-3 py-1 text-xs font-mono text-white w-48 outline-none focus:border-purple-500"
                            />
                          </div>
                        )}
                      </div>
                    </div>
                  )}

                  {/* TAB 2: OPENTELEMETRY (OTEL) */}
                  {configTab === "otel" && (
                    <div className="space-y-4">
                      {/* OTEL ENABLED TOGGLE */}
                      <div className="p-4 rounded-2xl bg-[#14141d] border border-white/5 flex items-center justify-between">
                        <div className="space-y-0.5">
                          <span className="text-xs font-bold text-slate-200">
                            Enable OpenTelemetry (OTel) Exporter
                          </span>
                          <p className="text-[11px] text-slate-400">
                            Pushes distributed traces and metrics to an OTLP Collector (Jaeger, Phoenix, Tempo, OpenLit).
                          </p>
                        </div>
                        <button
                          type="button"
                          onClick={() =>
                            setConfigSettings((prev) => ({
                              ...prev,
                              AION_OTEL_ENABLED:
                                prev.AION_OTEL_ENABLED === "1" ? "0" : "1",
                            }))
                          }
                          className={`w-11 h-6 rounded-full transition-colors relative cursor-pointer ${configSettings.AION_OTEL_ENABLED === "1"
                            ? "bg-indigo-600"
                            : "bg-slate-700"
                            }`}
                        >
                          <span
                            className={`w-4 h-4 bg-white rounded-full absolute top-1 transition-transform ${configSettings.AION_OTEL_ENABLED === "1"
                              ? "left-6"
                              : "left-1"
                              }`}
                          />
                        </button>
                      </div>

                      {/* OTEL COLLECTOR ENDPOINT */}
                      <div className="space-y-1.5">
                        <div className="flex items-center justify-between">
                          <label className="text-xs font-bold text-slate-200">
                            OTLP Collector Endpoint
                          </label>
                          <span className="text-[10px] font-mono text-indigo-400">AION_OTEL_ENDPOINT</span>
                        </div>
                        <div className="flex items-center gap-2">
                          <input
                            type="text"
                            value={configSettings.AION_OTEL_ENDPOINT || ""}
                            onChange={(e) =>
                              setConfigSettings((prev) => ({
                                ...prev,
                                AION_OTEL_ENDPOINT: e.target.value,
                              }))
                            }
                            placeholder="http://localhost:4317"
                            className="bg-[#16161f] border border-white/10 rounded-xl px-3.5 py-2 text-xs font-mono text-white w-full outline-none focus:border-indigo-500 transition-all shadow-inner"
                          />
                          <button
                            type="button"
                            onClick={() => handleProbeConnection("otel")}
                            disabled={configProbing.otel}
                            className="px-3.5 py-2 rounded-xl bg-indigo-950/50 border border-indigo-500/40 text-indigo-300 hover:bg-indigo-900/60 text-xs font-bold transition-all whitespace-nowrap cursor-pointer disabled:opacity-50 flex items-center gap-1.5"
                          >
                            {configProbing.otel ? (
                              <Loader2 className="w-3.5 h-3.5 animate-spin" />
                            ) : (
                              <Play className="w-3.5 h-3.5" />
                            )}
                            <span>Test Collector</span>
                          </button>
                        </div>

                        {/* PROBE RESULT BADGE */}
                        {configProbeResults.otel && (
                          <div
                            className={`mt-2 p-2.5 rounded-xl border text-xs flex items-center justify-between gap-2 ${configProbeResults.otel.success
                              ? "bg-emerald-950/30 border-emerald-500/30 text-emerald-300"
                              : "bg-red-950/30 border-red-500/30 text-red-300"
                              }`}
                          >
                            <div className="flex items-center gap-2">
                              {configProbeResults.otel.success ? (
                                <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
                              ) : (
                                <AlertTriangle className="w-4 h-4 text-red-400 shrink-0" />
                              )}
                              <span>{configProbeResults.otel.message}</span>
                            </div>
                            {configProbeResults.otel.latency_ms !== undefined && (
                              <span className="font-mono text-[11px] font-bold">
                                {configProbeResults.otel.latency_ms} ms
                              </span>
                            )}
                          </div>
                        )}
                      </div>

                      {/* GRID: PROTOCOL & SERVICE NAME & METRIC INTERVAL */}
                      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                        {/* PROTOCOL */}
                        <div className="space-y-1">
                          <label className="text-xs font-bold text-slate-300">
                            Protocol (AION_OTEL_PROTOCOL)
                          </label>
                          <select
                            value={configSettings.AION_OTEL_PROTOCOL || "grpc"}
                            onChange={(e) =>
                              setConfigSettings((prev) => ({
                                ...prev,
                                AION_OTEL_PROTOCOL: e.target.value,
                              }))
                            }
                            className="w-full bg-[#16161f] border border-white/10 rounded-xl px-3 py-2 text-xs text-white outline-none focus:border-indigo-500 cursor-pointer"
                          >
                            <option value="grpc" className="bg-[#16161f]">gRPC (4317)</option>
                            <option value="http" className="bg-[#16161f]">HTTP (4318)</option>
                          </select>
                        </div>

                        {/* SERVICE NAME */}
                        <div className="space-y-1">
                          <label className="text-xs font-bold text-slate-300">
                            Service Name
                          </label>
                          <input
                            type="text"
                            value={configSettings.AION_OTEL_SERVICE_NAME || "aion-agent"}
                            onChange={(e) =>
                              setConfigSettings((prev) => ({
                                ...prev,
                                AION_OTEL_SERVICE_NAME: e.target.value,
                              }))
                            }
                            placeholder="aion-agent"
                            className="w-full bg-[#16161f] border border-white/10 rounded-xl px-3 py-2 text-xs font-mono text-white outline-none focus:border-indigo-500"
                          />
                        </div>

                        {/* METRIC EXPORT INTERVAL */}
                        <div className="space-y-1">
                          <label className="text-xs font-bold text-slate-300">
                            Export Interval (ms)
                          </label>
                          <input
                            type="number"
                            value={configSettings.AION_OTEL_METRIC_EXPORT_INTERVAL || "5000"}
                            onChange={(e) =>
                              setConfigSettings((prev) => ({
                                ...prev,
                                AION_OTEL_METRIC_EXPORT_INTERVAL: e.target.value,
                              }))
                            }
                            placeholder="5000"
                            className="w-full bg-[#16161f] border border-white/10 rounded-xl px-3 py-2 text-xs font-mono text-white outline-none focus:border-indigo-500"
                          />
                        </div>
                      </div>

                      {/* TRACE CONTENT TOGGLE */}
                      <div className="p-3.5 rounded-xl bg-[#14141d] border border-white/5 flex items-center justify-between">
                        <div className="space-y-0.5">
                          <span className="text-xs font-bold text-slate-300">
                            Capture LLM Content in Traces (AION_OTEL_TRACE_CONTENT)
                          </span>
                          <p className="text-[11px] text-slate-400">
                            Records user prompts and generated assistant outputs in span attributes.
                          </p>
                        </div>
                        <button
                          type="button"
                          onClick={() =>
                            setConfigSettings((prev) => ({
                              ...prev,
                              AION_OTEL_TRACE_CONTENT:
                                prev.AION_OTEL_TRACE_CONTENT === "1" ? "0" : "1",
                            }))
                          }
                          className={`w-9 h-5 rounded-full transition-colors relative cursor-pointer ${configSettings.AION_OTEL_TRACE_CONTENT === "1"
                            ? "bg-indigo-600"
                            : "bg-slate-700"
                            }`}
                        >
                          <span
                            className={`w-3.5 h-3.5 bg-white rounded-full absolute top-0.75 transition-transform ${configSettings.AION_OTEL_TRACE_CONTENT === "1"
                              ? "left-5"
                              : "left-0.75"
                              }`}
                          />
                        </button>
                      </div>
                    </div>
                  )}

                  {/* TAB 3: OPIK */}
                  {configTab === "opik" && (
                    <div className="space-y-4">
                      {/* OPIK ENABLED TOGGLE */}
                      <div className="p-4 rounded-2xl bg-[#14141d] border border-white/5 flex items-center justify-between">
                        <div className="space-y-0.5">
                          <span className="text-xs font-bold text-slate-200">
                            Enable Opik (Comet ML) LLM Telemetry
                          </span>
                          <p className="text-[11px] text-slate-400">
                            Self-hosted LLM prompt library versioning, tracing, and session feedback scores.
                          </p>
                        </div>
                        <button
                          type="button"
                          onClick={() =>
                            setConfigSettings((prev) => ({
                              ...prev,
                              AION_OPIK_ENABLED:
                                prev.AION_OPIK_ENABLED === "1" ? "0" : "1",
                            }))
                          }
                          className={`w-11 h-6 rounded-full transition-colors relative cursor-pointer ${configSettings.AION_OPIK_ENABLED === "1"
                            ? "bg-cyan-600"
                            : "bg-slate-700"
                            }`}
                        >
                          <span
                            className={`w-4 h-4 bg-white rounded-full absolute top-1 transition-transform ${configSettings.AION_OPIK_ENABLED === "1"
                              ? "left-6"
                              : "left-1"
                              }`}
                          />
                        </button>
                      </div>

                      {/* OPIK URL OVERRIDE */}
                      <div className="space-y-1.5">
                        <div className="flex items-center justify-between">
                          <label className="text-xs font-bold text-slate-200">
                            Opik Endpoint URL (OPIK_URL_OVERRIDE)
                          </label>
                          <span className="text-[10px] font-mono text-cyan-400">OPIK_URL_OVERRIDE</span>
                        </div>
                        <div className="flex items-center gap-2">
                          <input
                            type="text"
                            value={configSettings.OPIK_URL_OVERRIDE || ""}
                            onChange={(e) =>
                              setConfigSettings((prev) => ({
                                ...prev,
                                OPIK_URL_OVERRIDE: e.target.value,
                              }))
                            }
                            placeholder="http://localhost:5173/api"
                            className="bg-[#16161f] border border-white/10 rounded-xl px-3.5 py-2 text-xs font-mono text-white w-full outline-none focus:border-cyan-500 transition-all shadow-inner"
                          />
                          <button
                            type="button"
                            onClick={() => handleProbeConnection("opik")}
                            disabled={configProbing.opik}
                            className="px-3.5 py-2 rounded-xl bg-cyan-950/50 border border-cyan-500/40 text-cyan-300 hover:bg-cyan-900/60 text-xs font-bold transition-all whitespace-nowrap cursor-pointer disabled:opacity-50 flex items-center gap-1.5"
                          >
                            {configProbing.opik ? (
                              <Loader2 className="w-3.5 h-3.5 animate-spin" />
                            ) : (
                              <Play className="w-3.5 h-3.5" />
                            )}
                            <span>Test Opik</span>
                          </button>
                        </div>

                        {/* PROBE RESULT BADGE */}
                        {configProbeResults.opik && (
                          <div
                            className={`mt-2 p-2.5 rounded-xl border text-xs flex items-center justify-between gap-2 ${configProbeResults.opik.success
                              ? "bg-emerald-950/30 border-emerald-500/30 text-emerald-300"
                              : "bg-red-950/30 border-red-500/30 text-red-300"
                              }`}
                          >
                            <div className="flex items-center gap-2">
                              {configProbeResults.opik.success ? (
                                <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
                              ) : (
                                <AlertTriangle className="w-4 h-4 text-red-400 shrink-0" />
                              )}
                              <span>{configProbeResults.opik.message}</span>
                            </div>
                            {configProbeResults.opik.latency_ms !== undefined && (
                              <span className="font-mono text-[11px] font-bold">
                                {configProbeResults.opik.latency_ms} ms
                              </span>
                            )}
                          </div>
                        )}
                      </div>

                      {/* GRID: PROJECT NAME & API KEY */}
                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                        {/* PROJECT NAME */}
                        <div className="space-y-1">
                          <label className="text-xs font-bold text-slate-300">
                            Project Name (OPIK_PROJECT_NAME)
                          </label>
                          <input
                            type="text"
                            value={configSettings.OPIK_PROJECT_NAME || "AION-Agent"}
                            onChange={(e) =>
                              setConfigSettings((prev) => ({
                                ...prev,
                                OPIK_PROJECT_NAME: e.target.value,
                              }))
                            }
                            placeholder="AION-Agent"
                            className="w-full bg-[#16161f] border border-white/10 rounded-xl px-3 py-2 text-xs font-mono text-white outline-none focus:border-cyan-500"
                          />
                        </div>

                        {/* API KEY */}
                        <div className="space-y-1">
                          <label className="text-xs font-bold text-slate-300">
                            Opik API Key (OPIK_API_KEY)
                          </label>
                          <div className="relative">
                            <input
                              type={showOpikApiKey ? "text" : "password"}
                              value={configSettings.OPIK_API_KEY || ""}
                              onChange={(e) =>
                                setConfigSettings((prev) => ({
                                  ...prev,
                                  OPIK_API_KEY: e.target.value,
                                }))
                              }
                              placeholder="local-self-hosted-placeholder"
                              className="w-full bg-[#16161f] border border-white/10 rounded-xl px-3 py-2 pr-9 text-xs font-mono text-white outline-none focus:border-cyan-500"
                            />
                            <button
                              type="button"
                              onClick={() => setShowOpikApiKey(!showOpikApiKey)}
                              className="absolute right-2.5 top-2.5 text-slate-400 hover:text-white"
                              title={showOpikApiKey ? "Hide key" : "Show key"}
                            >
                              {showOpikApiKey ? (
                                <EyeOff className="w-3.5 h-3.5" />
                              ) : (
                                <Eye className="w-3.5 h-3.5" />
                              )}
                            </button>
                          </div>
                        </div>
                      </div>
                    </div>
                  )}
                </>
              )}
            </div>

            {/* MODAL FOOTER */}
            <div className="px-6 py-4 border-t border-white/10 bg-[#13131a] flex items-center justify-between">
              <span className="text-[11px] text-slate-500">
                Changes will be saved to <strong className="text-slate-400 font-mono">data/runtime.env</strong>
              </span>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => setShowConfigModal(false)}
                  className="px-4 py-2 rounded-xl border border-white/10 bg-slate-900 hover:bg-white/10 text-slate-300 hover:text-white text-xs font-bold transition-all cursor-pointer"
                >
                  Close
                </button>
                <button
                  type="button"
                  onClick={handleSaveConfig}
                  disabled={configSaving || configLoading}
                  className="px-5 py-2 rounded-xl bg-purple-600 hover:bg-purple-500 text-white text-xs font-bold transition-all shadow-lg shadow-purple-900/40 cursor-pointer disabled:opacity-50 flex items-center gap-2"
                >
                  {configSaving ? (
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  ) : (
                    <Save className="w-3.5 h-3.5" />
                  )}
                  <span>Save Configuration</span>
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* REINITIALIZING AI KERNEL OVERLAY */}
      {restarting && (
        <div className="fixed inset-0 bg-black/80 backdrop-blur-md flex flex-col items-center justify-center z-50 animate-in fade-in duration-300">
          <div className="bg-[#0d0d0d] border border-[#262626] rounded-3xl p-8 max-w-md w-full text-center space-y-6 shadow-2xl shadow-purple-500/10">
            <div className="relative w-20 h-20 mx-auto">
              <div className="absolute inset-0 border-4 border-purple-500/20 rounded-full" />
              <div className="absolute inset-0 border-4 border-t-purple-500 rounded-full animate-spin" />
            </div>
            <div className="space-y-2">
              <h3 className="text-xl font-bold text-white">Reinitializing AI Kernel</h3>
              <p className="text-sm text-slate-400">
                The API container is restarting to apply the new telemetry and observability configurations. This usually takes about few minutes.
              </p>
            </div>
            <div className="text-[10px] font-bold uppercase tracking-widest text-purple-400 bg-purple-500/10 border border-purple-500/20 px-3.5 py-1.5 rounded-full inline-block animate-pulse">
              Waiting for health check...
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
