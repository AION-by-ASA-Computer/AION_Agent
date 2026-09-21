"use client";

import { useEffect, useState, useMemo } from "react";
import {
  X,
  Loader2,
  Wrench,
  Search,
  CheckSquare,
  Square,
  AlertTriangle,
  Save,
  CheckCircle2,
} from "lucide-react";
import { apiFetch } from "@/lib/api/headers";
import { apiBase } from "@/lib/api";

interface ToolItem {
  name: string;
  description: string;
  enabled?: boolean;
}

interface McpToolsManageModalProps {
  serverSlug: string | null;
  open: boolean;
  onClose: () => void;
  onSaved?: () => void;
}

export function McpToolsManageModal({
  serverSlug,
  open,
  onClose,
  onSaved,
}: McpToolsManageModalProps) {
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const [tools, setTools] = useState<ToolItem[]>([]);
  const [selectedNames, setSelectedNames] = useState<Set<string>>(new Set());
  const [searchQuery, setSearchQuery] = useState("");

  useEffect(() => {
    if (!open || !serverSlug) {
      setTools([]);
      setSelectedNames(new Set());
      setError(null);
      setSuccessMsg(null);
      setSearchQuery("");
      return;
    }

    let isMounted = true;
    const fetchTools = async () => {
      setLoading(true);
      setError(null);
      setSuccessMsg(null);
      try {
        const res = await apiFetch(
          `${apiBase()}/admin/mcp/${encodeURIComponent(serverSlug)}/probe`,
          { method: "POST" }
        );
        const data = await res.json();
        if (!isMounted) return;

        if (!res.ok || !data.ok) {
          setError(data.error || "Failed to discover tools for this server.");
          return;
        }

        const discoveredTools: ToolItem[] = data.tools || [];
        setTools(discoveredTools);

        const activeTools = new Set<string>();
        discoveredTools.forEach((t) => {
          if (t.enabled !== false) {
            activeTools.add(t.name);
          }
        });
        setSelectedNames(activeTools);
      } catch (err: any) {
        if (!isMounted) return;
        setError(err.message || "Network error while probing server tools.");
      } finally {
        if (isMounted) setLoading(false);
      }
    };

    fetchTools();
    return () => {
      isMounted = false;
    };
  }, [open, serverSlug]);

  const filteredTools = useMemo(() => {
    if (!searchQuery.trim()) return tools;
    const q = searchQuery.toLowerCase();
    return tools.filter(
      (t) =>
        t.name.toLowerCase().includes(q) ||
        (t.description && t.description.toLowerCase().includes(q))
    );
  }, [tools, searchQuery]);

  const toggleTool = (name: string) => {
    setSelectedNames((prev) => {
      const next = new Set(prev);
      if (next.has(name)) {
        next.delete(name);
      } else {
        next.add(name);
      }
      return next;
    });
  };

  const handleSelectAll = () => {
    setSelectedNames(new Set(tools.map((t) => t.name)));
  };

  const handleDeselectAll = () => {
    setSelectedNames(new Set());
  };

  const handleSave = async () => {
    if (!serverSlug) return;
    setSaving(true);
    setError(null);
    setSuccessMsg(null);
    try {
      const enabledList = Array.from(selectedNames);
      const res = await apiFetch(
        `${apiBase()}/admin/mcp/${encodeURIComponent(serverSlug)}/tools-config`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ enabled_tools: enabledList }),
        }
      );
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || "Failed to save tool configuration.");
      }
      setSuccessMsg("Tools configuration saved successfully.");
      if (onSaved) onSaved();
      setTimeout(() => {
        onClose();
      }, 700);
    } catch (err: any) {
      setError(err.message || "Failed to save tools.");
    } finally {
      setSaving(false);
    }
  };

  if (!open || !serverSlug) return null;

  const totalCount = tools.length;
  const activeCount = selectedNames.size;
  const isHighTokenWarning = activeCount > 25;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-sm p-4 overflow-y-auto">
      <div className="relative w-full max-w-3xl bg-neutral-900 border border-neutral-800 rounded-2xl shadow-2xl overflow-hidden flex flex-col max-h-[88vh]">
        {/* Header */}
        <div className="flex items-center justify-between p-6 border-b border-neutral-800 bg-neutral-900/80">
          <div className="flex items-center gap-3">
            <div className="w-11 h-11 rounded-xl bg-violet-500/10 border border-violet-500/20 flex items-center justify-center text-violet-400">
              <Wrench className="w-6 h-6" />
            </div>
            <div>
              <h2 className="text-lg font-bold text-white flex items-center gap-2">
                Manage Tools: <span className="font-mono text-violet-400">{serverSlug}</span>
              </h2>
              <p className="text-xs text-neutral-400 mt-0.5">
                Enable only the tools you need to optimize agent speed and context window.
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-2 rounded-xl text-neutral-400 hover:text-white hover:bg-neutral-800 transition"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6 space-y-4">
          {error && (
            <div className="p-4 rounded-xl bg-red-500/10 border border-red-500/20 text-red-400 text-sm flex items-start gap-2.5">
              <AlertTriangle className="w-5 h-5 shrink-0 text-red-400 mt-0.5" />
              <div>
                <p className="font-semibold">Tool Discovery Notice</p>
                <p className="text-xs text-red-400/90 mt-0.5">{error}</p>
              </div>
            </div>
          )}

          {successMsg && (
            <div className="p-3.5 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-300 text-sm flex items-center gap-2">
              <CheckCircle2 className="w-4 h-4 text-emerald-400" />
              <span>{successMsg}</span>
            </div>
          )}

          {loading ? (
            <div className="flex flex-col items-center justify-center py-16 gap-3 text-neutral-400">
              <Loader2 className="w-8 h-8 animate-spin text-violet-400" />
              <p className="text-sm">Probing MCP server and fetching tool schemas...</p>
            </div>
          ) : tools.length === 0 && !error ? (
            <div className="text-center py-12 text-neutral-400 text-sm">
              No tools discovered for this server.
            </div>
          ) : (
            <>
              {/* Controls bar */}
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 bg-neutral-950/60 p-3.5 rounded-xl border border-neutral-800">
                <div className="relative flex-1">
                  <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-neutral-500" />
                  <input
                    type="text"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    placeholder="Filter tools by name or description..."
                    className="w-full pl-9 pr-3 py-1.5 rounded-lg bg-neutral-900 border border-neutral-800 text-xs text-white placeholder-neutral-500 focus:outline-none focus:border-violet-500"
                  />
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <button
                    type="button"
                    onClick={handleSelectAll}
                    className="px-2.5 py-1.5 rounded-lg bg-neutral-800 hover:bg-neutral-700 text-neutral-300 text-xs font-medium transition cursor-pointer flex items-center gap-1.5"
                  >
                    <CheckSquare className="w-3.5 h-3.5 text-violet-400" />
                    Select All
                  </button>
                  <button
                    type="button"
                    onClick={handleDeselectAll}
                    className="px-2.5 py-1.5 rounded-lg bg-neutral-800 hover:bg-neutral-700 text-neutral-300 text-xs font-medium transition cursor-pointer flex items-center gap-1.5"
                  >
                    <Square className="w-3.5 h-3.5 text-neutral-400" />
                    Deselect All
                  </button>
                </div>
              </div>

              {/* Status Badge */}
              <div className="flex items-center justify-between text-xs px-1">
                <div className="flex items-center gap-2">
                  <span className="font-semibold text-neutral-300">
                    Active Tools:
                  </span>
                  <span
                    className={`px-2 py-0.5 rounded-md font-mono font-bold ${
                      activeCount === 0
                        ? "bg-neutral-800 text-neutral-400"
                        : isHighTokenWarning
                        ? "bg-amber-500/10 text-amber-300 border border-amber-500/20"
                        : "bg-violet-500/10 text-violet-300 border border-violet-500/20"
                    }`}
                  >
                    {activeCount} / {totalCount}
                  </span>
                </div>
                {isHighTokenWarning && (
                  <div className="flex items-center gap-1.5 text-amber-400/90 text-[11px]">
                    <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
                    <span>Large tool count may consume significant prompt tokens.</span>
                  </div>
                )}
              </div>

              {/* Tools List */}
              <div className="space-y-2 max-h-[46vh] overflow-y-auto pr-1">
                {filteredTools.map((tool) => {
                  const isChecked = selectedNames.has(tool.name);
                  return (
                    <div
                      key={tool.name}
                      onClick={() => toggleTool(tool.name)}
                      className={`p-3 rounded-xl border transition cursor-pointer flex items-start gap-3 select-none ${
                        isChecked
                          ? "bg-violet-500/5 border-violet-500/30 hover:border-violet-500/50"
                          : "bg-neutral-900/40 border-neutral-800/80 hover:border-neutral-700 opacity-60 hover:opacity-100"
                      }`}
                    >
                      <input
                        type="checkbox"
                        checked={isChecked}
                        onChange={() => toggleTool(tool.name)}
                        onClick={(e) => e.stopPropagation()}
                        className="mt-0.5 rounded border-neutral-700 text-violet-600 focus:ring-violet-500 cursor-pointer"
                      />
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center justify-between gap-2">
                          <span className="font-mono text-xs font-bold text-white">
                            {tool.name}
                          </span>
                          {isChecked ? (
                            <span className="text-[10px] px-1.5 py-0.5 rounded bg-violet-500/20 text-violet-300 font-medium">
                              Active
                            </span>
                          ) : (
                            <span className="text-[10px] px-1.5 py-0.5 rounded bg-neutral-800 text-neutral-400">
                              Disabled
                            </span>
                          )}
                        </div>
                        {tool.description && (
                          <p className="text-xs text-neutral-400 mt-1 line-clamp-2">
                            {tool.description}
                          </p>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between p-4 border-t border-neutral-800 bg-neutral-900/80">
          <div className="text-xs text-neutral-500">
            {activeCount === 0 ? "⚠️ Agent will not see any tool from this MCP" : `${activeCount} tool(s) will be exposed to the agent`}
          </div>
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 rounded-xl text-neutral-400 hover:text-white hover:bg-neutral-800 text-xs font-semibold transition cursor-pointer"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleSave}
              disabled={saving || loading}
              className="px-5 py-2 rounded-xl bg-violet-600 hover:bg-violet-500 text-white text-xs font-bold transition flex items-center gap-2 shadow-lg shadow-violet-600/20 cursor-pointer disabled:opacity-50"
            >
              {saving ? (
                <>
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  Saving...
                </>
              ) : (
                <>
                  <Save className="w-3.5 h-3.5" />
                  Save Active Tools
                </>
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
