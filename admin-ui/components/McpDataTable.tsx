"use client";

import React, { useState, useRef, useEffect } from "react";
import { createPortal } from "react-dom";
import {
  Box,
  Globe,
  Settings2,
  Terminal,
  Trash2,
  Users,
  Wand2,
  Wrench,
  MoreVertical,
  Activity,
  AlertTriangle,
  ExternalLink,
  MessageSquare,
  ShieldCheck,
  CheckCircle2,
  Key,
  Layers,
  Loader2,
} from "lucide-react";
import type { IntegrationPolicyRow } from "@/lib/mcpIntegrationPolicy";
import { modeLabel, policyBadges } from "@/lib/mcpIntegrationPolicy";
import type { McpIntegrityIssue } from "@/components/McpIntegrityBanner";
import { oauthAdminSetupPending } from "@/lib/mcpOAuthSetup";

export interface McpItemRow {
  name: string;
  config: {
    description?: string;
    type?: string;
    is_base?: boolean;
    aion_connector_id?: string;
    command?: string;
    args?: string[];
    url?: string;
    env?: Record<string, string>;
  };
  policy?: IntegrationPolicyRow;
  connector?: Record<string, unknown> | null;
  issues?: McpIntegrityIssue[];
}

export interface McpDataTableProps {
  items: McpItemRow[];
  loading?: boolean;
  probingSlug?: string | null;
  onEdit: (name: string, config: any) => void;
  onProbe?: (name: string) => void;
  onWizard?: (name: string) => void;
  onManageTools?: (name: string) => void;
  onDelete?: (name: string) => void;
  onAdvisor?: (name: string) => void;
  advisorUrl?: (name: string) => string;
}

function installTypeMeta(type?: string) {
  switch (type) {
    case "sse":
      return { label: "Remote SSE", icon: Globe, colorClass: "text-blue-400 bg-blue-500/10 border-blue-500/20" };
    case "remote-bridge":
      return { label: "Remote Bridge", icon: Globe, colorClass: "text-indigo-400 bg-indigo-500/10 border-indigo-500/20" };
    case "in_process":
      return { label: "In-Process", icon: Box, colorClass: "text-amber-400 bg-amber-500/10 border-amber-500/20" };
    default:
      return { label: "Stdio", icon: Terminal, colorClass: "text-gray-400 bg-white/5 border-white/10" };
  }
}

