"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "@/lib/api/headers";
import { apiBase } from "@/lib/api";
import {
  embeddingProviderToProbeProvider,
  probeBaseUrlFromOcrServiceUrl,
  probeBaseUrlFromServiceUrl,
} from "@/lib/llm-probe";

export type LlmProviderItem = {
  id: string;
  slug: string;
  display_name: string;
  provider: string;
  model_name: string;
  api_base_url?: string | null;
  enabled: boolean;
  is_default: boolean;
};

export type ProbeResult = {
  status: "checking" | "online" | "offline";
  latency_ms?: number;
  error?: string;
  local?: boolean;
};

export type SeriesPoint = { timestamp: string; value: number };

export type MetricsOverview = {
  prometheus_connected: boolean;
  total_tokens: number;
  total_turns: number;
  avg_turn_duration_seconds: number;
  p95_turn_duration_seconds: number;
  total_tool_calls: number;
  tool_success_rate: number;
  total_failures: number;
  profile_metrics: { profile: string; total_turns: number }[];
  mcp_call_errors: { mcp_server: string; tool_name: string; error_count: number; error_message?: string | null }[];
  tokens_series: SeriesPoint[];
  turns_series: SeriesPoint[];
  turn_duration_series: SeriesPoint[];
};

export type Stats = {
  active_profiles?: number;
  total_skills?: number;
  installed_mcp?: number;
  total_projects?: number;
  cron_jobs?: { total: number; enabled: number };
  api_keys?: { total: number };
};

export type Health = {
  redis?: { connected?: boolean; url?: string | null; type?: string; namespace?: string };
  database?: { url?: string; size_bytes?: number };
  storage?: { backend?: string; local_root?: string };
};

export type CronJob = {
  job_id: string;
  name: string;
  enabled: boolean;
  last_run?: { status?: string; started_at?: string; error_message?: string | null } | null;
};

export type FeedbackItem = {
  message_id: string;
  rating: number | null;
  feedback_comment?: string | null;
  created_at?: string;
  profile_name?: string;
};

export type McpRegistry = Record<string, { is_base?: boolean; disabled?: boolean; enabled?: boolean }>;

export type AdminUser = { id: string; identifier: string; last_active_at?: string | null };

export type DashboardData = {
  stats: Stats | null;
  health: Health | null;
  providers: LlmProviderItem[];
  settings: Record<string, string>;
  probes: Record<string, ProbeResult>;
  metrics: MetricsOverview | null;
  jobs: CronJob[] | null;
  feedback: FeedbackItem[] | null;
  users: AdminUser[] | null;
  registry: McpRegistry | null;
  loading: boolean;
  refreshing: boolean;
  failed: boolean;
  lastUpdated: Date | null;
  refresh: () => void;
};

async function getJson<T>(path: string): Promise<T | null> {
  try {
    const res = await apiFetch(`${apiBase()}${path}`);
    return res.ok ? ((await res.json()) as T) : null;
  } catch {
    return null;
  }
}

