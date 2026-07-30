"use client";

import { Box, Globe, Settings2, Trash2, Users, Wand2 } from "lucide-react";
import type { IntegrationPolicyRow } from "@/lib/mcpIntegrationPolicy";
import { modeLabel, policyBadges } from "@/lib/mcpIntegrationPolicy";
import type { McpIntegrityIssue } from "@/components/McpIntegrityBanner";

type RegistryConfig = {
  description?: string;
  type?: string;
  is_base?: boolean;
  aion_connector_id?: string;
};

type Props = {
  name: string;
  config: RegistryConfig;
  policy?: IntegrationPolicyRow;
  issues?: McpIntegrityIssue[];
  loading?: boolean;
  onEdit: () => void;
  onProbe?: () => void;
  onWizard?: () => void;
  onDelete?: () => void;
};

function typeBadge(type?: string) {
  switch (type) {
    case "sse":
      return { label: "SSE remoto", className: "text-cyan-400 bg-cyan-500/10 border-cyan-500/20" };
    case "remote-bridge":
      return { label: "Remote bridge", className: "text-purple-400 bg-purple-500/10 border-purple-500/20" };
    case "in_process":
      return { label: "In-process", className: "text-amber-400 bg-amber-500/10 border-amber-500/20" };
    default:
      return { label: "Stdio", className: "text-gray-400 bg-white/5 border-white/10" };
  }
}

export function McpInstalledCard({
  name,
  config,
  policy,
  issues = [],
  loading,
  onEdit,
  onProbe,
  onWizard,
  onDelete,
}: Props) {
  const badge = typeBadge(config.type);
  const badges = policyBadges(policy);
  const hasIssues = issues.length > 0;
  const connectorId = policy?.aion_connector_id || config.aion_connector_id;

  return (
    <div
      className={`glass-card flex flex-col rounded-2xl border backdrop-blur-sm transition-all duration-200 shadow-xl ${
        hasIssues
          ? "border-amber-500/30 bg-amber-500/[0.03]"
          : "border-white/5 bg-[#121212]/80 hover:border-white/15"
      }`}
    >
      <div className="p-5 flex-1 space-y-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <h3 className="font-bold text-base text-white truncate font-mono">{name}</h3>
            {policy?.display_name && policy.display_name !== name ? (
              <p className="text-xs text-gray-500 truncate">{policy.display_name}</p>
            ) : null}
          </div>
          <div className="p-2 bg-white/5 border border-white/10 rounded-xl shrink-0">
            {config.type === "sse" || config.type === "remote-bridge" ? (
              <Globe className="w-4 h-4 text-blue-400" />
            ) : (
              <Box className="w-4 h-4 text-gray-300" />
            )}
          </div>
        </div>

        <div className="flex flex-wrap gap-1.5">
          <span className={`text-[9px] font-bold uppercase tracking-wide px-2 py-0.5 rounded-md border ${badge.className}`}>
            {badge.label}
          </span>
          {config.is_base ? (
            <span className="text-[9px] font-bold uppercase tracking-wide text-blue-400 bg-blue-500/10 border border-blue-500/20 px-2 py-0.5 rounded-md">
              Sistema
            </span>
          ) : null}
          {policy?.credential_mode ? (
            <span className="text-[9px] font-bold uppercase tracking-wide text-indigo-300 bg-indigo-500/10 border border-indigo-500/25 px-2 py-0.5 rounded-md">
              {modeLabel(policy.credential_mode)}
            </span>
          ) : null}
          {badges.map((b) => (
            <span
              key={b}
              className="text-[9px] font-bold uppercase tracking-wide text-gray-400 bg-white/5 border border-white/10 px-2 py-0.5 rounded-md"
            >
              {b}
            </span>
          ))}
        </div>

        {connectorId ? (
          <p className="text-[10px] text-gray-500">
            Connettore: <span className="font-mono text-gray-400">{connectorId}</span>
          </p>
        ) : null}

        <p className="text-sm text-gray-400 line-clamp-2 leading-relaxed">
          {config.description || policy?.description || "Nessuna descrizione."}
        </p>

        {hasIssues ? (
          <div className="rounded-lg border border-amber-500/25 bg-amber-500/5 px-3 py-2 text-[11px] text-amber-200/90 space-y-1">
            {issues.slice(0, 2).map((issue, i) => (
              <p key={`${issue.code}-${i}`}>{issue.message}</p>
            ))}
          </div>
        ) : null}
      </div>

      <div className="flex flex-wrap gap-2 border-t border-white/5 p-3 bg-black/20 rounded-b-2xl">
        <button
          type="button"
          onClick={onEdit}
          className="flex-1 min-w-[120px] flex items-center justify-center gap-1.5 py-2 bg-white/10 hover:bg-white/15 border border-white/10 rounded-xl text-[11px] font-bold text-white transition-all"
        >
          <Settings2 className="w-3.5 h-3.5" />
          Configura
        </button>
        {config.type === "remote-bridge" ? (
          <div
            className="px-2.5 py-2 bg-blue-500/10 border border-blue-500/20 rounded-xl text-[10px] font-bold text-blue-300 flex items-center gap-1"
            title="OAuth gestito dagli utenti in chat-ui"
          >
            <Users className="w-3.5 h-3.5" />
            OAuth
          </div>
        ) : null}
        {!config.is_base && onProbe ? (
          <button
            type="button"
            onClick={onProbe}
            disabled={loading}
            className="px-2.5 py-2 bg-emerald-500/10 hover:bg-emerald-500/20 border border-emerald-500/20 rounded-xl text-[10px] font-bold text-emerald-300"
          >
            Probe
          </button>
        ) : null}
        {!config.is_base && onWizard && config.type !== "sse" && config.type !== "remote-bridge" ? (
          <button
            type="button"
            onClick={onWizard}
            className="px-2.5 py-2 bg-indigo-500/10 hover:bg-indigo-500/20 border border-indigo-500/20 rounded-xl text-indigo-300"
            title="Wizard guidato"
          >
            <Wand2 className="w-4 h-4" />
          </button>
        ) : null}
        {!config.is_base && onDelete ? (
          <button
            type="button"
            onClick={onDelete}
            className="px-2.5 py-2 bg-red-500/10 hover:bg-red-500/20 border border-red-500/20 rounded-xl text-red-400"
            title="Disinstalla"
          >
            <Trash2 className="w-4 h-4" />
          </button>
        ) : null}
      </div>
    </div>
  );
}