function ActionDropdown({
  item,
  loading,
  isProbing,
  onEdit,
  onProbe,
  onWizard,
  onManageTools,
  onDelete,
  onAdvisor,
  advisorUrl,
}: {
  item: McpItemRow;
  loading?: boolean;
  isProbing?: boolean;
  onEdit: () => void;
  onProbe?: () => void;
  onWizard?: () => void;
  onManageTools?: () => void;
  onDelete?: () => void;
  onAdvisor?: () => void;
  advisorUrl?: string;
}) {
  const [open, setOpen] = useState(false);
  const [menuPosition, setMenuPosition] = useState<{ top: number; left: number } | null>(null);
  const [mounted, setMounted] = useState(false);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setMounted(true);
  }, []);

  const updatePosition = () => {
    if (!buttonRef.current) return;
    const rect = buttonRef.current.getBoundingClientRect();
    const menuWidth = 224; // w-56
    const estimatedHeight = 240;
    const spaceBelow = window.innerHeight - rect.bottom;
    const openUp = spaceBelow < estimatedHeight && rect.top > spaceBelow;

    const top = openUp ? Math.max(8, rect.top - estimatedHeight - 4) : rect.bottom + 6;
    const left = Math.max(8, Math.min(window.innerWidth - menuWidth - 8, rect.right - menuWidth));

    setMenuPosition({ top, left });
  };

  const handleToggle = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!open) {
      updatePosition();
    }
    setOpen((prev) => !prev);
  };

  useEffect(() => {
    if (!open) return;

    const handleClickOutside = (e: MouseEvent) => {
      if (
        menuRef.current &&
        !menuRef.current.contains(e.target as Node) &&
        buttonRef.current &&
        !buttonRef.current.contains(e.target as Node)
      ) {
        setOpen(false);
      }
    };

    const handleScrollOrResize = () => {
      setOpen(false);
    };

    document.addEventListener("mousedown", handleClickOutside);
    window.addEventListener("scroll", handleScrollOrResize, true);
    window.addEventListener("resize", handleScrollOrResize);

    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      window.removeEventListener("scroll", handleScrollOrResize, true);
      window.removeEventListener("resize", handleScrollOrResize);
    };
  }, [open]);

  const { name, config } = item;
  const isBase = Boolean(config.is_base);

  const menuContent = open && menuPosition && (
    <div
      ref={menuRef}
      style={{
        position: "fixed",
        top: `${menuPosition.top}px`,
        left: `${menuPosition.left}px`,
        zIndex: 99999,
      }}
      className="w-56 rounded-xl border border-white/10 bg-[#181818] shadow-2xl py-1.5 text-xs animate-in fade-in zoom-in-95 duration-150 max-h-[calc(100vh-32px)] overflow-y-auto"
    >
      <button
        type="button"
        onClick={() => {
          setOpen(false);
          onEdit();
        }}
        className="w-full flex items-center gap-2.5 px-3.5 py-2 text-gray-200 hover:bg-blue-600/15 hover:text-blue-300 text-left transition cursor-pointer"
      >
        <Settings2 className="w-3.5 h-3.5 text-blue-400" />
        Configure MCP
      </button>

      {!isBase && onManageTools && (
        <button
          type="button"
          onClick={() => {
            setOpen(false);
            onManageTools();
          }}
          disabled={loading}
          className="w-full flex items-center gap-2.5 px-3.5 py-2 text-gray-200 hover:bg-amber-600/15 hover:text-amber-300 text-left transition cursor-pointer disabled:opacity-50"
        >
          <Wrench className="w-3.5 h-3.5 text-amber-400" />
          Manage Active Tools
        </button>
      )}

      {!isBase && onProbe && (
        <button
          type="button"
          onClick={() => {
            setOpen(false);
            onProbe();
          }}
          disabled={loading || isProbing}
          className="w-full flex items-center gap-2.5 px-3.5 py-2 text-gray-200 hover:bg-emerald-600/15 hover:text-emerald-300 text-left transition cursor-pointer disabled:opacity-50"
        >
          {isProbing ? (
            <Loader2 className="w-3.5 h-3.5 text-emerald-400 animate-spin" />
          ) : (
            <Activity className="w-3.5 h-3.5 text-emerald-400" />
          )}
          {isProbing ? "Probing server..." : "Test Connection (Probe)"}
        </button>
      )}

      {!isBase && onWizard && config.type !== "sse" && config.type !== "remote-bridge" && (
        <button
          type="button"
          onClick={() => {
            setOpen(false);
            onWizard();
          }}
          disabled={loading}
          className="w-full flex items-center gap-2.5 px-3.5 py-2 text-gray-200 hover:bg-indigo-600/15 hover:text-indigo-300 text-left transition cursor-pointer disabled:opacity-50"
        >
          <Wand2 className="w-3.5 h-3.5 text-indigo-400" />
          Guided Wizard
        </button>
      )}

      {onAdvisor && (
        <button
          type="button"
          onClick={() => {
            setOpen(false);
            onAdvisor();
          }}
          className="w-full flex items-center gap-2.5 px-3.5 py-2 text-gray-200 hover:bg-blue-600/15 hover:text-blue-300 text-left transition cursor-pointer"
        >
          <MessageSquare className="w-3.5 h-3.5 text-sky-400" />
          Advisor & Guide
        </button>
      )}

      {advisorUrl && (
        <a
          href={advisorUrl}
          target="_blank"
          rel="noopener noreferrer"
          onClick={() => setOpen(false)}
          className="w-full flex items-center gap-2.5 px-3.5 py-2 text-gray-400 hover:bg-white/5 hover:text-white text-left transition"
        >
          <ExternalLink className="w-3.5 h-3.5 text-gray-500" />
          Open in Chat UI
        </a>
      )}

      {!isBase && onDelete && (
        <>
          <div className="my-1 border-t border-white/10" />
          <button
            type="button"
            onClick={() => {
              setOpen(false);
              onDelete();
            }}
            disabled={loading}
            className="w-full flex items-center gap-2.5 px-3.5 py-2 text-red-400 hover:bg-red-500/15 hover:text-red-300 text-left transition cursor-pointer font-semibold disabled:opacity-50"
          >
            <Trash2 className="w-3.5 h-3.5" />
            Uninstall Module
          </button>
        </>
      )}
    </div>
  );

  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        onClick={handleToggle}
        className="p-1.5 rounded-lg text-gray-400 hover:text-white hover:bg-white/10 transition cursor-pointer"
        title="More actions"
      >
        <MoreVertical className="w-4 h-4" />
      </button>

      {mounted && typeof document !== "undefined" && menuContent && createPortal(menuContent, document.body)}
    </>
  );
}

