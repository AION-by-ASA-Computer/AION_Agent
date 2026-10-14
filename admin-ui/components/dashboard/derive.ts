import {
  Bot,
  Brain,
  Clock,
  Database,
  KeyRound,
  Plug,
  Layers,
  Cpu,
  ScanLine,
  Server,
  Sparkles,
  Terminal,
  Users,
  Zap,
  type LucideIcon,
} from "lucide-react";
import type { DashboardData } from "./useDashboardData";

export type NodeStatus = "ok" | "warn" | "error" | "checking" | "idle";

export type MapNode = {
  id: string;
  icon: LucideIcon;
  label: string;
  value: string | null;
  detail: string;
  status: NodeStatus;
  href: string;
  /** Accessible status text. */
  statusLabel: string;
};

export type MapColumn = { id: string; label: string; nodes: MapNode[] };

export type Attention = {
  id: string;
  severity: "error" | "warn";
  title: string;
  detail?: string;
  href: string;
  action: string;
  /** Map node this problem lives on, highlighted while the row is hovered. */
  node?: string;
};

type T = (key: string, vars?: Record<string, string | number>) => string;

export type MapEdge = {
  from: string;
  to: string;
  /** "uses": the request flows along it. "contains": the profile bundles the target. */
  kind: "uses" | "contains";
  /** Node the edge arcs over instead of crossing it. */
  over?: string;
};

/** The request path: callers pick a profile, the profile is handed to the model, the model works with its capabilities. */
export const MAP_EDGES: MapEdge[] = [
  { from: "users", to: "profiles", kind: "uses" },
  { from: "api_keys", to: "profiles", kind: "uses" },
  { from: "jobs", to: "profiles", kind: "uses" },
  { from: "profiles", to: "models", kind: "uses" },
  { from: "profiles", to: "skills", kind: "contains", over: "models" },
  { from: "profiles", to: "mcp", kind: "contains", over: "models" },
  { from: "models", to: "memory", kind: "uses" },
  { from: "models", to: "skills", kind: "uses" },
  { from: "models", to: "mcp", kind: "uses" },
  { from: "memory", to: "embeddings", kind: "uses" },
  { from: "memory", to: "redis", kind: "uses" },
  { from: "memory", to: "database", kind: "uses" },
  { from: "mcp", to: "ocr", kind: "uses" },
  { from: "mcp", to: "sandbox", kind: "uses" },
  { from: "mcp", to: "mcp_other", kind: "uses" },
];

const DAY = 24 * 60 * 60 * 1000;

function within(iso: string | null | undefined, ms: number): boolean {
  if (!iso) return false;
  const tms = new Date(iso).getTime();
  return Number.isFinite(tms) && Date.now() - tms <= ms;
}

