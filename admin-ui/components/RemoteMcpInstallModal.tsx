"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Download,
  Globe,
  Loader2,
  ShieldCheck,
  X,
} from "lucide-react";
import { apiFetch } from "@/lib/api/headers";
import { apiBase } from "@/lib/api";

export type RemoteCatalogPreset = {
  id: string;
  title?: string;
  description?: string;
  remote_url?: string;
  remote_url_template?: boolean;
  auth_type?: string;
  official_doc_url?: string;
  featured_remote?: boolean;
  install_type?: string;
};

type RemoteProbe = {
  type?: string;
  url?: string;
  credential_mode?: string;
  oauth_provider?: string;
  oauth_server?: string;
  oauth_token_url?: string;
  hint?: string;
  remote_error?: string;
};

type RemoteMcpInstallModalProps = {
  open: boolean;
  onClose: () => void;
  onInstalled: (serverSlug: string) => void;
  presets?: RemoteCatalogPreset[];
  initialUrl?: string;
  initialDisplayName?: string;
  initialConnectorId?: string;
  installing?: boolean;
  onInstallStart?: () => void;
  onInstallEnd?: () => void;
};

const AUTH_TYPES = [
  { value: "auto", label: "Auto (probe)" },
  { value: "oauth2", label: "OAuth 2.0" },
  { value: "api-key", label: "API key / Bearer" },
  { value: "basic", label: "Basic auth" },
  { value: "none", label: "None" },
] as const;