async function probe(body: Record<string, unknown>): Promise<ProbeResult> {
  try {
    const res = await apiFetch(`${apiBase()}/admin/llm-providers/probe`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (res.ok) {
      const data = await res.json();
      return { status: "online", latency_ms: data.latency_ms ? Math.round(data.latency_ms) : undefined };
    }
    const err = await res.json().catch(() => ({}));
    return { status: "offline", error: typeof err.detail === "string" ? err.detail : undefined };
  } catch (e) {
    return { status: "offline", error: e instanceof Error ? e.message : undefined };
  }
}

const REFRESH_MS = 60_000;

export function useDashboardData(): DashboardData {
  const [stats, setStats] = useState<Stats | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [providers, setProviders] = useState<LlmProviderItem[]>([]);
  const [settings, setSettings] = useState<Record<string, string>>({});
  const [probes, setProbes] = useState<Record<string, ProbeResult>>({});
  const [metrics, setMetrics] = useState<MetricsOverview | null>(null);
  const [jobs, setJobs] = useState<CronJob[] | null>(null);
  const [feedback, setFeedback] = useState<FeedbackItem[] | null>(null);
  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [registry, setRegistry] = useState<McpRegistry | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [failed, setFailed] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  const runProbes = useCallback(async (list: LlmProviderItem[], s: Record<string, string>) => {
    const enabled = list.filter((p) => p.enabled);
    const ocrUrl = (s.AION_OCR_BASE_URL || "").trim();
    setProbes((prev) => {
      const next: Record<string, ProbeResult> = {};
      for (const p of enabled) next[p.slug] = { ...prev[p.slug], status: "checking" };
      next.embeddings = { ...prev.embeddings, status: "checking" };
      next.ocr = ocrUrl ? { ...prev.ocr, status: "checking" } : { status: "online", local: true };
      return next;
    });
    const set = (key: string, r: ProbeResult) => setProbes((prev) => ({ ...prev, [key]: r }));
    await Promise.all([
      ...enabled.map((p) =>
        probe({ slug: p.slug, provider: p.provider, api_base_url: p.api_base_url || undefined }).then((r) =>
          set(p.slug, r),
        ),
      ),
      probe({
        provider: embeddingProviderToProbeProvider(s.AION_EMBEDDINGS_PROVIDER || "openai"),
        api_base_url: probeBaseUrlFromServiceUrl(s.AION_EMBEDDING_URL || "") || undefined,
        api_key: (s.AION_EMBEDDINGS_API_KEY || "").trim() || undefined,
      }).then((r) => set("embeddings", r)),
      ocrUrl
        ? probe({
            provider: "vllm",
            api_base_url: probeBaseUrlFromOcrServiceUrl(ocrUrl) || undefined,
            api_key: (s.AION_OCR_API_KEY || "").trim() || undefined,
          }).then((r) => set("ocr", r))
        : Promise.resolve(),
    ]);
  }, []);

  const load = useCallback(async () => {
    const [st, he, pr, se, me, jo, fb, us, rg] = await Promise.all([
      getJson<Stats>("/admin/stats"),
      getJson<Health>("/admin/system/health"),
      getJson<LlmProviderItem[]>("/admin/llm-providers"),
      getJson<{ settings?: Record<string, string> }>("/admin/settings"),
      getJson<MetricsOverview>("/admin/metrics/overview?time_range=24h"),
      getJson<{ jobs: CronJob[] }>("/admin/cron-jobs?limit=200"),
      getJson<{ feedback: FeedbackItem[] }>("/admin/feedback"),
      getJson<{ users: AdminUser[] }>("/admin/users"),
      getJson<McpRegistry>("/admin/registry"),
    ]);
    setStats(st);
    setHealth(he);
    const list = Array.isArray(pr) ? pr : [];
    setProviders(list);
    const s = se?.settings || {};
    setSettings(s);
    setMetrics(me);
    setJobs(jo?.jobs ?? null);
    setFeedback(fb?.feedback ?? null);
    setUsers(us?.users ?? null);
    setRegistry(rg);
    setFailed(!st && !he && !pr);
    setLastUpdated(new Date());
    setLoading(false);
    setRefreshing(false);
    if (pr || se) void runProbes(list, s);
  }, [runProbes]);

  useEffect(() => {
    const first = setTimeout(() => void load(), 0);
    const id = setInterval(() => void load(), REFRESH_MS);
    return () => {
      clearTimeout(first);
      clearInterval(id);
    };
  }, [load]);

  return {
    stats,
    health,
    providers,
    settings,
    probes,
    metrics,
    jobs,
    feedback,
    users,
    registry,
    loading,
    refreshing,
    failed,
    lastUpdated,
    refresh: () => {
      setRefreshing(true);
      void load();
    },
  };
}
