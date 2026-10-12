"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import {
  ArrowRight,
  Zap,
  Globe,
  Users,
  Server,
  Database,
  HardDrive,
  RefreshCw,
  Activity,
  Settings,
  Plus,
  Clock,
  KeyRound,
  Brain,
  Bot,
  XCircle,
  ExternalLink,
  Layers,
  ScanLine,
} from "lucide-react";
import { apiFetch } from "@/lib/api/headers";
import { apiBase } from "@/lib/api";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";
import {
  embeddingProviderToProbeProvider,
  probeBaseUrlFromOcrServiceUrl,
  probeBaseUrlFromServiceUrl,
} from "@/lib/llm-probe";

interface LlmProviderItem {
  id: string;
  slug: string;
  display_name: string;
  provider: string;
  model_name: string;
  api_base_url?: string | null;
  enabled: boolean;
  is_default: boolean;
  timeout?: number;
}

interface ProbeResult {
  status: "checking" | "online" | "offline";
  latency_ms?: number;
  error?: string;
  warning?: string | null;
}

export default function Home() {
  const t = useT();

  const [stats, setStats] = useState<any>(null);
  const [health, setHealth] = useState<any>(null);
  const [settings, setSettings] = useState<Record<string, string>>({});
  const [llmProviders, setLlmProviders] = useState<LlmProviderItem[]>([]);
  const [probeResults, setProbeResults] = useState<Record<string, ProbeResult>>({});
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [probingModels, setProbingModels] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  // Probe single LLM provider
  const probeProvider = useCallback(async (provider: LlmProviderItem) => {
    setProbeResults((prev) => ({
      ...prev,
      [provider.slug]: { status: "checking" },
    }));

    try {
      const res = await apiFetch(`${apiBase()}/admin/llm-providers/probe`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          slug: provider.slug,
          provider: provider.provider,
          api_base_url: provider.api_base_url || undefined,
        }),
      });

      if (res.ok) {
        const data = await res.json();
        setProbeResults((prev) => ({
          ...prev,
          [provider.slug]: {
            status: "online",
            latency_ms: data.latency_ms ? Math.round(data.latency_ms) : undefined,
            warning: data.warning || null,
          },
        }));
      } else {
        const errData = await res.json().catch(() => ({}));
        setProbeResults((prev) => ({
          ...prev,
          [provider.slug]: {
            status: "offline",
            error: errData.detail || t("admin_dashboard.models.error_fallback"),
          },
        }));
      }
    } catch (e: any) {
      setProbeResults((prev) => ({
        ...prev,
        [provider.slug]: {
          status: "offline",
          error: e.message || t("admin_dashboard.models.error_network"),
        },
      }));
    }
  }, [t]);

  // Probe Embeddings service
  const probeEmbeddings = useCallback(async (settingsMap: Record<string, string>) => {
    setProbeResults((prev) => ({
      ...prev,
      embeddings: { status: "checking" },
    }));

    const rawUrl = settingsMap.AION_EMBEDDING_URL || "";
    const probeBase = probeBaseUrlFromServiceUrl(rawUrl);
    const embProvider = embeddingProviderToProbeProvider(settingsMap.AION_EMBEDDINGS_PROVIDER || "openai");
    const apiKey = (settingsMap.AION_EMBEDDINGS_API_KEY || "").trim();

    try {
      const res = await apiFetch(`${apiBase()}/admin/llm-providers/probe`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          provider: embProvider,
          api_base_url: probeBase || undefined,
          api_key: apiKey || undefined,
        }),
      });

      if (res.ok) {
        const data = await res.json();
        setProbeResults((prev) => ({
          ...prev,
          embeddings: {
            status: "online",
            latency_ms: data.latency_ms ? Math.round(data.latency_ms) : undefined,
            warning: data.warning || null,
          },
        }));
      } else {
        const errData = await res.json().catch(() => ({}));
        setProbeResults((prev) => ({
          ...prev,
          embeddings: {
            status: "offline",
            error: errData.detail || t("admin_dashboard.models.error_fallback"),
          },
        }));
      }
    } catch (e: any) {
      setProbeResults((prev) => ({
        ...prev,
        embeddings: {
          status: "offline",
          error: e.message || t("admin_dashboard.models.error_network"),
        },
      }));
    }
  }, [t]);

  // Probe OCR service
  const probeOcr = useCallback(async (settingsMap: Record<string, string>) => {
    const rawOcrUrl = (settingsMap.AION_OCR_BASE_URL || "").trim();

    // Se OCR è locale, è sempre operativo
    if (!rawOcrUrl) {
      setProbeResults((prev) => ({
        ...prev,
        ocr: { status: "online", latency_ms: 1 },
      }));
      return;
    }

    setProbeResults((prev) => ({
      ...prev,
      ocr: { status: "checking" },
    }));

    const probeBase = probeBaseUrlFromOcrServiceUrl(rawOcrUrl);
    const apiKey = (settingsMap.AION_OCR_API_KEY || "").trim();

    try {
      const res = await apiFetch(`${apiBase()}/admin/llm-providers/probe`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          provider: "vllm",
          api_base_url: probeBase || undefined,
          api_key: apiKey || undefined,
        }),
      });

      if (res.ok) {
        const data = await res.json();
        setProbeResults((prev) => ({
          ...prev,
          ocr: {
            status: "online",
            latency_ms: data.latency_ms ? Math.round(data.latency_ms) : undefined,
            warning: data.warning || null,
          },
        }));
      } else {
        const errData = await res.json().catch(() => ({}));
        setProbeResults((prev) => ({
          ...prev,
          ocr: {
            status: "offline",
            error: errData.detail || t("admin_dashboard.models.error_fallback"),
          },
        }));
      }
    } catch (e: any) {
      setProbeResults((prev) => ({
        ...prev,
        ocr: {
          status: "offline",
          error: e.message || t("admin_dashboard.models.error_network"),
        },
      }));
    }
  }, [t]);

  // Probe all AI endpoints
  const probeAllEndpoints = useCallback(
    async (providersList: LlmProviderItem[], settingsMap: Record<string, string>) => {
      setProbingModels(true);
      try {
        await Promise.all([
          ...providersList.map((p) => probeProvider(p)),
          probeEmbeddings(settingsMap),
          probeOcr(settingsMap),
        ]);
      } finally {
        setProbingModels(false);
      }
    },
    [probeProvider, probeEmbeddings, probeOcr]
  );

  // Fetch all dashboard data
  const fetchData = useCallback(async () => {
    setRefreshing(true);
    try {
      const [statsRes, healthRes, providersRes, settingsRes] = await Promise.all([
        apiFetch(`${apiBase()}/admin/stats`),
        apiFetch(`${apiBase()}/admin/system/health`),
        apiFetch(`${apiBase()}/admin/llm-providers`),
        apiFetch(`${apiBase()}/admin/settings`),
      ]);

      const [statsData, healthData, providersData, settingsData] = await Promise.all([
        statsRes.ok ? statsRes.json() : null,
        healthRes.ok ? healthRes.json() : null,
        providersRes.ok ? providersRes.json() : null,
        settingsRes.ok ? settingsRes.json() : null,
      ]);

      if (statsData) setStats(statsData);
      if (healthData) setHealth(healthData);

      const loadedSettings = settingsData?.settings || {};
      setSettings(loadedSettings);

      const loadedProviders = Array.isArray(providersData) ? providersData : [];
      setLlmProviders(loadedProviders);

      void probeAllEndpoints(loadedProviders, loadedSettings);
      setLastUpdated(new Date());
    } catch (err) {
      console.error("Dashboard data fetch failed", err);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [probeAllEndpoints]);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 60000);
    return () => clearInterval(interval);
  }, [fetchData]);

  const cronTotal = stats?.cron_jobs?.total !== undefined ? stats.cron_jobs.total : "...";
  const cronEnabled = stats?.cron_jobs?.enabled !== undefined ? stats.cron_jobs.enabled : "...";
  const apiKeysTotal = stats?.api_keys?.total !== undefined ? stats.api_keys.total : "...";
  const projectsTotal = stats?.total_projects !== undefined ? stats.total_projects : "...";
  const skillsCount = stats?.total_skills !== undefined ? stats.total_skills : "...";

  const statItems = [
    {
      name: t("admin_dashboard.kpi.profiles_title"),
      value: stats?.active_profiles !== undefined ? stats.active_profiles : "...",
      icon: Users,
      color: "border-sky-500/25 bg-sky-500/10 text-sky-500 dark:text-sky-400",
      accentBorder: "hover:border-sky-500/40",
      href: "/profiles",
      description: t("admin_dashboard.kpi.profiles_desc"),
    },
    {
      name: t("admin_dashboard.kpi.skills_title"),
      value: skillsCount,
      icon: Zap,
      color: "border-purple-500/25 bg-purple-500/10 text-purple-500 dark:text-purple-400",
      accentBorder: "hover:border-purple-500/40",
      href: "/skills",
      description: t("admin_dashboard.kpi.skills_desc"),
    },
    {
      name: t("admin_dashboard.kpi.mcp_title"),
      value: stats?.installed_mcp !== undefined ? stats.installed_mcp : "...",
      icon: Globe,
      color: "border-emerald-500/25 bg-emerald-500/10 text-emerald-500 dark:text-emerald-400",
      accentBorder: "hover:border-emerald-500/40",
      href: "/hub",
      description: t("admin_dashboard.kpi.mcp_desc"),
    },
    {
      name: t("admin_dashboard.kpi.memory_title"),
      value: projectsTotal,
      icon: Brain,
      color: "border-indigo-500/25 bg-indigo-500/10 text-indigo-500 dark:text-indigo-400",
      accentBorder: "hover:border-indigo-500/40",
      href: "/memory",
      description: t("admin_dashboard.kpi.memory_desc"),
    },
    {
      name: t("admin_dashboard.kpi.schedules_title"),
      value: cronTotal !== "..." ? `${cronEnabled}/${cronTotal}` : "...",
      icon: Clock,
      color: "border-amber-500/25 bg-amber-500/10 text-amber-500 dark:text-amber-400",
      accentBorder: "hover:border-amber-500/40",
      href: "/schedules",
      description: t("admin_dashboard.kpi.schedules_desc"),
    },
    {
      name: t("admin_dashboard.kpi.api_keys_title"),
      value: apiKeysTotal,
      icon: KeyRound,
      color: "border-cyan-500/25 bg-cyan-500/10 text-cyan-500 dark:text-cyan-400",
      accentBorder: "hover:border-cyan-500/40",
      href: "/api-keys",
      description: t("admin_dashboard.kpi.api_keys_desc"),
    },
  ];

  // Helper formatting for memory size
  const formatBytes = (bytes: number) => {
    if (bytes === undefined || bytes === null || bytes <= 0) return "N/A";
    const mb = bytes / (1024 * 1024);
    return `${mb.toFixed(2)} MB`;
  };

  // Integrità del Sistema status
  const isRedisHealthy = !!health?.redis?.connected;
  const isDbHealthy = !loading && health?.database !== undefined;
  const isStorageHealthy = !loading && health?.storage !== undefined;

  // Servizi aggiuntivi AI (Embeddings & OCR)
  const hasRemoteOcr = !!(settings.AION_OCR_BASE_URL || "").trim();
  const totalAiServicesCount = llmProviders.length + 2; // LLM + Embeddings + OCR

  const embProbe = probeResults["embeddings"];
  const ocrProbe = probeResults["ocr"];

  return (
    <div className="space-y-8 animate-in fade-in duration-300">
      {/* Header Dashboard */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-border/60 pb-6">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-[10px] font-bold uppercase tracking-[0.2em] text-muted-foreground">
              {t("admin_dashboard.badge")}
            </span>
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse" />
          </div>
          <h1 className="text-2xl sm:text-3xl font-black text-foreground tracking-tight mt-1">
            {t("admin_dashboard.title")}
          </h1>
          <p className="text-muted-foreground text-xs sm:text-sm mt-0.5">
            {t("admin_dashboard.subtitle")}
          </p>
        </div>

        {/* Pulsanti Azione Header */}
        <div className="flex items-center gap-2.5 shrink-0">
          {lastUpdated ? (
            <span className="text-[11px] font-mono text-muted-foreground hidden md:inline">
              {t("admin_dashboard.updated_at")}{" "}
              {lastUpdated.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
            </span>
          ) : null}

          <button
            type="button"
            onClick={() => void fetchData()}
            disabled={refreshing}
            className="focus-ring inline-flex items-center gap-1.5 rounded-xl border border-border/80 bg-card/60 px-3 py-1.5 text-xs font-semibold text-foreground hover:bg-muted transition cursor-pointer shadow-2xs"
            title={t("admin_dashboard.refresh_all_tooltip")}
          >
            <RefreshCw className={cn("h-3.5 w-3.5", refreshing && "animate-spin text-primary")} />
            <span>{t("admin_dashboard.refresh")}</span>
          </button>

          <Link
            href="/settings"
            className="focus-ring inline-flex items-center gap-1.5 rounded-xl border border-primary/30 bg-primary/10 px-3 py-1.5 text-xs font-semibold text-primary hover:bg-primary/20 transition cursor-pointer shadow-2xs"
          >
            <Settings className="h-3.5 w-3.5" />
            <span>{t("admin_dashboard.settings")}</span>
          </Link>
        </div>
      </div>

      {/* KPI Cards Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-6 gap-4">
        {statItems.map((stat) => (
          <Link
            key={stat.name}
            href={stat.href}
            className={cn(
              "group relative flex flex-col justify-between rounded-2xl border border-border/70 bg-card/40 p-5 shadow-xs transition-all duration-200 overflow-hidden",
              "before:absolute before:inset-x-0 before:top-0 before:h-px before:bg-gradient-to-r before:from-transparent before:via-white/15 before:to-transparent",
              "hover:-translate-y-0.5 hover:shadow-md dark:hover:shadow-black/40",
              stat.accentBorder,
            )}
          >
            <div>
              <div className="flex items-center justify-between mb-3">
                <div className={cn("flex h-10 w-10 items-center justify-center rounded-xl border transition-transform duration-200 group-hover:scale-105 shadow-2xs", stat.color)}>
                  <stat.icon className="h-5 w-5" />
                </div>
                <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/10 px-2 py-0.5 text-[10px] font-bold text-emerald-600 dark:text-emerald-400 border border-emerald-500/20">
                  <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                  {t("admin_dashboard.kpi.status_active")}
                </span>
              </div>

              <div className="text-3xl font-black tracking-tight text-foreground">
                {stat.value}
              </div>

              <div className="text-xs font-bold uppercase tracking-wider text-muted-foreground mt-1.5">
                {stat.name}
              </div>
            </div>

            <div className="mt-3 pt-2.5 border-t border-border/50 flex items-center justify-between text-[11px] text-muted-foreground/80 font-medium">
              <span className="truncate">{stat.description}</span>
              <ArrowRight className="h-3 w-3 opacity-0 -translate-x-1 transition-all group-hover:opacity-100 group-hover:translate-x-0 shrink-0" />
            </div>
          </Link>
        ))}
      </div>

      {/* System Integrity & Infrastructure Section con Bordi e Sfumature Colorate */}
      <div className="relative rounded-2xl border border-border/70 bg-card/40 p-5 shadow-xs overflow-hidden before:absolute before:inset-x-0 before:top-0 before:h-px before:bg-gradient-to-r before:from-transparent before:via-white/15 before:to-transparent">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-4 border-b border-border/60">
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg border border-sky-500/20 bg-sky-500/10 text-sky-500 dark:text-sky-400 shadow-2xs">
              <Activity className="h-4 w-4" />
            </div>
            <div>
              <h2 className="text-xs font-bold uppercase tracking-wider text-foreground">
                {t("admin_dashboard.system.title")}
              </h2>
              <p className="text-[11px] text-muted-foreground">
                {t("admin_dashboard.system.subtitle")}
              </p>
            </div>
          </div>

          <Link
            href="/system"
            className="text-xs font-semibold text-primary hover:text-primary/80 transition-colors flex items-center gap-1 self-start sm:self-auto"
          >
            <span>{t("admin_dashboard.system.diagnostic_details")}</span>
            <ArrowRight className="h-3 w-3" />
          </Link>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 pt-4">
          {/* Redis Health Card */}
          <div
            className={cn(
              "relative flex items-start gap-4 p-4 rounded-xl border transition-all duration-200 overflow-hidden shadow-xs hover:shadow-md",
              "before:absolute before:inset-x-0 before:top-0 before:h-0.5 before:bg-gradient-to-r before:from-transparent before:to-transparent",
              isRedisHealthy
                ? "border-emerald-500/35 bg-gradient-to-br from-emerald-500/[0.08] via-card/80 to-background/50 hover:border-emerald-500/55 shadow-emerald-500/5 before:via-emerald-500/70"
                : "border-destructive/40 bg-gradient-to-br from-destructive/[0.08] via-card/80 to-background/50 hover:border-destructive/60 shadow-destructive/5 before:via-destructive/70",
            )}
          >
            <div
              className={cn(
                "flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border shadow-2xs transition-transform group-hover:scale-105",
                isRedisHealthy
                  ? "border-emerald-500/30 bg-emerald-500/15 text-emerald-500 dark:text-emerald-400"
                  : "border-destructive/30 bg-destructive/15 text-destructive",
              )}
            >
              <Server className="h-5 w-5" />
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs font-bold text-foreground tracking-tight">
                  {t("admin_dashboard.system.redis_title")}
                </span>
                {loading ? (
                  <span className="text-[10px] font-mono text-muted-foreground">
                    {t("admin_dashboard.system.status_checking")}
                  </span>
                ) : isRedisHealthy ? (
                  <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/15 px-2.5 py-0.5 text-[10px] font-bold text-emerald-600 dark:text-emerald-400 border border-emerald-500/30 shadow-2xs">
                    <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse" />
                    {t("admin_dashboard.system.status_operational")}
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1 rounded-full bg-destructive/15 px-2.5 py-0.5 text-[10px] font-bold text-destructive border border-destructive/30 shadow-2xs">
                    <span className="h-1.5 w-1.5 rounded-full bg-destructive" />
                    {t("admin_dashboard.system.status_offline")}
                  </span>
                )}
              </div>
              <p className="text-[11px] font-mono text-muted-foreground truncate mt-1">
                {health?.redis?.url ? health.redis.url.replace(/:\/\/.*@/, "://") : "redis://redis:6379/0"}
              </p>
              <div className="text-[10px] text-muted-foreground/80 mt-0.5 font-medium">
                {t("admin_dashboard.system.redis_type", {
                  type: health?.redis?.type || "Redis asyncio",
                  namespace: health?.redis?.namespace || "aion",
                })}
              </div>
            </div>
          </div>

          {/* Database SQLite Card */}
          <div
            className={cn(
              "relative flex items-start gap-4 p-4 rounded-xl border transition-all duration-200 overflow-hidden shadow-xs hover:shadow-md",
              "before:absolute before:inset-x-0 before:top-0 before:h-0.5 before:bg-gradient-to-r before:from-transparent before:to-transparent",
              isDbHealthy
                ? "border-emerald-500/35 bg-gradient-to-br from-emerald-500/[0.08] via-card/80 to-background/50 hover:border-emerald-500/55 shadow-emerald-500/5 before:via-emerald-500/70"
                : "border-destructive/40 bg-gradient-to-br from-destructive/[0.08] via-card/80 to-background/50 hover:border-destructive/60 shadow-destructive/5 before:via-destructive/70",
            )}
          >
            <div
              className={cn(
                "flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border shadow-2xs",
                isDbHealthy
                  ? "border-emerald-500/30 bg-emerald-500/15 text-emerald-500 dark:text-emerald-400"
                  : "border-destructive/30 bg-destructive/15 text-destructive",
              )}
            >
              <Database className="h-5 w-5" />
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs font-bold text-foreground tracking-tight">
                  {t("admin_dashboard.system.database_title")}
                </span>
                {loading ? (
                  <span className="text-[10px] font-mono text-muted-foreground">
                    {t("admin_dashboard.system.status_checking")}
                  </span>
                ) : isDbHealthy ? (
                  <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/15 px-2.5 py-0.5 text-[10px] font-bold text-emerald-600 dark:text-emerald-400 border border-emerald-500/30 shadow-2xs">
                    <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                    {t("admin_dashboard.system.status_operational")}
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1 rounded-full bg-destructive/15 px-2.5 py-0.5 text-[10px] font-bold text-destructive border border-destructive/30 shadow-2xs">
                    <span className="h-1.5 w-1.5 rounded-full bg-destructive" />
                    {t("admin_dashboard.system.status_offline")}
                  </span>
                )}
              </div>
              <p className="text-[11px] font-mono text-muted-foreground truncate mt-1">
                data/aion.db ({formatBytes(health?.database?.size_bytes)})
              </p>
              <div className="text-[10px] text-muted-foreground/80 mt-0.5 font-medium">
                {t("admin_dashboard.system.database_arch")}
              </div>
            </div>
          </div>

          {/* Storage Sandbox Card */}
          <div
            className={cn(
              "relative flex items-start gap-4 p-4 rounded-xl border transition-all duration-200 overflow-hidden shadow-xs hover:shadow-md",
              "before:absolute before:inset-x-0 before:top-0 before:h-0.5 before:bg-gradient-to-r before:from-transparent before:to-transparent",
              isStorageHealthy
                ? "border-emerald-500/35 bg-gradient-to-br from-emerald-500/[0.08] via-card/80 to-background/50 hover:border-emerald-500/55 shadow-emerald-500/5 before:via-emerald-500/70"
                : "border-destructive/40 bg-gradient-to-br from-destructive/[0.08] via-card/80 to-background/50 hover:border-destructive/60 shadow-destructive/5 before:via-destructive/70",
            )}
          >
            <div
              className={cn(
                "flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border shadow-2xs",
                isStorageHealthy
                  ? "border-emerald-500/30 bg-emerald-500/15 text-emerald-500 dark:text-emerald-400"
                  : "border-destructive/30 bg-destructive/15 text-destructive",
              )}
            >
              <HardDrive className="h-5 w-5" />
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs font-bold text-foreground tracking-tight">
                  {t("admin_dashboard.system.storage_title")}
                </span>
                {loading ? (
                  <span className="text-[10px] font-mono text-muted-foreground">
                    {t("admin_dashboard.system.status_checking")}
                  </span>
                ) : isStorageHealthy ? (
                  <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/15 px-2.5 py-0.5 text-[10px] font-bold text-emerald-600 dark:text-emerald-400 border border-emerald-500/30 shadow-2xs">
                    <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                    {t("admin_dashboard.system.status_operational")}
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1 rounded-full bg-destructive/15 px-2.5 py-0.5 text-[10px] font-bold text-destructive border border-destructive/30 shadow-2xs">
                    <span className="h-1.5 w-1.5 rounded-full bg-destructive" />
                    {t("admin_dashboard.system.status_offline")}
                  </span>
                )}
              </div>
              <p className="text-[11px] font-mono text-muted-foreground truncate mt-1">
                {t("admin_dashboard.system.storage_backend", {
                  backend: health?.storage?.backend?.toUpperCase() || "LOCAL",
                })}
              </p>
              <div className="text-[10px] text-muted-foreground/80 mt-0.5 font-medium">
                {t("admin_dashboard.system.storage_workspaces")}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Model & AI Services Health Check Section (LLM, Embeddings, OCR) */}
      <div className="relative rounded-2xl border border-border/70 bg-card/40 p-5 shadow-xs overflow-hidden before:absolute before:inset-x-0 before:top-0 before:h-px before:bg-gradient-to-r before:from-transparent before:via-white/15 before:to-transparent">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-4 border-b border-border/60">
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg border border-purple-500/20 bg-purple-500/10 text-purple-500 dark:text-purple-400 shadow-2xs">
              <Bot className="h-4 w-4" />
            </div>
            <div>
              <h2 className="text-xs font-bold uppercase tracking-wider text-foreground flex items-center gap-2">
                <span>{t("admin_dashboard.models.title")}</span>
                <span className="rounded-full bg-purple-500/10 px-2 py-0.2 text-[10px] font-bold text-purple-600 dark:text-purple-400 border border-purple-500/20">
                  {t("admin_dashboard.models.configured_services", { count: totalAiServicesCount })}
                </span>
              </h2>
              <p className="text-[11px] text-muted-foreground">
                {t("admin_dashboard.models.subtitle")}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2 self-start sm:self-auto">
            <button
              type="button"
              onClick={() => void probeAllEndpoints(llmProviders, settings)}
              disabled={probingModels}
              className="focus-ring inline-flex items-center gap-1.5 rounded-xl border border-border/80 bg-background/60 px-3 py-1.5 text-xs font-semibold text-foreground hover:bg-muted transition cursor-pointer shadow-2xs"
            >
              <RefreshCw className={cn("h-3 w-3", probingModels && "animate-spin text-primary")} />
              <span>{t("admin_dashboard.models.probe_now")}</span>
            </button>

            <Link
              href="/settings"
              className="focus-ring inline-flex items-center gap-1.5 rounded-xl border border-border/80 bg-background/60 px-3 py-1.5 text-xs font-semibold text-foreground hover:bg-muted transition cursor-pointer shadow-2xs"
            >
              <Settings className="h-3 w-3 text-muted-foreground" />
              <span>{t("admin_dashboard.models.manage_settings")}</span>
              <ExternalLink className="h-3 w-3 text-muted-foreground/60" />
            </Link>
          </div>
        </div>

        {/* AI Services Grid: LLM Providers + Embeddings + OCR */}
        <div className="pt-4 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {/* 1. Embeddings Service Card */}
          <div className="flex flex-col justify-between rounded-xl border border-sky-500/30 bg-gradient-to-b from-sky-500/[0.04] to-background/60 p-4 shadow-2xs hover:border-sky-500/50 transition-all">
            <div>
              <div className="flex items-start justify-between gap-2 mb-2">
                <div className="min-w-0">
                  <div className="flex items-center gap-1.5 mb-1">
                    <span className="inline-flex items-center rounded-md bg-sky-500/15 px-1.5 py-0.5 text-[9px] font-black uppercase text-sky-600 dark:text-sky-400 border border-sky-500/30">
                      <Layers className="h-2.5 w-2.5 mr-1" />
                      {t("admin_dashboard.models.kind_embedding")}
                    </span>
                  </div>
                  <h3 className="font-semibold text-sm text-foreground truncate">
                    {t("admin_dashboard.models.embeddings_default_name")}
                  </h3>
                  <div className="text-[11px] text-muted-foreground mt-0.5">
                    {t("admin_dashboard.models.provider_label")}{" "}
                    <span className="font-semibold text-foreground/80 uppercase">
                      {settings.AION_EMBEDDINGS_PROVIDER || "openai"}
                    </span>
                  </div>
                </div>

                {/* Status Badge */}
                <div className="shrink-0">
                  {embProbe?.status === "checking" ? (
                    <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-500/10 px-2 py-0.5 text-[10px] font-semibold text-amber-700 dark:text-amber-400 border border-amber-500/25">
                      <RefreshCw className="h-2.5 w-2.5 animate-spin" />
                      {t("admin_dashboard.models.checking")}
                    </span>
                  ) : embProbe?.status === "online" ? (
                    <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-500/10 px-2 py-0.5 text-[10px] font-semibold text-emerald-700 dark:text-emerald-400 border border-emerald-500/25">
                      <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse" />
                      {t("admin_dashboard.models.reachable")}{" "}
                      {embProbe.latency_ms ? `(${embProbe.latency_ms}ms)` : ""}
                    </span>
                  ) : embProbe?.status === "offline" ? (
                    <span
                      className="inline-flex items-center gap-1.5 rounded-full bg-destructive/10 px-2 py-0.5 text-[10px] font-semibold text-destructive border border-destructive/25"
                      title={embProbe.error}
                    >
                      <XCircle className="h-3 w-3" />
                      {t("admin_dashboard.models.unreachable")}
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1.5 rounded-full bg-muted/80 px-2 py-0.5 text-[10px] font-semibold text-muted-foreground border border-border/50">
                      {t("admin_dashboard.models.pending")}
                    </span>
                  )}
                </div>
              </div>

              {/* Model & Endpoint */}
              <div className="space-y-1.5 my-3 p-2.5 rounded-lg bg-muted/30 border border-border/40 text-xs">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[11px] text-muted-foreground">
                    {t("admin_dashboard.models.model_label")}
                  </span>
                  <span className="font-mono text-[11px] font-semibold text-foreground truncate">
                    {settings.AION_EMBEDDING_MODEL || "text-embedding-3-small"}
                  </span>
                </div>
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[11px] text-muted-foreground">
                    {t("admin_dashboard.models.endpoint_label")}
                  </span>
                  <span
                    className="font-mono text-[10px] text-muted-foreground truncate max-w-[200px]"
                    title={settings.AION_EMBEDDING_URL || "https://api.openai.com/v1/embeddings"}
                  >
                    {settings.AION_EMBEDDING_URL || "https://api.openai.com/v1/embeddings"}
                  </span>
                </div>
              </div>

              {embProbe?.status === "offline" && embProbe.error ? (
                <p className="text-[10px] text-destructive leading-tight mb-3 p-2 rounded bg-destructive/5 border border-destructive/20 line-clamp-2">
                  {embProbe.error}
                </p>
              ) : null}
            </div>

            <div className="pt-2.5 border-t border-border/50 flex items-center justify-between gap-2">
              <button
                type="button"
                onClick={() => void probeEmbeddings(settings)}
                disabled={embProbe?.status === "checking"}
                className="text-[11px] font-medium text-muted-foreground hover:text-foreground transition-colors flex items-center gap-1 cursor-pointer"
              >
                <RefreshCw className={cn("h-3 w-3", embProbe?.status === "checking" && "animate-spin")} />
                <span>{t("admin_dashboard.models.retest")}</span>
              </button>

              <Link
                href="/settings"
                className="text-[11px] font-semibold text-primary hover:text-primary/80 transition-colors flex items-center gap-1"
              >
                <span>{t("admin_dashboard.models.configure")}</span>
                <ArrowRight className="h-3 w-3" />
              </Link>
            </div>
          </div>

          {/* 2. OCR & Vision Service Card */}
          <div className="flex flex-col justify-between rounded-xl border border-amber-500/30 bg-gradient-to-b from-amber-500/[0.04] to-background/60 p-4 shadow-2xs hover:border-amber-500/50 transition-all">
            <div>
              <div className="flex items-start justify-between gap-2 mb-2">
                <div className="min-w-0">
                  <div className="flex items-center gap-1.5 mb-1">
                    <span className="inline-flex items-center rounded-md bg-amber-500/15 px-1.5 py-0.5 text-[9px] font-black uppercase text-amber-600 dark:text-amber-400 border border-amber-500/30">
                      <ScanLine className="h-2.5 w-2.5 mr-1" />
                      {t("admin_dashboard.models.kind_ocr")}
                    </span>
                  </div>
                  <h3 className="font-semibold text-sm text-foreground truncate">
                    {t("admin_dashboard.models.ocr_default_name")}
                  </h3>
                  <div className="text-[11px] text-muted-foreground mt-0.5">
                    {t("admin_dashboard.models.provider_label")}{" "}
                    <span className="font-semibold text-foreground/80 uppercase">
                      {hasRemoteOcr ? "vLLM Vision" : t("admin_dashboard.models.ocr_local_badge")}
                    </span>
                  </div>
                </div>

                {/* Status Badge */}
                <div className="shrink-0">
                  {ocrProbe?.status === "checking" ? (
                    <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-500/10 px-2 py-0.5 text-[10px] font-semibold text-amber-700 dark:text-amber-400 border border-amber-500/25">
                      <RefreshCw className="h-2.5 w-2.5 animate-spin" />
                      {t("admin_dashboard.models.checking")}
                    </span>
                  ) : ocrProbe?.status === "online" ? (
                    <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-500/10 px-2 py-0.5 text-[10px] font-semibold text-emerald-700 dark:text-emerald-400 border border-emerald-500/25">
                      <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse" />
                      {t("admin_dashboard.models.reachable")}{" "}
                      {ocrProbe.latency_ms && hasRemoteOcr ? `(${ocrProbe.latency_ms}ms)` : ""}
                    </span>
                  ) : ocrProbe?.status === "offline" ? (
                    <span
                      className="inline-flex items-center gap-1.5 rounded-full bg-destructive/10 px-2 py-0.5 text-[10px] font-semibold text-destructive border border-destructive/25"
                      title={ocrProbe.error}
                    >
                      <XCircle className="h-3 w-3" />
                      {t("admin_dashboard.models.unreachable")}
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1.5 rounded-full bg-muted/80 px-2 py-0.5 text-[10px] font-semibold text-muted-foreground border border-border/50">
                      {t("admin_dashboard.models.pending")}
                    </span>
                  )}
                </div>
              </div>

              {/* Model & Endpoint */}
              <div className="space-y-1.5 my-3 p-2.5 rounded-lg bg-muted/30 border border-border/40 text-xs">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[11px] text-muted-foreground">
                    {t("admin_dashboard.models.model_label")}
                  </span>
                  <span className="font-mono text-[11px] font-semibold text-foreground truncate">
                    {settings.AION_OCR_MODEL || (hasRemoteOcr ? "Vision Model" : "PyMuPDF / Tesseract")}
                  </span>
                </div>
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[11px] text-muted-foreground">
                    {t("admin_dashboard.models.endpoint_label")}
                  </span>
                  <span
                    className="font-mono text-[10px] text-muted-foreground truncate max-w-[200px]"
                    title={hasRemoteOcr ? settings.AION_OCR_BASE_URL : t("admin_dashboard.models.ocr_local_endpoint")}
                  >
                    {hasRemoteOcr ? settings.AION_OCR_BASE_URL : t("admin_dashboard.models.ocr_local_endpoint")}
                  </span>
                </div>
              </div>

              {ocrProbe?.status === "offline" && ocrProbe.error ? (
                <p className="text-[10px] text-destructive leading-tight mb-3 p-2 rounded bg-destructive/5 border border-destructive/20 line-clamp-2">
                  {ocrProbe.error}
                </p>
              ) : null}
            </div>

            <div className="pt-2.5 border-t border-border/50 flex items-center justify-between gap-2">
              <button
                type="button"
                onClick={() => void probeOcr(settings)}
                disabled={ocrProbe?.status === "checking"}
                className="text-[11px] font-medium text-muted-foreground hover:text-foreground transition-colors flex items-center gap-1 cursor-pointer"
              >
                <RefreshCw className={cn("h-3 w-3", ocrProbe?.status === "checking" && "animate-spin")} />
                <span>{t("admin_dashboard.models.retest")}</span>
              </button>

              <Link
                href="/settings"
                className="text-[11px] font-semibold text-primary hover:text-primary/80 transition-colors flex items-center gap-1"
              >
                <span>{t("admin_dashboard.models.configure")}</span>
                <ArrowRight className="h-3 w-3" />
              </Link>
            </div>
          </div>

          {/* 3. LLM Providers Cards */}
          {llmProviders.map((prov) => {
            const probe = probeResults[prov.slug];
            const isChecking = probe?.status === "checking";
            const isOnline = probe?.status === "online";
            const isOffline = probe?.status === "offline";

            return (
              <div
                key={prov.slug}
                className="flex flex-col justify-between rounded-xl border border-purple-500/25 bg-gradient-to-b from-purple-500/[0.03] to-background/60 p-4 shadow-2xs hover:border-purple-500/45 transition-all"
              >
                <div>
                  {/* Card Top: Nome e Badges */}
                  <div className="flex items-start justify-between gap-2 mb-2">
                    <div className="min-w-0">
                      <div className="flex items-center gap-1.5 mb-1">
                        <span className="inline-flex items-center rounded-md bg-purple-500/15 px-1.5 py-0.5 text-[9px] font-black uppercase text-purple-600 dark:text-purple-400 border border-purple-500/30">
                          <Bot className="h-2.5 w-2.5 mr-1" />
                          {t("admin_dashboard.models.kind_llm")}
                        </span>
                        {prov.is_default ? (
                          <span className="inline-flex items-center rounded-md bg-primary/10 px-1.5 py-0.5 text-[9px] font-bold text-primary border border-primary/25 uppercase">
                            {t("admin_dashboard.models.default_badge")}
                          </span>
                        ) : null}
                      </div>

                      <h3 className="font-semibold text-sm text-foreground truncate">
                        {prov.display_name}
                      </h3>
                      <div className="text-[11px] text-muted-foreground mt-0.5">
                        {t("admin_dashboard.models.provider_label")}{" "}
                        <span className="font-semibold text-foreground/80 uppercase">{prov.provider}</span>
                      </div>
                    </div>

                    {/* Status Badge */}
                    <div className="shrink-0">
                      {isChecking ? (
                        <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-500/10 px-2 py-0.5 text-[10px] font-semibold text-amber-700 dark:text-amber-400 border border-amber-500/25">
                          <RefreshCw className="h-2.5 w-2.5 animate-spin" />
                          {t("admin_dashboard.models.checking")}
                        </span>
                      ) : isOnline ? (
                        <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-500/10 px-2 py-0.5 text-[10px] font-semibold text-emerald-700 dark:text-emerald-400 border border-emerald-500/25">
                          <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse" />
                          {t("admin_dashboard.models.reachable")}{" "}
                          {probe.latency_ms ? `(${probe.latency_ms}ms)` : ""}
                        </span>
                      ) : isOffline ? (
                        <span
                          className="inline-flex items-center gap-1.5 rounded-full bg-destructive/10 px-2 py-0.5 text-[10px] font-semibold text-destructive border border-destructive/25"
                          title={probe.error}
                        >
                          <XCircle className="h-3 w-3" />
                          {t("admin_dashboard.models.unreachable")}
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1.5 rounded-full bg-muted/80 px-2 py-0.5 text-[10px] font-semibold text-muted-foreground border border-border/50">
                          {t("admin_dashboard.models.pending")}
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Model Name and Endpoint */}
                  <div className="space-y-1.5 my-3 p-2.5 rounded-lg bg-muted/30 border border-border/40 text-xs">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-[11px] text-muted-foreground">
                        {t("admin_dashboard.models.model_label")}
                      </span>
                      <span className="font-mono text-[11px] font-semibold text-foreground truncate">
                        {prov.model_name}
                      </span>
                    </div>
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-[11px] text-muted-foreground">
                        {t("admin_dashboard.models.endpoint_label")}
                      </span>
                      <span
                        className="font-mono text-[10px] text-muted-foreground truncate max-w-[200px]"
                        title={prov.api_base_url || t("admin_dashboard.models.cloud_standard_tooltip")}
                      >
                        {prov.api_base_url || t("admin_dashboard.models.cloud_standard")}
                      </span>
                    </div>
                  </div>

                  {/* Error message detail if offline */}
                  {isOffline && probe.error ? (
                    <p className="text-[10px] text-destructive leading-tight mb-3 p-2 rounded bg-destructive/5 border border-destructive/20 line-clamp-2">
                      {probe.error}
                    </p>
                  ) : null}
                </div>

                {/* Card Footer Actions */}
                <div className="pt-2.5 border-t border-border/50 flex items-center justify-between gap-2">
                  <button
                    type="button"
                    onClick={() => void probeProvider(prov)}
                    disabled={isChecking}
                    className="text-[11px] font-medium text-muted-foreground hover:text-foreground transition-colors flex items-center gap-1 cursor-pointer"
                  >
                    <RefreshCw className={cn("h-3 w-3", isChecking && "animate-spin")} />
                    <span>{t("admin_dashboard.models.retest")}</span>
                  </button>

                  <Link
                    href="/settings"
                    className="text-[11px] font-semibold text-primary hover:text-primary/80 transition-colors flex items-center gap-1"
                  >
                    <span>{t("admin_dashboard.models.configure")}</span>
                    <ArrowRight className="h-3 w-3" />
                  </Link>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
