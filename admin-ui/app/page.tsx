"use client";

import { useEffect, useState } from "react";
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
  FileText,
  Settings,
  Plus,
  Clock,
  Key,
  FolderOpen
} from "lucide-react";
import { apiFetch } from "@/lib/api/headers";
import { apiBase } from "@/lib/api";

export default function Home() {
  const [stats, setStats] = useState<any>(null);
  const [health, setHealth] = useState<any>(null);
  const [conversations, setConversations] = useState<any[]>([]);
  const [recoveryStats, setRecoveryStats] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const fetchData = async () => {
    setRefreshing(true);
    try {
      const [statsRes, healthRes, convsRes, recoveryRes] = await Promise.all([
        apiFetch(`${apiBase()}/admin/stats`),
        apiFetch(`${apiBase()}/admin/system/health`),
        apiFetch(`${apiBase()}/admin/conversations/global?limit=10`),
        apiFetch(`${apiBase()}/admin/diagnostics/json-recovery`)
      ]);

      const [statsData, healthData, convsData, recoveryData] = await Promise.all([
        statsRes.ok ? statsRes.json() : null,
        healthRes.ok ? healthRes.json() : null,
        convsRes.ok ? convsRes.json() : null,
        recoveryRes.ok ? recoveryRes.json() : null
      ]);

      if (statsData) setStats(statsData);
      if (healthData) setHealth(healthData);
      if (convsData) setConversations(convsData.conversations || []);
      if (recoveryData) setRecoveryStats(recoveryData);
    } catch (err) {
      console.error("Dashboard data fetch failed", err);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 30000);
    return () => clearInterval(interval);
  }, []);

  const cronTotal = stats?.cron_jobs?.total !== undefined ? stats.cron_jobs.total : "...";
  const cronEnabled = stats?.cron_jobs?.enabled !== undefined ? stats.cron_jobs.enabled : "...";
  const apiKeysTotal = stats?.api_keys?.total !== undefined ? stats.api_keys.total : "...";
  const projectsTotal = stats?.total_projects !== undefined ? stats.total_projects : "...";

  const statItems = [
    {
      name: "Active Profiles",
      value: stats?.active_profiles !== undefined ? stats.active_profiles : "...",
      icon: Users,
      color: "text-blue-400 bg-blue-500/10 border-blue-500/20",
      hoverColor: "hover:border-blue-500/40 hover:shadow-blue-500/5",
      href: "/profiles",
      description: "Configured personas"
    },
    {
      name: "Total Skills",
      value: stats?.total_skills !== undefined ? stats.total_skills : "...",
      icon: Zap,
      color: "text-purple-400 bg-purple-500/10 border-purple-500/20",
      hoverColor: "hover:border-purple-500/40 hover:shadow-purple-500/5",
      href: "/skills",
      description: "Custom capabilities"
    },
    {
      name: "Installed MCPs",
      value: stats?.installed_mcp !== undefined ? stats.installed_mcp : "...",
      icon: Globe,
      color: "text-green-400 bg-green-500/10 border-green-500/20",
      hoverColor: "hover:border-green-500/40 hover:shadow-green-500/5",
      href: "/hub",
      description: "MCP tool servers"
    },
    {
      name: "SQL Projects",
      value: projectsTotal,
      icon: FolderOpen,
      color: "text-indigo-400 bg-indigo-500/10 border-indigo-500/20",
      hoverColor: "hover:border-indigo-500/40 hover:shadow-indigo-500/5",
      href: "/memory",
      description: "Isolated database projects"
    },
    {
      name: "Cron Jobs",
      value: cronTotal !== "..." ? `${cronEnabled}/${cronTotal}` : "...",
      icon: Clock,
      color: "text-amber-400 bg-amber-500/10 border-amber-500/20",
      hoverColor: "hover:border-amber-500/40 hover:shadow-amber-500/5",
      href: "/schedules",
      description: "Active background cron tasks"
    },
    {
      name: "API Keys",
      value: apiKeysTotal,
      icon: Key,
      color: "text-cyan-400 bg-cyan-500/10 border-cyan-500/20",
      hoverColor: "hover:border-cyan-500/40 hover:shadow-cyan-500/5",
      href: "/api-keys",
      description: "Authorized access credentials"
    }
  ];

  // Helper formatting for memory size
  const formatBytes = (bytes: number) => {
    if (bytes === undefined || bytes === null || bytes <= 0) return "N/A";
    const mb = bytes / (1024 * 1024);
    return `${mb.toFixed(2)} MB`;
  };

  // Helper for conversation time formatting
  const formatTime = (dateStr: string) => {
    try {
      const date = new Date(dateStr);
      return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) + ' ' + date.toLocaleDateString([], { month: 'short', day: 'numeric' });
    } catch {
      return dateStr;
    }
  };

  // Calculate JSON repair rate
  const repairAttempts = recoveryStats?.attempts || 0;
  const repairRecovered = recoveryStats?.recovered || 0;
  const repairRate = repairAttempts > 0 ? ((repairRecovered / repairAttempts) * 100).toFixed(1) : "100.0";

  return (
    <div className="space-y-8 animate-in fade-in duration-500">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-[10px] font-bold uppercase tracking-[0.2em] text-gray-500">Overview</h2>
          <h1 className="text-3xl font-black text-white mt-1">Control Center</h1>
          <p className="text-gray-400 text-sm mt-1">Real-time monitoring and configurations overview for AION Agent.</p>
        </div>
      </div>

      {/* KPI Cards Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-6 gap-6">
        {statItems.map((stat) => (
          <Link
            key={stat.name}
            href={stat.href}
            className={`glass-card p-6 border border-white/10 bg-[#141414]/40 transition-all group flex flex-col justify-between hover:shadow-lg ${stat.hoverColor}`}
          >
            <div>
              <div className="flex items-center justify-between mb-4">
                <div className={`p-3 rounded-xl border ${stat.color} group-hover:scale-110 transition-transform`}>
                  <stat.icon className="w-5 h-5" />
                </div>
                <span className="text-[9px] text-green-500 font-bold bg-green-500/10 border border-green-500/20 px-2.5 py-0.5 rounded-full uppercase tracking-wider">
                  Active
                </span>
              </div>
              <div className="text-3xl font-black tracking-tight text-white">{stat.value}</div>
              <div className="text-xs font-bold uppercase text-gray-200 mt-2 tracking-wider">{stat.name}</div>
            </div>
            <div className="text-[10px] text-gray-500 mt-2 font-medium">{stat.description}</div>
          </Link>
        ))}
      </div>

      {/* System Health Quick Status Strip */}
      <div className="glass-card p-4 border border-white/10 bg-[#141414]/40 flex flex-wrap items-center justify-between gap-6">
        <div className="flex items-center gap-2">
          <Activity className="w-4 h-4 text-gray-400" />
          <span className="text-xs font-bold uppercase tracking-wider text-gray-400">System Integrity:</span>
        </div>

        <div className="flex flex-wrap items-center gap-6 flex-1 justify-start md:justify-around">
          {/* Redis Health */}
          <div className="flex items-center gap-3">
            <Server className="w-4 h-4 text-gray-500" />
            <div className="text-xs">
              <span className="text-gray-500 font-semibold mr-1.5">Redis:</span>
              {loading ? (
                <span className="text-gray-600 font-mono">Checking...</span>
              ) : health?.redis?.connected ? (
                <span className="inline-flex items-center gap-1 text-green-400 font-bold">
                  <span className="w-1.5 h-1.5 bg-green-400 rounded-full animate-pulse"></span>
                  OPERATIONAL
                </span>
              ) : (
                <span className="inline-flex items-center gap-1 text-red-400 font-bold">
                  <span className="w-1.5 h-1.5 bg-red-400 rounded-full"></span>
                  OFFLINE
                </span>
              )}
            </div>
          </div>

          {/* DB Health */}
          <div className="flex items-center gap-3">
            <Database className="w-4 h-4 text-gray-500" />
            <div className="text-xs">
              <span className="text-gray-500 font-semibold mr-1.5">Database:</span>
              {loading ? (
                <span className="text-gray-600 font-mono">Checking...</span>
              ) : (
                <span className="text-gray-200 font-mono font-bold">
                  SQLite ({formatBytes(health?.database?.size_bytes)})
                </span>
              )}
            </div>
          </div>

          {/* Storage Health */}
          <div className="flex items-center gap-3">
            <HardDrive className="w-4 h-4 text-gray-500" />
            <div className="text-xs">
              <span className="text-gray-500 font-semibold mr-1.5">Storage Backend:</span>
              {loading ? (
                <span className="text-gray-600 font-mono">Checking...</span>
              ) : (
                <span className="text-purple-400 font-bold uppercase font-mono">
                  {health?.storage?.backend || "LOCAL"}
                </span>
              )}
            </div>
          </div>
        </div>

        <Link
          href="/system"
          className="text-xs font-bold text-blue-400 hover:text-blue-300 transition-colors flex items-center gap-1"
        >
          View Health Details <ArrowRight className="w-3 h-3" />
        </Link>
      </div>

      {/* Main Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* Left Section: Recent Conversations & Secondary Diagnostics */}
        <div className="lg:col-span-2 space-y-8">
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <FileText className="w-4 h-4 text-blue-400" />
                <h2 className="text-xs font-bold uppercase text-gray-400 tracking-wider">Recent Activity Sessions</h2>
              </div>
              <Link
                href="/conversations"
                className="text-xs font-bold text-gray-500 hover:text-white transition-colors"
              >
                View All
              </Link>
            </div>

            <div className="glass-card overflow-hidden border border-white/10 rounded-2xl bg-gradient-to-b from-[#181818]/90 to-[#121212]/90 shadow-xl">
              <div className="overflow-x-auto">
                <table className="w-full text-left">
                  <thead>
                    <tr className="bg-black/30 border-b border-white/10 text-xs font-bold text-gray-400 uppercase tracking-wider">
                      <th className="px-6 py-4">Session Info</th>
                      <th className="px-6 py-4">Profile</th>
                      <th className="px-6 py-4">Msgs</th>
                      <th className="px-6 py-4 text-right">Inspect</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/5">
                    {conversations.slice(0, 6).map((conv) => (
                      <tr key={conv.id} className="hover:bg-white/[0.02] transition-colors group">
                        <td className="px-6 py-4">
                          <div>
                            <div className="text-sm font-bold text-white max-w-[280px] truncate">
                              {conv.title || "Untitled Conversation"}
                            </div>
                            <div className="text-[10px] text-gray-500 font-mono mt-0.5 flex items-center gap-1.5">
                              <span>ID: {conv.id.substring(0, 8)}...</span>
                              <span>•</span>
                              <span>{formatTime(conv.updated_at)}</span>
                            </div>
                          </div>
                        </td>
                        <td className="px-6 py-4">
                          <span className="text-xs font-mono font-bold px-2 py-0.5 rounded bg-blue-500/10 text-blue-400 border border-blue-500/20 uppercase tracking-wide">
                            {conv.profile_slug || "default"}
                          </span>
                        </td>
                        <td className="px-6 py-4 text-xs font-mono font-bold text-gray-300">
                          {conv.message_count || 0}
                        </td>
                        <td className="px-6 py-4 text-right">
                          <Link
                            href={`/conversations/${conv.id}`}
                            className="p-2 bg-white/5 hover:bg-blue-500/20 text-gray-400 hover:text-blue-400 border border-white/10 rounded-xl transition-all hover:border-blue-500/40 inline-flex items-center justify-center cursor-pointer"
                          >
                            <ArrowRight className="w-4 h-4" />
                          </Link>
                        </td>
                      </tr>
                    ))}
                    {conversations.length === 0 && !loading && (
                      <tr>
                        <td colSpan={4} className="p-12 text-center text-gray-500 text-sm font-semibold">
                          No active conversation sessions found.
                        </td>
                      </tr>
                    )}
                    {loading && (
                      <tr>
                        <td colSpan={4} className="p-12 text-center text-gray-500 text-sm font-bold uppercase tracking-wider animate-pulse">
                          Fetching active sessions...
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </div>

          {/* Diagnostics and Key Scope Audit Sub-grid */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">


            {/* API Key Scopes Audit */}
            <div className="space-y-4">
              <div className="flex items-center gap-2">
                <Key className="w-4 h-4 text-cyan-400" />
                <h2 className="text-xs font-bold uppercase text-gray-400 tracking-wider">API Key Scope Audit</h2>
              </div>

              <div className="glass-card p-6 border border-white/10 bg-[#141414]/40 space-y-4 flex flex-col justify-between h-[230px]">
                <div>
                  <h3 className="font-bold text-white text-sm">Key Permissions Distribution</h3>
                  <div className="space-y-2 pt-2 overflow-y-auto max-h-[120px] custom-scrollbar">
                    {stats?.api_keys?.by_scope && Object.keys(stats.api_keys.by_scope).length > 0 ? (
                      Object.keys(stats.api_keys.by_scope)
                        .sort((a, b) => (stats.api_keys.by_scope[b] || 0) - (stats.api_keys.by_scope[a] || 0))
                        .map((scopeName) => {
                          const count = stats.api_keys.by_scope[scopeName] || 0;
                          return (
                            <div key={scopeName} className="flex justify-between items-center text-xs py-0.5">
                              <span className="font-mono text-[9px] px-2 py-0.5 rounded bg-cyan-500/10 text-cyan-400 border border-cyan-500/20 uppercase tracking-wide truncate max-w-[130px]" title={scopeName}>
                                {scopeName}
                              </span>
                              <span className="text-gray-400 font-semibold font-mono text-[10px]">
                                {count} key{count !== 1 ? "s" : ""}
                              </span>
                            </div>
                          );
                        })
                    ) : (
                      <div className="text-[10px] text-gray-500 font-bold uppercase tracking-wider py-4 text-center">
                        No active API keys found.
                      </div>
                    )}
                  </div>
                </div>

                <div className="pt-3 border-t border-[#262626] text-[10px] text-gray-500 leading-tight">
                  Distribution of authorized access credentials.
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Right Section: Model Usage & Directives */}
        <div className="space-y-8">
          {/* Model Usage Distribution Card */}
          <div className="space-y-4">
            <div className="flex items-center gap-2">
              <Server className="w-4 h-4 text-cyan-400" />
              <h2 className="text-xs font-bold uppercase text-gray-400 tracking-wider">Model Usage</h2>
            </div>

            <div className="glass-card p-6 border border-white/10 bg-[#141414]/40 space-y-4">
              <h3 className="font-bold text-white text-sm">Top Active LLM Models</h3>
              <div className="space-y-4">
                {stats?.model_usage && Object.keys(stats.model_usage).length > 0 ? (
                  (() => {
                    const modelUsage = stats.model_usage;
                    const totalUsage = Object.values(modelUsage).reduce((acc: number, val: any) => acc + (val || 0), 0) as number;
                    const modelKeys = Object.keys(modelUsage).sort((a, b) => (modelUsage[b] || 0) - (modelUsage[a] || 0));

                    return modelKeys.map((modelName, index) => {
                      const count = modelUsage[modelName] || 0;
                      const percentage = totalUsage > 0 ? ((count / totalUsage) * 100) : 0;
                      const colors = [
                        "bg-gradient-to-r from-blue-500 to-indigo-500",
                        "bg-gradient-to-r from-purple-500 to-pink-500",
                        "bg-gradient-to-r from-cyan-500 to-emerald-500",
                      ];
                      const progressColor = colors[index % colors.length];

                      return (
                        <div key={modelName} className="space-y-1.5">
                          <div className="flex justify-between items-center text-xs">
                            <span className="text-gray-300 font-semibold truncate max-w-[170px]" title={modelName}>
                              {modelName}
                            </span>
                            <span className="text-gray-500 font-mono text-[10px]">
                              {count} chat{count !== 1 ? "s" : ""} ({percentage.toFixed(0)}%)
                            </span>
                          </div>
                          <div className="w-full bg-[#1b1b1b] rounded-full h-1.5 overflow-hidden">
                            <div
                              className={`h-1.5 rounded-full ${progressColor}`}
                              style={{ width: `${percentage}%` }}
                            />
                          </div>
                        </div>
                      );
                    });
                  })()
                ) : (
                  <div className="text-[10px] text-gray-500 font-bold uppercase tracking-wider py-4 text-center">
                    No LLM usage records detected.
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Operational Directives */}
          <div className="space-y-4">
            <h2 className="text-xs font-bold uppercase text-gray-400 tracking-wider">Operational Directives</h2>
            <div className="space-y-3">
              <Link
                href="/profiles"
                className="w-full flex items-center justify-between px-5 py-4 bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white rounded-xl font-bold transition-all shadow-lg shadow-blue-500/20 text-xs uppercase tracking-wider cursor-pointer"
              >
                Create New Profile <Plus className="w-4 h-4" />
              </Link>
              <Link
                href="/hub"
                className="w-full flex items-center justify-between px-5 py-4 bg-[#0d0d0d] hover:bg-[#141414] border border-[#262626] text-gray-300 rounded-xl font-bold transition-all text-xs uppercase tracking-wider hover:border-gray-500/40 cursor-pointer"
              >
                Provision MCP Server <Globe className="w-4 h-4" />
              </Link>
              <Link
                href="/settings"
                className="w-full flex items-center justify-between px-5 py-4 bg-[#0d0d0d] hover:bg-[#141414] border border-[#262626] text-gray-300 rounded-xl font-bold transition-all text-xs uppercase tracking-wider hover:border-gray-500/40 cursor-pointer"
              >
                Governance / Settings <Settings className="w-4 h-4" />
              </Link>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