export function RemoteMcpInstallModal({
  open,
  onClose,
  onInstalled,
  presets = [],
  initialUrl = "",
  initialDisplayName = "",
  initialConnectorId = "",
  installing = false,
  onInstallStart,
  onInstallEnd,
}: RemoteMcpInstallModalProps) {
  const [url, setUrl] = useState(initialUrl);
  const [displayName, setDisplayName] = useState(initialDisplayName);
  const [connectorId, setConnectorId] = useState(initialConnectorId);
  const [authType, setAuthType] = useState<string>("auto");
  const [probing, setProbing] = useState(false);
  const [probe, setProbe] = useState<RemoteProbe | null>(null);
  const [probeError, setProbeError] = useState<string | null>(null);
  const [localInstalling, setLocalInstalling] = useState(false);

  const busy = installing || localInstalling;

  useEffect(() => {
    if (!open) return;
    setUrl(initialUrl);
    setDisplayName(initialDisplayName);
    setConnectorId(initialConnectorId);
    setProbe(null);
    setProbeError(null);
    setAuthType("auto");
  }, [open, initialUrl, initialDisplayName, initialConnectorId]);

  const featuredPresets = useMemo(
    () => presets.filter((p) => p.remote_url),
    [presets],
  );

  const applyPreset = useCallback((preset: RemoteCatalogPreset) => {
    if (preset.remote_url) setUrl(preset.remote_url);
    if (preset.title) setDisplayName(preset.title);
    setConnectorId(preset.id);
    setProbe(null);
    setProbeError(null);
  }, []);

  const handleProbe = async () => {
    const trimmed = url.trim();
    if (!trimmed) {
      setProbeError("Enter a remote MCP URL.");
      return;
    }
    if (trimmed.includes("{") || trimmed.includes("}")) {
      setProbeError("Replace URL placeholders (e.g. {tenant_id}) before validating.");
      return;
    }
    setProbing(true);
    setProbeError(null);
    setProbe(null);
    try {
      const res = await apiFetch(`${apiBase()}/admin/mcp/probe-remote`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: trimmed }),
      });
      if (!res.ok) {
        let detail = `HTTP ${res.status}`;
        try {
          const body = await res.json();
          if (body?.detail != null) {
            detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
          }
        } catch {
          /* ignore */
        }
        throw new Error(detail);
      }
      const data = await res.json();
      setProbe((data.probe as RemoteProbe) || null);
      if (authType === "auto" && data.probe?.type) {
        const t = String(data.probe.type);
        if (["none", "oauth2", "api-key", "basic"].includes(t)) {
          setAuthType(t);
        }
      }
    } catch (e: unknown) {
      setProbeError(e instanceof Error ? e.message : String(e));
    } finally {
      setProbing(false);
    }
  };

  const handleInstall = async () => {
    const trimmed = url.trim();
    if (!trimmed) {
      setProbeError("Enter a remote MCP URL.");
      return;
    }
    if (trimmed.includes("{") || trimmed.includes("}")) {
      setProbeError("Replace URL placeholders before installing.");
      return;
    }
    setLocalInstalling(true);
    onInstallStart?.();
    setProbeError(null);
    try {
      const payload: Record<string, string> = { url: trimmed };
      if (displayName.trim()) payload.display_name = displayName.trim();
      if (connectorId.trim()) payload.connector_id = connectorId.trim();
      if (authType !== "auto") payload.auth_type = authType;

      const res = await apiFetch(`${apiBase()}/admin/market/install-remote`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        let detail = `HTTP ${res.status}`;
        try {
          const body = await res.json();
          if (body?.detail != null) {
            detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
          }
        } catch {
          /* ignore */
        }
        throw new Error(detail);
      }
      const data = await res.json();
      onInstalled(String(data.name || data.server_slug || ""));
      onClose();
    } catch (e: unknown) {
      setProbeError(e instanceof Error ? e.message : String(e));
    } finally {
      setLocalInstalling(false);
      onInstallEnd?.();
    }
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[65] bg-black/75 flex items-center justify-center p-4">
      <div className="bg-[#1a1a1a] border border-white/10 rounded-2xl max-w-2xl w-full max-h-[90vh] overflow-y-auto p-6 space-y-5 shadow-2xl">
        <div className="flex justify-between items-start gap-4">
          <div>
            <h3 className="text-lg font-bold text-white flex items-center gap-2">
              <Globe className="w-5 h-5 text-indigo-400" />
              Remote MCP Server
            </h3>
            <p className="text-xs text-gray-500 mt-1 leading-relaxed">
              Connect to a hosted MCP endpoint from the catalog or enter a custom URL.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-gray-500 hover:text-white p-1 cursor-pointer"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {featuredPresets.length > 0 && (
          <div className="space-y-2">
            <p className="text-[10px] font-bold uppercase tracking-wider text-gray-400">
              Curated presets
            </p>
            <div className="flex flex-wrap gap-2">
              {featuredPresets.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  onClick={() => applyPreset(p)}
                  className="text-xs font-semibold px-3 py-1.5 rounded-lg border border-indigo-500/30 bg-indigo-500/10 text-indigo-200 hover:bg-indigo-500/20 cursor-pointer"
                  title={p.description || p.remote_url}
                >
                  {p.title || p.id}
                  {p.remote_url_template ? " *" : ""}
                </button>
              ))}
            </div>
            <p className="text-[10px] text-gray-600">* URL template — edit placeholders before validate/install</p>
          </div>
        )}

        <label className="block text-xs font-bold text-gray-400 uppercase tracking-wider">
          Remote endpoint URL
          <input
            type="url"
            value={url}
            onChange={(e) => {
              setUrl(e.target.value);
              setProbe(null);
            }}
            placeholder="https://mcp.example.com/mcp"
            className="mt-1.5 w-full bg-black/40 border border-white/10 rounded-xl px-3 py-2.5 text-sm text-white placeholder:text-gray-600 focus:border-indigo-500/80 outline-none font-mono"
          />
        </label>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <label className="block text-xs font-bold text-gray-400 uppercase tracking-wider">
            Display name (optional)
            <input
              type="text"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder="my_remote_mcp"
              className="mt-1.5 w-full bg-black/40 border border-white/10 rounded-xl px-3 py-2.5 text-sm text-white placeholder:text-gray-600 focus:border-indigo-500/80 outline-none"
            />
          </label>
          <label className="block text-xs font-bold text-gray-400 uppercase tracking-wider">
            Auth type
            <select
              value={authType}
              onChange={(e) => setAuthType(e.target.value)}
              className="mt-1.5 w-full bg-black/40 border border-white/10 rounded-xl px-3 py-2.5 text-sm text-white focus:border-indigo-500/80 outline-none cursor-pointer"
            >
              {AUTH_TYPES.map((a) => (
                <option key={a.value} value={a.value} className="bg-[#1a1a1a]">
                  {a.label}
                </option>
              ))}
            </select>
          </label>
        </div>

        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => void handleProbe()}
            disabled={busy || probing || !url.trim()}
            className="flex items-center gap-2 px-4 py-2 text-sm font-bold text-emerald-300 bg-emerald-500/10 border border-emerald-500/25 rounded-xl hover:bg-emerald-500/20 disabled:opacity-50 cursor-pointer"
          >
            {probing ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <ShieldCheck className="w-4 h-4" />
            )}
            Validate endpoint
          </button>
        </div>

        {probeError && (
          <p className="text-sm text-red-400 flex items-start gap-2">
            <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
            {probeError}
          </p>
        )}

        {probe && (
          <div className="rounded-xl border border-white/10 bg-black/30 p-4 space-y-2 text-sm">
            <p className="flex items-center gap-2 text-emerald-400 font-semibold">
              <CheckCircle2 className="w-4 h-4" />
              Probe OK — {probe.type || "unknown"}
            </p>
            {probe.oauth_provider && (
              <p className="text-gray-400">
                Provider: <span className="text-white font-mono">{probe.oauth_provider}</span>
              </p>
            )}
            {probe.oauth_server && (
              <p className="text-gray-400 text-xs break-all">
                Auth server: <span className="text-gray-300">{probe.oauth_server}</span>
              </p>
            )}
            {probe.oauth_token_url && (
              <p className="text-gray-400 text-xs break-all">
                Token URL: <span className="text-gray-300">{probe.oauth_token_url}</span>
              </p>
            )}
            {probe.credential_mode && (
              <p className="text-gray-400">
                Suggested mode:{" "}
                <span className="text-indigo-300 font-mono">{probe.credential_mode}</span>
              </p>
            )}
            {probe.hint && (
              <p className="text-[11px] text-gray-500 font-mono break-all">{probe.hint}</p>
            )}
          </div>
        )}

        <div className="flex gap-3 justify-end pt-2 border-t border-white/5">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 text-sm text-gray-400 hover:text-white cursor-pointer"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => void handleInstall()}
            disabled={busy || !url.trim()}
            className="px-5 py-2.5 bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl text-sm font-bold disabled:opacity-50 cursor-pointer flex items-center gap-2"
          >
            {busy ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" /> Installing…
              </>
            ) : (
              <>
                <Download className="w-4 h-4" /> Install remote MCP
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
