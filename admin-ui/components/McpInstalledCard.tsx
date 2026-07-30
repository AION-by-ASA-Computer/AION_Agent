"use client";

import { Box, Globe, Settings2, Terminal, Trash2, Users, Wand2 } from "lucide-react";
import type { IntegrationPolicyRow } from "@/lib/mcpIntegrationPolicy";
import { modeLabel, policyBadges } from "@/lib/mcpIntegrationPolicy";
import type { McpIntegrityIssue } from "@/components/McpIntegrityBanner";
import { cn } from "@/lib/cn";

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

function installTypeMeta(type?: string) {
  switch (type) {
    case "sse":
      return { label: "Remote", icon: Globe, iconClass: "text-blue-400" };
    case "remote-bridge":
      return { label: "Remote bridge", icon: Globe, iconClass: "text-blue-400" };
    case "in_process":
      return { label: "In-process", icon: Box, iconClass: "text-amber-400" };
    default:
      return { label: "Stdio", icon: Terminal, iconClass: "text-gray-400" };
  }
}

function headerIcon(type?: string) {
  if (type === "sse" || type === "remote-bridge") {
    return { Icon: Globe, className: "text-blue-400" };
  }
  if (type === "in_process") {
    return { Icon: Box, className: "text-amber-400" };
  }
  return { Icon: Terminal, className: "text-gray-300" };
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
  const badges = policyBadges(policy);
  const hasIssues = issues.length > 0;
  const connectorId = policy?.aion_connector_id || config.aion_connector_id;
  const displayName = policy?.display_name && policy.display_name !== name ? policy.display_name : null;
  const typeMeta = installTypeMeta(config.type);
  const TypeIcon = typeMeta.icon;
  const header = headerIcon(config.type);
  const HeaderIcon = header.Icon;

  return (
    <div
      className={cn(
        "glass-card group flex flex-col rounded-2xl border bg-[#121212]/80 shadow-xl backdrop-blur-sm transition-all duration-200",
        hasIssues
          ? "border-amber-500/30 hover:border-amber-500/50"
          : "border-white/5 hover:border-blue-500/50",
      )}
    >
      <div className="flex-1 space-y-4 p-6">
        <div className="flex items-start justify-between gap-3">
          <div
            className={cn(
              "rounded-xl border p-3 transition-colors",
              hasIssues
                ? "border-amber-500/20 bg-amber-500/10 group-hover:bg-amber-500/15"
                : "border-blue-500/20 bg-blue-500/10 group-hover:bg-blue-500/20",
            )}
          >
            <HeaderIcon className={cn("h-6 w-6", hasIssues ? "text-amber-400" : header.className)} aria-hidden />
          </div>
          <div className="flex max-w-[55%] flex-col items-end gap-1.5">
            {config.is_base ? (
              <span className="rounded-lg border border-blue-500/20 bg-blue-500/10 px-2.5 py-1 text-[10px] font-bold uppercase tracking-widest text-blue-300">
                Sistema
              </span>
            ) : hasIssues ? (
              <span className="rounded-lg border border-amber-500/20 bg-amber-500/10 px-2.5 py-1 text-[10px] font-bold uppercase tracking-widest text-amber-300">
                Attenzione
              </span>
            ) : (
              <span className="rounded-lg border border-emerald-500/20 bg-emerald-500/10 px-2.5 py-1 text-[10px] font-bold uppercase tracking-widest text-emerald-300">
                Attivo
              </span>
            )}
            {policy?.credential_mode ? (
              <span className="rounded-lg border border-white/10 bg-white/5 px-2.5 py-1 font-mono text-[10px] font-bold uppercase tracking-widest text-gray-400">
                {modeLabel(policy.credential_mode)}
              </span>
            ) : null}
          </div>
        </div>

        <div>
          <h3 className="truncate text-xl font-bold text-white">{name}</h3>
          {displayName ? <p className="mt-0.5 truncate text-xs text-gray-500">{displayName}</p> : null}
          <p className="mt-1 line-clamp-2 text-sm text-gray-400">
            {config.description || "Nessuna descrizione."}
          </p>
        </div>

        {(badges.length > 0 || connectorId) && (
          <div className="flex flex-wrap gap-1.5">
            {badges.map((b) => (
              <span
                key={b}
                className="rounded-md border border-white/10 bg-white/5 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-gray-400"
              >
                {b}
              </span>
            ))}
            {connectorId ? (
              <span className="rounded-md border border-white/10 bg-white/5 px-2 py-0.5 font-mono text-[10px] text-gray-500">
                {connectorId}
              </span>
            ) : null}
          </div>
        )}

        {hasIssues ? (
          <div className="space-y-1 rounded-xl border border-amber-500/20 bg-amber-500/5 px-3 py-2 text-[11px] text-amber-200/90">
            {issues.slice(0, 2).map((issue, i) => (
              <p key={`${issue.code}-${i}`}>{issue.message}</p>
            ))}
          </div>
        ) : null}
      </div>

      <div className="flex items-center justify-between rounded-b-2xl border-t border-white/5 bg-black/20 p-4">
        <div className="flex items-center gap-2 font-mono text-[10px] font-bold uppercase text-gray-500">
          <TypeIcon className={cn("h-3 w-3", typeMeta.iconClass)} aria-hidden />
          {typeMeta.label}
          {config.type === "remote-bridge" ? (
            <span className="ml-1 inline-flex items-center gap-1 normal-case text-indigo-300/90">
              <Users className="h-3 w-3" aria-hidden />
              OAuth
            </span>
          ) : null}
        </div>

        <div className="flex items-center gap-2">
          {!config.is_base && onWizard && config.type !== "sse" && config.type !== "remote-bridge" ? (
            <button
              type="button"
              onClick={onWizard}
              disabled={loading}
              className="flex cursor-pointer items-center gap-1.5 rounded-xl border border-indigo-500/20 bg-indigo-500/10 px-3 py-2 text-xs font-bold text-indigo-300 hover:bg-indigo-500/20 disabled:opacity-50"
              title="Wizard guidato"
            >
              <Wand2 className="h-3.5 w-3.5" aria-hidden />
              WIZARD
            </button>
          ) : null}
          {!config.is_base && onProbe ? (
            <button
              type="button"
              onClick={onProbe}
              disabled={loading}
              className="cursor-pointer rounded-xl border border-emerald-500/20 bg-emerald-500/10 px-3 py-2 text-xs font-bold text-emerald-300 hover:bg-emerald-500/20 disabled:opacity-50"
            >
              PROBE
            </button>
          ) : null}
          <button
            type="button"
            onClick={onEdit}
            className="flex cursor-pointer items-center gap-2 rounded-xl border border-blue-500/20 bg-blue-500/10 px-4 py-2 text-xs font-bold text-blue-400 shadow-lg shadow-blue-500/5 transition-all hover:border-blue-500/40 hover:bg-blue-500/20"
          >
            <Settings2 className="h-3.5 w-3.5" aria-hidden />
            CONFIGURA
          </button>
          {!config.is_base && onDelete ? (
            <button
              type="button"
              onClick={onDelete}
              className="cursor-pointer rounded-xl border border-red-500/20 bg-red-500/10 p-2 text-red-400 hover:bg-red-500/20"
              title="Disinstalla"
            >
              <Trash2 className="h-4 w-4" aria-hidden />
            </button>
          ) : null}
        </div>
      </div>
    </div>
  );
}