function bytes(n: number | undefined, locale: string): string {
  if (n === undefined || n === null) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let v = n;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${new Intl.NumberFormat(locale, { maximumFractionDigits: v < 10 ? 1 : 0 }).format(v)} ${units[i]}`;
}

function hostOf(url: string | null | undefined): string {
  if (!url) return "";
  try {
    return new URL(url).host;
  } catch {
    return url.replace(/^[a-z]+:\/\//, "").split("/")[0];
  }
}

export function deriveDashboard(d: DashboardData, t: T, locale: string) {
  const num = (v: number | undefined | null) =>
    v === undefined || v === null ? null : new Intl.NumberFormat(locale).format(v);
  const k = "admin_dashboard";
  const statusLabel = (s: NodeStatus) => t(`${k}.status.${s}`);
  const attention: Attention[] = [];

  // ── Models ─────────────────────────────────────────────
  const enabled = d.providers.filter((p) => p.enabled);
  const offline = enabled.filter((p) => d.probes[p.slug]?.status === "offline");
  const checkingModels = enabled.some((p) => !d.probes[p.slug] || d.probes[p.slug].status === "checking");
  const def = enabled.find((p) => p.is_default) ?? enabled[0];
  let modelStatus: NodeStatus = "ok";
  let modelDetail = "";
  if (!d.loading && enabled.length === 0) {
    modelStatus = "error";
    modelDetail = t(`${k}.nodes.models_none`);
    attention.push({
      id: "no-models",
      node: "models",
      severity: "error",
      title: t(`${k}.attention.no_models`),
      detail: t(`${k}.attention.no_models_detail`),
      href: "/settings",
      action: t(`${k}.attention.action_add_model`),
    });
  } else if (offline.length > 0) {
    modelStatus = offline.some((p) => p.is_default) ? "error" : "warn";
    modelDetail = t(`${k}.nodes.models_offline`, { count: offline.length });
    for (const p of offline) {
      attention.push({
        id: `model-${p.slug}`,
        node: "models",
        severity: p.is_default ? "error" : "warn",
        title: t(`${k}.attention.model_offline`, { name: p.display_name || p.slug }),
        detail: [hostOf(p.api_base_url) || p.provider, d.probes[p.slug]?.error].filter(Boolean).join(" · "),
        href: "/settings",
        action: t(`${k}.attention.action_settings`),
      });
    }
  } else if (checkingModels || d.loading) {
    modelStatus = "checking";
    modelDetail = def ? def.display_name || def.model_name : t(`${k}.status.checking`);
  } else if (def) {
    const ms = d.probes[def.slug]?.latency_ms;
    modelDetail = ms ? t(`${k}.nodes.with_latency`, { name: def.display_name || def.model_name, ms }) : def.display_name;
  }

  // ── Probed services ────────────────────────────────────
  const serviceNode = (
    key: "embeddings" | "ocr",
    icon: LucideIcon,
    okDetail: string,
  ): MapNode => {
    const p = d.probes[key];
    let status: NodeStatus = "checking";
    let detail = t(`${k}.status.checking`);
    if (p?.status === "online") {
      status = "ok";
      detail = p.local ? t(`${k}.nodes.ocr_local`) : p.latency_ms ? `${okDetail} · ${p.latency_ms} ms` : okDetail;
    } else if (p?.status === "offline") {
      status = "error";
      detail = t(`${k}.nodes.unreachable`);
      attention.push({
        id: `svc-${key}`,
      node: key,
        severity: "error",
        title: t(`${k}.attention.${key}_offline`),
        detail: [
          hostOf(key === "ocr" ? d.settings.AION_OCR_BASE_URL : d.settings.AION_EMBEDDING_URL),
          p.error,
        ]
          .filter(Boolean)
          .join(" · "),
        href: "/settings",
        action: t(`${k}.attention.action_settings`),
      });
    }
    return {
      id: key,
      icon,
      label: t(`${k}.nodes.${key}`),
      value: null,
      detail,
      status,
      href: "/settings",
      statusLabel: statusLabel(status),
    };
  };

  const embeddings = serviceNode(
    "embeddings",
    Layers,
    d.settings.AION_EMBEDDING_MODEL || t(`${k}.nodes.embeddings_default`),
  );
  const ocr = serviceNode("ocr", ScanLine, d.settings.AION_OCR_MODEL || t(`${k}.nodes.ocr_remote`));

  // ── Redis / DB ───────────────────────────────
  const redis = d.health?.redis;
  let redisStatus: NodeStatus = d.health ? "ok" : d.loading ? "checking" : "idle";
  let redisDetail = d.health ? hostOf(redis?.url) || redis?.type || "" : "—";
  if (d.health && !redis?.url) {
    redisStatus = "idle";
    redisDetail = t(`${k}.nodes.not_configured`);
  } else if (d.health && redis && redis.connected === false) {
    redisStatus = "error";
    redisDetail = t(`${k}.nodes.disconnected`);
    attention.push({
      id: "redis",
      node: "redis",
      severity: "error",
      title: t(`${k}.attention.redis_down`),
      detail: hostOf(redis.url),
      href: "/system",
      action: t(`${k}.attention.action_system`),
    });
  }

  // ── MCP errors ─────────────────────────────────────────
  const mcpErrors = d.metrics?.mcp_call_errors ?? [];
  const mcpErrorCount = mcpErrors.reduce((a, e) => a + (e.error_count || 1), 0);
  if (mcpErrorCount > 0) {
    const servers = Array.from(new Set(mcpErrors.map((e) => e.mcp_server).filter(Boolean)));
    attention.push({
      id: "mcp-errors",
      node: "mcp",
      severity: "warn",
      title: t(`${k}.attention.mcp_errors`, { count: mcpErrorCount }),
      detail: servers.slice(0, 3).join(", ") + (servers.length > 3 ? ` +${servers.length - 3}` : ""),
      href: "/metrics",
      action: t(`${k}.attention.action_metrics`),
    });
  }

  // ── Scheduled jobs ─────────────────────────────────────
  const failedJobs = (d.jobs ?? []).filter((j) => j.enabled && j.last_run?.status === "error");
  if (failedJobs.length > 0) {
    attention.push({
      id: "jobs",
      node: "jobs",
      severity: "warn",
      title: t(`${k}.attention.jobs_failed`, { count: failedJobs.length }),
      detail:
        failedJobs
          .slice(0, 3)
          .map((j) => j.name)
          .join(", ") + (failedJobs.length > 3 ? ` +${failedJobs.length - 3}` : ""),
      href: "/schedules",
      action: t(`${k}.attention.action_jobs`),
    });
  }

  // ── Feedback ───────────────────────────────────────────
  const week = 7 * DAY;
  const recentFeedback = (d.feedback ?? []).filter((f) => within(f.created_at, week));
  const negatives = recentFeedback.filter((f) => f.rating === -1);
  const positives = recentFeedback.filter((f) => f.rating === 1);
  if (negatives.length > 0) {
    const latest = negatives.find((f) => f.feedback_comment?.trim());
    attention.push({
      id: "feedback",
      severity: "warn",
      title: t(`${k}.attention.feedback_negative`, { count: negatives.length }),
      detail: latest ? `“${latest.feedback_comment!.trim().slice(0, 90)}”` : undefined,
      href: "/conversations?feedback=disliked",
      action: t(`${k}.attention.action_feedback`),
    });
  }

  if (d.failed) {
    attention.unshift({
      id: "load-failed",
      severity: "error",
      title: t(`${k}.attention.load_failed`),
      detail: t(`${k}.attention.load_failed_detail`),
      href: "/system",
      action: t(`${k}.attention.action_system`),
    });
  }

  attention.sort((a, b) => (a.severity === b.severity ? 0 : a.severity === "error" ? -1 : 1));

  // ── Map ────────────────────────────────────────────────
  const s = d.stats;
  const pending = d.loading ? "checking" : "idle";

  // ── Other MCP servers: everything in the registry besides the two drawn on their own ──
  const OWN_NODES = new Set(["ocr", "session_sandbox"]);
  const otherMcp = Object.entries(d.registry ?? {})
    .filter(([name, cfg]) => !OWN_NODES.has(name) && cfg?.disabled !== true && cfg?.enabled !== false)
    // Servers added for this install come first: they are the ones an admin recognises.
    .sort(([a, x], [b, y]) => Number(!!x?.is_base) - Number(!!y?.is_base) || a.localeCompare(b))
    .map(([name]) => name);
  const otherMcpErrors = (d.metrics?.mcp_call_errors ?? [])
    .filter((e) => otherMcp.includes(e.mcp_server))
    .reduce((n, e) => n + e.error_count, 0);
  const otherMcpStatus: NodeStatus = otherMcpErrors > 0 ? "warn" : "ok";
  const shown = otherMcp.slice(0, 3).join(", ");
  const otherMcpNode: MapNode | null = otherMcp.length
    ? {
        id: "mcp_other",
        icon: Plug,
        label: t(`${k}.nodes.mcp_other`),
        value: new Intl.NumberFormat(locale).format(otherMcp.length),
        detail:
          otherMcpErrors > 0
            ? t(`${k}.nodes.errors_24h`, { count: otherMcpErrors })
            : otherMcp.length > 3
              ? t(`${k}.nodes.mcp_other_more`, { names: shown, count: otherMcp.length - 3 })
              : shown,
        status: otherMcpStatus,
        href: "/hub",
        statusLabel: statusLabel(otherMcpStatus),
      }
    : null;

  // ── Session sandbox: the MCP server that runs the agent's code ──
  const sandboxErrors = (d.metrics?.mcp_call_errors ?? [])
    .filter((e) => e.mcp_server === "session_sandbox")
    .reduce((n, e) => n + e.error_count, 0);
  const sandboxBackend = (d.settings.AION_SANDBOX_BACKEND || "").trim();
  const sandboxStatus: NodeStatus = sandboxErrors > 0 ? "warn" : d.stats ? "ok" : pending;
  const sandboxDetail =
    sandboxErrors > 0
      ? t(`${k}.nodes.errors_24h`, { count: sandboxErrors })
      : sandboxBackend === "container"
        ? t(`${k}.nodes.sandbox_container`)
        : sandboxBackend === "subprocess"
          ? t(`${k}.nodes.sandbox_subprocess`)
          : d.stats
            ? sandboxBackend || t(`${k}.nodes.sandbox_subprocess`)
            : "—";
  const users = d.users;
  const activeUsers = users?.filter((u) => within(u.last_active_at, DAY)).length;
  const usedProfiles = d.metrics?.profile_metrics?.filter((p) => p.total_turns > 0).length;
  const jobsTotal = s?.cron_jobs?.total;

  const node = (
    id: string,
    icon: LucideIcon,
    href: string,
    value: number | undefined | null,
    detail: string,
    status?: NodeStatus,
  ): MapNode => {
    const st: NodeStatus = status ?? (value === undefined || value === null ? pending : "ok");
    return {
      id,
      icon,
      label: t(`${k}.nodes.${id}`),
      value: num(value),
      detail,
      status: st,
      href,
      statusLabel: statusLabel(st),
    };
  };

  const columns: MapColumn[] = [
    {
      id: "callers",
      label: t(`${k}.map.col_callers`),
      nodes: [
        node(
          "users",
          Users,
          "/users",
          users?.length,
          activeUsers !== undefined ? t(`${k}.nodes.users_active`, { count: activeUsers }) : "—",
        ),
        node("api_keys", KeyRound, "/api-keys", s?.api_keys?.total, t(`${k}.nodes.api_keys_detail`)),
        node(
          "jobs",
          Clock,
          "/schedules",
          jobsTotal,
          failedJobs.length > 0
            ? t(`${k}.nodes.jobs_failed`, { count: failedJobs.length })
            : t(`${k}.nodes.jobs_enabled`, { count: s?.cron_jobs?.enabled ?? 0 }),
          jobsTotal === undefined ? undefined : failedJobs.length > 0 ? "warn" : "ok",
        ),
      ],
    },
    {
      id: "agent",
      label: t(`${k}.map.col_agent`),
      nodes: [
        node(
          "profiles",
          Bot,
          "/profiles",
          s?.active_profiles,
          usedProfiles !== undefined ? t(`${k}.nodes.profiles_used`, { count: usedProfiles }) : "—",
        ),
      ],
    },
    {
      id: "model",
      label: t(`${k}.map.col_model`),
      nodes: [
        node("models", Cpu, "/settings", d.loading ? undefined : enabled.length, modelDetail, d.loading ? "checking" : modelStatus),
      ],
    },
    {
      id: "tools",
      label: t(`${k}.map.col_tools`),
      nodes: [
        node("memory", Brain, "/memory", s?.total_projects, t(`${k}.nodes.memory_detail`)),
        node("skills", Sparkles, "/skills", s?.total_skills, t(`${k}.nodes.skills_detail`)),
        node(
          "mcp",
          Server,
          "/hub",
          s?.installed_mcp,
          d.metrics
            ? mcpErrorCount > 0
              ? t(`${k}.nodes.mcp_errors`, { count: mcpErrorCount })
              : t(`${k}.nodes.mcp_ok`)
            : t(`${k}.nodes.mcp_detail`),
          s?.installed_mcp === undefined ? undefined : mcpErrorCount > 0 ? "warn" : "ok",
        ),
      ],
    },
    {
      id: "services",
      label: t(`${k}.map.col_services`),
      nodes: [
        embeddings,
        {
          id: "redis",
          icon: Zap,
          label: t(`${k}.nodes.redis`),
          value: null,
          detail: redisDetail,
          status: redisStatus,
          href: "/system",
          statusLabel: statusLabel(redisStatus),
        },
        {
          id: "database",
          icon: Database,
          label: t(`${k}.nodes.database`),
          value: null,
          detail: d.health?.database ? bytes(d.health.database.size_bytes, locale) : "—",
          status: d.health?.database ? "ok" : pending,
          href: "/system",
          statusLabel: statusLabel(d.health?.database ? "ok" : pending),
        },
        ocr,
        {
          id: "sandbox",
          icon: Terminal,
          label: t(`${k}.nodes.sandbox`),
          value: null,
          detail: sandboxDetail,
          status: sandboxStatus,
          href: "/hub",
          statusLabel: statusLabel(sandboxStatus),
        },
        ...(otherMcpNode ? [otherMcpNode] : []),
      ],
    },
  ];

  const checking =
    d.loading || Object.values(d.probes).some((p) => p.status === "checking");

  return {
    attention,
    columns,
    checking,
    feedback: { positives: positives.length, negatives: negatives.length },
    summary: {
      profiles: s?.active_profiles,
      mcp: s?.installed_mcp,
      users: users?.length,
    },
  };
}