export function McpDataTable({
  items,
  loading = false,
  probingSlug = null,
  onEdit,
  onProbe,
  onWizard,
  onManageTools,
  onDelete,
  onAdvisor,
  advisorUrl,
}: McpDataTableProps) {
  if (items.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center rounded-2xl border border-white/5 bg-[#121212]/40 px-6 py-20 text-center">
        <Box className="mb-3 h-10 w-10 text-gray-600 animate-pulse" aria-hidden />
        <p className="text-sm font-semibold text-gray-300">No installed MCPs found</p>
        <p className="mt-1 max-w-sm text-xs text-gray-500">
          No MCP servers match the current search filters.
        </p>
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-2xl border border-white/10 bg-[#121212]/90 shadow-2xl backdrop-blur-md">
      <div className="overflow-x-auto">
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className="border-b border-white/10 bg-white/[0.02] text-[11px] font-bold uppercase tracking-wider text-gray-400 font-mono">
              <th scope="col" className="py-4 pl-6 pr-4">Module</th>
              <th scope="col" className="px-4 py-4">Status</th>
              <th scope="col" className="px-4 py-4">Scope</th>
              <th scope="col" className="px-4 py-4">Runtime</th>
              <th scope="col" className="py-4 pl-4 pr-6 text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/5 text-sm">
            {items.map((item) => {
              const { name, config, policy, connector, issues = [] } = item;
              const isProbingThis = probingSlug === name;
              const hasIssues = issues.length > 0;
              const awaitingAdminOAuth = oauthAdminSetupPending(
                policy?.oauth_config,
                connector,
                config
              );
              const isBase = Boolean(config.is_base);
              const displayName =
                policy?.display_name && policy.display_name !== name
                  ? policy.display_name
                  : null;
              const connectorId =
                policy?.aion_connector_id || config.aion_connector_id;
              const typeMeta = installTypeMeta(config.type);
              const TypeIcon = typeMeta.icon;

              const scopeMode = policy?.credential_mode || "none";

              return (
                <tr
                  key={name}
                  className="group hover:bg-white/[0.03] transition-colors duration-150"
                >
                  {/* Modulo (Icon + Name + Description) */}
                  <td className="py-4 pl-6 pr-4 align-middle">
                    <div className="flex items-center gap-3.5">
                      <div
                        className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border ${
                          isProbingThis
                            ? "border-sky-500/40 bg-sky-500/15 text-sky-300"
                            : hasIssues
                            ? "border-amber-500/30 bg-amber-500/10 text-amber-400"
                            : awaitingAdminOAuth
                            ? "border-sky-500/30 bg-sky-500/10 text-sky-400"
                            : isBase
                            ? "border-blue-500/30 bg-blue-500/10 text-blue-400"
                            : "border-white/10 bg-white/5 text-gray-300 group-hover:border-blue-500/40 group-hover:text-blue-400"
                        } transition-colors`}
                      >
                        {isProbingThis ? (
                          <Loader2 className="w-5 h-5 animate-spin text-sky-400" />
                        ) : config.type === "sse" || config.type === "remote-bridge" ? (
                          <Globe className="w-5 h-5" />
                        ) : config.type === "in_process" ? (
                          <Box className="w-5 h-5" />
                        ) : (
                          <Terminal className="w-5 h-5" />
                        )}
                      </div>

                      <div className="min-w-0 max-w-sm">
                        <div className="flex items-center gap-2">
                          <span className="font-mono font-bold text-white text-sm group-hover:text-blue-300 transition-colors">
                            {name}
                          </span>
                          {connectorId && (
                            <span className="rounded-md border border-white/10 bg-white/5 px-1.5 py-0.5 font-mono text-[10px] text-gray-400">
                              {connectorId}
                            </span>
                          )}
                        </div>
                        {displayName ? (
                          <p className="truncate text-xs text-gray-400 font-medium mt-0.5">
                            {displayName}
                          </p>
                        ) : config.description ? (
                          <p className="truncate text-xs text-gray-500 mt-0.5">
                            {config.description}
                          </p>
                        ) : null}
                      </div>
                    </div>
                  </td>

                  {/* Status Indicator (Observability Badge with Pulsing Dot) */}
                  <td className="px-4 py-4 align-middle whitespace-nowrap">
                    {isProbingThis ? (
                      <span className="inline-flex items-center gap-1.5 rounded-full border border-sky-500/40 bg-sky-500/15 px-3 py-1 text-xs font-semibold text-sky-300 shadow-sm shadow-sky-500/10 animate-pulse">
                        <Loader2 className="h-3.5 w-3.5 text-sky-400 animate-spin" />
                        Probing...
                      </span>
                    ) : hasIssues ? (
                      <span className="inline-flex items-center gap-1.5 rounded-full border border-amber-500/30 bg-amber-500/10 px-3 py-1 text-xs font-semibold text-amber-300">
                        <span className="h-2 w-2 rounded-full bg-amber-500 animate-pulse" />
                        Warning
                      </span>
                    ) : awaitingAdminOAuth ? (
                      <span className="inline-flex items-center gap-1.5 rounded-full border border-sky-500/30 bg-sky-500/10 px-3 py-1 text-xs font-semibold text-sky-300">
                        <span className="h-2 w-2 rounded-full bg-sky-400 animate-pulse" />
                        OAuth Pending
                      </span>
                    ) : isBase ? (
                      <span className="inline-flex items-center gap-1.5 rounded-full border border-blue-500/30 bg-blue-500/10 px-3 py-1 text-xs font-semibold text-blue-300">
                        <span className="h-2 w-2 rounded-full bg-blue-400" />
                        System
                      </span>
                    ) : policy?.is_enabled_for_users === false ? (
                      <span className="inline-flex items-center gap-1.5 rounded-full border border-zinc-700 bg-zinc-800/80 px-3 py-1 text-xs font-semibold text-zinc-400">
                        <span className="h-2 w-2 rounded-full bg-zinc-500" />
                        Disabled
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-3 py-1 text-xs font-semibold text-emerald-300">
                        <span className="h-2 w-2 rounded-full bg-emerald-500 animate-pulse" />
                        Active
                      </span>
                    )}
                  </td>

                  {/* Scope Badge */}
                  <td className="px-4 py-4 align-middle whitespace-nowrap">
                    {scopeMode === "org_shared" ? (
                      <span className="inline-flex items-center gap-1.5 rounded-lg border border-blue-500/30 bg-blue-500/15 px-2.5 py-1 text-xs font-bold text-blue-300">
                        <ShieldCheck className="w-3.5 h-3.5" />
                        Global (Org)
                      </span>
                    ) : scopeMode === "per_user" ? (
                      <span className="inline-flex items-center gap-1.5 rounded-lg border border-purple-500/30 bg-purple-500/15 px-2.5 py-1 text-xs font-bold text-purple-300">
                        <Users className="w-3.5 h-3.5" />
                        Per-User
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/5 px-2.5 py-1 text-xs font-semibold text-gray-400">
                        None
                      </span>
                    )}
                  </td>

                  {/* Runtime Type Badge */}
                  <td className="px-4 py-4 align-middle whitespace-nowrap">
                    <span
                      className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 font-mono text-xs font-medium ${typeMeta.colorClass}`}
                    >
                      <TypeIcon className="w-3.5 h-3.5" />
                      {typeMeta.label}
                    </span>
                  </td>

                  {/* Actions (Configure button + Dropdown menu) */}
                  <td className="py-4 pl-4 pr-6 align-middle text-right whitespace-nowrap">
                    <div className="flex items-center justify-end gap-2">
                      <button
                        type="button"
                        onClick={() => onEdit(name, config)}
                        className="inline-flex items-center gap-1.5 rounded-xl border border-blue-500/30 bg-blue-500/10 px-3.5 py-1.5 text-xs font-bold text-blue-400 hover:bg-blue-500/20 hover:border-blue-500/50 transition cursor-pointer shadow-sm shadow-blue-500/10"
                      >
                        <Settings2 className="w-3.5 h-3.5" />
                        Configure
                      </button>

                      <ActionDropdown
                        item={item}
                        loading={loading}
                        isProbing={isProbingThis}
                        onEdit={() => onEdit(name, config)}
                        onProbe={onProbe ? () => onProbe(name) : undefined}
                        onWizard={onWizard ? () => onWizard(name) : undefined}
                        onManageTools={onManageTools ? () => onManageTools(name) : undefined}
                        onDelete={onDelete ? () => onDelete(name) : undefined}
                        onAdvisor={onAdvisor ? () => onAdvisor(name) : undefined}
                        advisorUrl={advisorUrl ? advisorUrl(name) : undefined}
                      />
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
