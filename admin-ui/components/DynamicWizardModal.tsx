"use client";

import { useEffect, useState, useCallback } from "react";
import {
  X,
  Loader2,
  Shield,
  ShieldCheck,
  Users,
  KeyRound,
  Eye,
  EyeOff,
  CheckCircle2,
  AlertCircle,
  Sparkles,
  Terminal,
  Plus,
  Trash2,
  Package,
  Globe,
  Info,
  Wrench,
  Search,
} from "lucide-react";
import { apiFetch } from "@/lib/api/headers";
import { apiBase } from "@/lib/api";
import { resolveGithubMarketplaceUrl } from "@/lib/githubUrl";

export interface EnvField {
  key: string;
  description?: string;
  required?: boolean;
  is_secret?: boolean;
  default?: string;
  value?: string;
}

export interface CliArgField {
  name: string;
  description?: string;
  required?: boolean;
  default?: string;
  placeholder?: string;
  value?: string;
}

export interface DynamicWizardTarget {
  id?: string;
  qualified_name?: string;
  display_name?: string;
  description?: string;
  icon_url?: string;
  runner?: "npx" | "uvx" | "node" | string;
  package_url?: string;
  required_envs?: EnvField[];
  cli_args?: CliArgField[];
  source?: string;
  url?: string;
  is_remote?: boolean;
  deployment_url?: string;
  remote_url?: string;
  auth_type?: string;
  install_type?: string;
  command_args?: string[];
}

interface DynamicWizardModalProps {
  open: boolean;
  target: DynamicWizardTarget | null;
  onClose: () => void;
  onInstalled: (serverSlug: string) => void;
}

export function DynamicWizardModal({
  open,
  target,
  onClose,
  onInstalled,
}: DynamicWizardModalProps) {
  const [loadingSchema, setLoadingSchema] = useState(false);
  const [installing, setInstalling] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [displayName, setDisplayName] = useState("");
  const [serverSlug, setServerSlug] = useState("");
  const [description, setDescription] = useState("");
  const [runner, setRunner] = useState<"npx" | "uvx">("npx");
  const [packageUrl, setPackageUrl] = useState("");
  const [iconUrl, setIconUrl] = useState("");
  const [isRemote, setIsRemote] = useState(false);
  const [remoteUrl, setRemoteUrl] = useState("");
  const [authType, setAuthType] = useState("oauth2");

  const [credentialMode, setCredentialMode] = useState<"org_shared" | "per_user" | "none">("org_shared");
  const [envs, setEnvs] = useState<EnvField[]>([]);
  const [showSecret, setShowSecret] = useState<Record<string, boolean>>({});
  const [commandArgs, setCommandArgs] = useState<string[] | null>(null);
  const [githubSource, setGithubSource] = useState(false);

  // CLI positional args (e.g. allowed directories for filesystem MCP)
  const [cliArgs, setCliArgs] = useState<CliArgField[]>([]);

  const [customKey, setCustomKey] = useState("");
  const [customVal, setCustomVal] = useState("");
  const [customDescription, setCustomDescription] = useState("");
  const [customRequired, setCustomRequired] = useState(true);
  const [customIsSecret, setCustomIsSecret] = useState(true);

  // Tools Management state
  const [discoveredTools, setDiscoveredTools] = useState<Array<{ name: string; description: string }>>([]);
  const [selectedTools, setSelectedTools] = useState<Set<string>>(new Set());
  const [discoveringTools, setDiscoveringTools] = useState(false);
  const [toolSearchQuery, setToolSearchQuery] = useState("");
  const [toolDiscoveryError, setToolDiscoveryError] = useState<string | null>(null);

  const toggleRequired = (key: string) => {
    setEnvs((prev) =>
      prev.map((e) => (e.key === key ? { ...e, required: !e.required } : e))
    );
  };

  const toggleSecret = (key: string) => {
    setEnvs((prev) =>
      prev.map((e) => (e.key === key ? { ...e, is_secret: !e.is_secret } : e))
    );
  };

  const handleDiscoverTools = async () => {
    setDiscoveringTools(true);
    setToolDiscoveryError(null);
    try {
      const envDict: Record<string, string> = {};
      const secretKeysList: string[] = [];
      envs.forEach((env) => {
        if (env.value !== undefined && env.value.trim() !== "") {
          envDict[env.key] = env.value.trim();
        }
        if (env.is_secret) {
          secretKeysList.push(env.key);
        }
      });

      let finalCommandArgs = commandArgs && commandArgs.length > 0 ? [...commandArgs] : undefined;
      if (cliArgs.length > 0) {
        const runnerPrefix = runner === "uvx" ? [packageUrl] : ["-y", packageUrl];
        const userArgs = cliArgs
          .map((a) => (a.value || a.default || "").trim())
          .filter(Boolean);
        finalCommandArgs = [...runnerPrefix, ...userArgs];
      }

      const candidateBody = {
        runner: isRemote ? "node" : runner,
        package_url: isRemote ? (remoteUrl || packageUrl) : packageUrl,
        command_args: finalCommandArgs,
        envs: envDict,
        secret_keys: secretKeysList,
        is_remote: isRemote,
        remote_url: isRemote ? (remoteUrl || packageUrl) : undefined,
        auth_type: isRemote ? authType : undefined,
      };

      const res = await apiFetch(`${apiBase()}/admin/market/probe-candidate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(candidateBody),
      });
      const data = await res.json();
      if (!res.ok || !data.ok) {
        setToolDiscoveryError(data.error || "Failed to discover tools with current parameters.");
        return;
      }
      const toolsList: Array<{ name: string; description: string }> = data.tools || [];
      setDiscoveredTools(toolsList);
      setSelectedTools(new Set(toolsList.map((t) => t.name)));
    } catch (err: any) {
      setToolDiscoveryError(err.message || "Network error during tool probe.");
    } finally {
      setDiscoveringTools(false);
    }
  };

  const toggleSingleTool = (toolName: string) => {
    setSelectedTools((prev) => {
      const next = new Set(prev);
      if (next.has(toolName)) next.delete(toolName);
      else next.add(toolName);
      return next;
    });
  };

  const handleSelectAllTools = () => {
    setSelectedTools(new Set(discoveredTools.map((t) => t.name)));
  };

  const handleDeselectAllTools = () => {
    setSelectedTools(new Set());
  };

  const initFromTarget = useCallback(async (tgt: DynamicWizardTarget) => {
    setError(null);
    setCommandArgs(null);
    setGithubSource(false);
    setDiscoveredTools([]);
    setSelectedTools(new Set());
    setToolDiscoveryError(null);
    setToolSearchQuery("");
    setCliArgs([]);
    const initialName = tgt.display_name || tgt.qualified_name || "mcp_server";
    setDisplayName(initialName);
    const initialSlug = (tgt.qualified_name || initialName)
      .toLowerCase()
      .replace(/[^a-z0-9_-]+/g, "_")
      .replace(/^_+|_+$/g, "");
    setServerSlug(initialSlug);
    setDescription(tgt.description || "");
    setRunner(tgt.runner === "uvx" ? "uvx" : "npx");
    setPackageUrl(tgt.package_url || tgt.qualified_name || initialSlug);
    setIconUrl(tgt.icon_url || "");
    const initialRemote = Boolean(tgt.is_remote || tgt.install_type === "remote" || tgt.deployment_url);
    setIsRemote(initialRemote);
    setRemoteUrl(tgt.remote_url || tgt.deployment_url || "");
    if (tgt.command_args && tgt.command_args.length > 0) {
      setCommandArgs(tgt.command_args);
    }

    // If required_envs are already supplied (e.g. from GitHub analysis)
    if (tgt.required_envs && tgt.required_envs.length > 0) {
      setCredentialMode("org_shared");
      setEnvs(
        tgt.required_envs.map((e) => ({
          ...e,
          value: e.default || "",
        }))
      );
    }

    // If cli_args are supplied (e.g. allowed directories for filesystem MCP)
    if (tgt.cli_args && tgt.cli_args.length > 0) {
      setCliArgs(
        tgt.cli_args.map((a) => ({
          ...a,
          value: a.default || "",
        }))
      );
    }

    if (!tgt.required_envs?.length && !tgt.cli_args?.length) {
      // will fall through to Smithery/GitHub analyze below
    } else {
      return;
    }

    const ghUrl = resolveGithubMarketplaceUrl(tgt);

    // Validated github.com repo URL only — use the zero-clone GitHub analyzer
    if (ghUrl) {
      setLoadingSchema(true);
      try {
        const res = await apiFetch(`${apiBase()}/admin/market/analyze-github`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ url: ghUrl }),
        });
        if (res.ok) {
          const data = await res.json();
          if (data.runner) setRunner(data.runner === "uvx" ? "uvx" : "npx");
          if (data.package_url) setPackageUrl(data.package_url);
          if (data.description && !tgt.description) setDescription(data.description);
          if (data.command_args) setCommandArgs(data.command_args);
          setGithubSource(true);
          const schemaEnvs: EnvField[] = (data.required_envs || []).map((e: any) => ({
            key: e.key,
            description: e.description || "",
            required: !!e.required,
            is_secret: !!e.is_secret,
            default: e.default || "",
            value: e.default || "",
          }));
          setEnvs(schemaEnvs);
          const schemaCliArgs: CliArgField[] = (data.cli_args || []).map((a: any) => ({
            name: a.name,
            description: a.description || "",
            required: !!a.required,
            default: a.default || "",
            placeholder: a.placeholder || "",
            value: a.default || "",
          }));
          setCliArgs(schemaCliArgs);
          if (schemaEnvs.length > 0) {
            setCredentialMode("org_shared");
          } else if (schemaCliArgs.length > 0) {
            setCredentialMode("none"); // CLI args don't need credential mode
          } else {
            setCredentialMode("none");
          }
          return;
        }
      } catch (err: any) {
        console.warn("GitHub analyze failed, fallback to defaults:", err);
      } finally {
        setLoadingSchema(false);
      }
    }

    // Otherwise fetch details from Smithery config endpoint
    const qName = tgt.qualified_name || tgt.id?.replace("smithery:", "") || "";
    if (qName && !qName.includes("github:") && !qName.includes("claude:")) {
      setLoadingSchema(true);
      try {
        const res = await apiFetch(
          `${apiBase()}/admin/market/config?qualified_name=${encodeURIComponent(qName)}`
        );
        if (res.ok) {
          const data = await res.json();
          if (data.display_name) setDisplayName(data.display_name);
          if (data.description) setDescription(data.description);
          if (data.runner) setRunner(data.runner === "uvx" ? "uvx" : "npx");
          if (data.package_url) setPackageUrl(data.package_url);
          if (data.icon_url) setIconUrl(data.icon_url);
          if (data.command_args) setCommandArgs(data.command_args);
          if (data.is_remote !== undefined) setIsRemote(Boolean(data.is_remote));
          if (data.remote_url || data.deployment_url) setRemoteUrl(data.remote_url || data.deployment_url);
          if (data.auth_type) setAuthType(data.auth_type);
          if (data.credential_mode) setCredentialMode(data.credential_mode);

          const schemaEnvs: EnvField[] = (data.required_envs || []).map((e: any) => ({
            key: e.key,
            description: e.description || "",
            required: !!e.required,
            is_secret: !!e.is_secret,
            default: e.default || "",
            value: e.default || "",
          }));
          setEnvs(schemaEnvs);
          setCredentialMode(schemaEnvs.length > 0 ? (data.credential_mode || "org_shared") : "none");
        }
      } catch (err: any) {
        console.warn("Failed to fetch schema details:", err);
      } finally {
        setLoadingSchema(false);
      }
    } else {
      setEnvs([]);
      setCredentialMode("none");
    }
  }, []);

  useEffect(() => {
    if (open && target) {
      initFromTarget(target);
    }
  }, [open, target, initFromTarget]);

  if (!open || !target) return null;

  const handleEnvChange = (key: string, val: string) => {
    setEnvs((prev) =>
      prev.map((e) => (e.key === key ? { ...e, value: val } : e))
    );
  };

  const handleAddCustomEnv = () => {
    if (!customKey.trim()) return;
    const cleanKey = customKey.trim().toUpperCase().replace(/[^A-Z0-9_]/g, "_");
    if (envs.some((e) => e.key === cleanKey)) {
      setError(`Variable ${cleanKey} already exists.`);
      return;
    }
    setEnvs((prev) => [
      ...prev,
      {
        key: cleanKey,
        description:
          customDescription.trim() ||
          (credentialMode === "per_user"
            ? "Personal user key"
            : "Custom variable"),
        required: customRequired,
        is_secret: customIsSecret,
        default: "",
        value: credentialMode === "org_shared" ? customVal.trim() : "",
      },
    ]);
    setCustomKey("");
    setCustomVal("");
    setCustomDescription("");
    setCustomRequired(true);
    setCustomIsSecret(true);
    setError(null);
  };

  const handleRemoveEnv = (key: string) => {
    setEnvs((prev) => prev.filter((e) => e.key !== key));
  };

  const toggleSecretVisibility = (key: string) => {
    setShowSecret((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    setInstalling(true);
    try {
      const envDict: Record<string, string> = {};
      const secretKeysList: string[] = [];

      // If org_shared, gather values entered by the admin (if any)
      if (credentialMode === "org_shared") {
        envs.forEach((env) => {
          if (env.value !== undefined && env.value.trim() !== "") {
            envDict[env.key] = env.value.trim();
          }
          if (env.is_secret) {
            secretKeysList.push(env.key);
          }
        });
      }

      // Construct schema fields to preserve them in aion.db McpServerConfig
      const schemaFields = envs.map((e) => ({
        key: e.key,
        label: e.description || e.key.replace(/_/g, " ").toUpperCase(),
        required: e.required ?? true,
        is_secret: e.is_secret ?? true,
        description: e.description || "",
      }));

      const payload: Record<string, any> = {
        server_slug: serverSlug || displayName.toLowerCase().replace(/[^a-z0-9_-]/g, "_"),
        display_name: displayName,
        description: description,
        runner: isRemote ? "node" : runner,
        package_url: isRemote ? (remoteUrl || packageUrl) : packageUrl,
        envs: envDict,
        secret_keys: secretKeysList,
        schema_fields: schemaFields,
        credential_mode: credentialMode,
        icon_url: iconUrl,
        github_source: githubSource,
        is_remote: isRemote,
        remote_url: isRemote ? (remoteUrl || packageUrl) : undefined,
        auth_type: isRemote ? authType : undefined,
      };

      if (discoveredTools && discoveredTools.length > 0) {
        payload.enabled_tools = Array.from(selectedTools);
      }

      // Build final command_args: start from template, replace placeholders with user-provided CLI arg values
      let finalCommandArgs = commandArgs ? [...commandArgs] : null;
      if (cliArgs.length > 0) {
        // Build base args: runner prefix + package + user positional args
        const runnerPrefix = runner === "uvx" ? [packageUrl] : ["-y", packageUrl];
        const userArgs = cliArgs
          .map((a) => (a.value || a.default || "").trim())
          .filter(Boolean);
        finalCommandArgs = [...runnerPrefix, ...userArgs];
      }

      if (finalCommandArgs && finalCommandArgs.length > 0) {
        payload.command_args = finalCommandArgs;
      }

      const res = await apiFetch(`${apiBase()}/admin/market/install-zero`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || "Zero-Install configuration failed.");
      }

      const data = await res.json();
      onInstalled(data.server_slug || payload.server_slug);
      onClose();
    } catch (err: any) {
      setError(err.message || "Installation failed.");
    } finally {
      setInstalling(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4 overflow-y-auto">
      <div className="relative w-full max-w-2xl bg-neutral-900 border border-neutral-800 rounded-2xl shadow-2xl overflow-hidden flex flex-col max-h-[90vh]">
        {/* Header */}
        <div className="flex items-start justify-between p-6 border-b border-neutral-800 bg-neutral-900/60">
          <div className="flex items-center gap-4">
            {iconUrl ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={iconUrl}
                alt={displayName}
                className="w-12 h-12 rounded-xl object-contain bg-neutral-800 p-1 border border-neutral-700"
                onError={(e) => {
                  (e.target as HTMLElement).style.display = "none";
                }}
              />
            ) : (
              <div className="w-12 h-12 rounded-xl bg-violet-500/10 border border-violet-500/20 flex items-center justify-center text-violet-400">
                <Package className="w-6 h-6" />
              </div>
            )}
            <div>
              <div className="flex items-center gap-2">
                <h3 className="text-xl font-bold text-neutral-100">{displayName}</h3>
                {isRemote && (
                  <span className="text-[10px] uppercase font-bold tracking-wider px-2 py-0.5 rounded bg-sky-500/20 text-sky-300 border border-sky-500/30">
                    Remote Bridge (SSE)
                  </span>
                )}
              </div>
              <p className="text-xs text-neutral-400 mt-1 max-w-md line-clamp-2">
                {description || "Configure and run this MCP server on-demand without local disk installation."}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-2 text-neutral-400 hover:text-neutral-100 hover:bg-neutral-800 rounded-xl transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content / Form */}
        <form onSubmit={handleSubmit} className="flex-1 overflow-y-auto p-6 space-y-6">
          {error && (
            <div className="flex items-start gap-3 p-4 bg-red-500/10 border border-red-500/20 rounded-xl text-red-400 text-sm">
              <AlertCircle className="w-5 h-5 shrink-0 mt-0.5" />
              <div>{error}</div>
            </div>
          )}

          {loadingSchema ? (
            <div className="flex flex-col items-center justify-center py-12 text-neutral-400 gap-3">
              <Loader2 className="w-8 h-8 animate-spin text-violet-400" />
              <p className="text-sm">Fetching configuration schema...</p>
            </div>
          ) : (
            <>
              {/* Basic Runner Settings */}
              {isRemote ? (
                <div className="p-4 rounded-xl bg-sky-950/20 border border-sky-500/25 space-y-2">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2 text-sky-400 text-xs font-bold uppercase tracking-wider">
                      <Globe className="w-4 h-4" /> Smithery / SSE Remote Endpoint
                    </div>
                    <span className="text-[11px] font-mono text-neutral-400 bg-neutral-900/80 px-2 py-0.5 rounded border border-neutral-700">
                      mcp-remote bridge ({authType})
                    </span>
                  </div>
                  <div className="text-xs font-mono text-sky-200 break-all bg-neutral-950/60 p-2.5 rounded-lg border border-sky-500/15">
                    {remoteUrl || packageUrl}
                  </div>
                </div>
              ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div>
                    <label className="block text-xs font-medium text-neutral-400 mb-1.5">
                      Package Identifier / URL
                    </label>
                    <div className="relative">
                      <input
                        type="text"
                        value={packageUrl}
                        onChange={(e) => setPackageUrl(e.target.value)}
                        required
                        placeholder="e.g. @modelcontextprotocol/server-postgres"
                        className="w-full bg-neutral-950 border border-neutral-800 rounded-xl px-3.5 py-2.5 text-sm text-neutral-200 placeholder-neutral-500 focus:outline-none focus:border-violet-500 transition-colors font-mono"
                      />
                    </div>
                  </div>

                  <div>
                    <label className="block text-xs font-medium text-neutral-400 mb-1.5">
                      Execution Runner
                    </label>
                    <div className="grid grid-cols-2 gap-2">
                      <button
                        type="button"
                        onClick={() => setRunner("npx")}
                        className={`flex items-center justify-center gap-2 py-2 px-3 rounded-xl border text-sm font-medium transition-all ${runner === "npx"
                          ? "bg-violet-600/10 border-violet-500/40 text-violet-300 shadow-sm"
                          : "bg-neutral-950 border-neutral-800 text-neutral-400 hover:text-neutral-200 hover:border-neutral-700"
                          }`}
                      >
                        <Terminal className="w-4 h-4" /> npx -y (Node)
                      </button>
                      <button
                        type="button"
                        onClick={() => setRunner("uvx")}
                        className={`flex items-center justify-center gap-2 py-2 px-3 rounded-xl border text-sm font-medium transition-all ${runner === "uvx"
                          ? "bg-violet-600/10 border-violet-500/40 text-violet-300 shadow-sm"
                          : "bg-neutral-950 border-neutral-800 text-neutral-400 hover:text-neutral-200 hover:border-neutral-700"
                          }`}
                      >
                        <Terminal className="w-4 h-4" /> uvx (Python)
                      </button>
                    </div>
                  </div>
                </div>
              )}

              {/* Credential Mode / Scope Selector */}
              <div className="space-y-3 pt-2">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Shield className="w-4 h-4 text-violet-400" />
                    <label className="text-sm font-semibold text-neutral-200">
                      Credential Mode (Configuration Scope)
                    </label>
                  </div>
                  <span className="text-[11px] text-neutral-500">
                    Choose how and by whom credentials will be provided
                  </span>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5">
                  <button
                    type="button"
                    onClick={() => setCredentialMode("org_shared")}
                    className={`p-3 rounded-xl border text-left flex flex-col gap-1 transition-all ${credentialMode === "org_shared"
                      ? "bg-violet-600/15 border-violet-500/50 text-neutral-100 ring-1 ring-violet-500/30"
                      : "bg-neutral-950 border-neutral-800 text-neutral-400 hover:text-neutral-200 hover:border-neutral-700"
                      }`}
                  >
                    <div className="flex items-center gap-1.5 font-semibold text-xs text-violet-300">
                      <ShieldCheck className="w-4 h-4 text-violet-400" /> Organization
                    </div>
                    <div className="text-[11px] text-neutral-400 leading-tight">
                      Global shared. Enter now or configure later.
                    </div>
                  </button>

                  <button
                    type="button"
                    onClick={() => setCredentialMode("per_user")}
                    className={`p-3 rounded-xl border text-left flex flex-col gap-1 transition-all ${credentialMode === "per_user"
                      ? "bg-violet-600/15 border-violet-500/50 text-neutral-100 ring-1 ring-violet-500/30"
                      : "bg-neutral-950 border-neutral-800 text-neutral-400 hover:text-neutral-200 hover:border-neutral-700"
                      }`}
                  >
                    <div className="flex items-center gap-1.5 font-semibold text-xs text-indigo-300">
                      <Users className="w-4 h-4 text-indigo-400" /> Personal (Per-User)
                    </div>
                    <div className="text-[11px] text-neutral-400 leading-tight">
                      Each user enters their own key in Chat.
                    </div>
                  </button>

                  <button
                    type="button"
                    onClick={() => setCredentialMode("none")}
                    className={`p-3 rounded-xl border text-left flex flex-col gap-1 transition-all ${credentialMode === "none"
                      ? "bg-violet-600/15 border-violet-500/50 text-neutral-100 ring-1 ring-violet-500/30"
                      : "bg-neutral-950 border-neutral-800 text-neutral-400 hover:text-neutral-200 hover:border-neutral-700"
                      }`}
                  >
                    <div className="flex items-center gap-1.5 font-semibold text-xs text-neutral-300">
                      <Globe className="w-4 h-4 text-neutral-400" /> No Configuration
                    </div>
                    <div className="text-[11px] text-neutral-400 leading-tight">
                      No keys required or authentication disabled.
                    </div>
                  </button>
                </div>
              </div>

              {/* Dynamic Credential Explanation & Input Form */}
              {credentialMode === "none" ? (
                <div className="p-4 bg-neutral-950/60 border border-neutral-800/80 rounded-xl text-neutral-400 text-xs flex items-center gap-3">
                  <Info className="w-4 h-4 text-neutral-400 shrink-0" />
                  <div>
                    This MCP server will run without requiring authentication keys or credentials.
                  </div>
                </div>
              ) : credentialMode === "per_user" ? (
                <div className="space-y-4">
                  <div className="p-3.5 bg-indigo-500/10 border border-indigo-500/20 rounded-xl text-xs text-indigo-300 flex items-start gap-2.5">
                    <Users className="w-4 h-4 text-indigo-400 shrink-0 mt-0.5" />
                    <div>
                      <span className="font-semibold text-indigo-200">Personal User Configuration:</span> It is not necessary to enter values now. The fields below will be prompted automatically to each user in the <span className="font-semibold text-white">&quot;My Integrations&quot;</span> chat panel.
                    </div>
                  </div>

                  <div className="space-y-2.5">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-semibold text-neutral-300">
                        Credential fields requested from users:
                      </span>
                      <span className="text-[11px] text-neutral-500">
                        Click badges to toggle Required or Secret
                      </span>
                    </div>

                    {envs.length === 0 ? (
                      <div className="p-3 bg-neutral-950 border border-neutral-800 rounded-xl text-neutral-400 text-xs">
                        No fields detected. You can add a custom one below.
                      </div>
                    ) : (
                      <div className="space-y-2">
                        {envs.map((env) => (
                          <div
                            key={env.key}
                            className="p-3 bg-neutral-950 border border-neutral-800 rounded-xl flex items-center justify-between gap-3"
                          >
                            <div className="min-w-0 flex-1">
                              <div className="flex flex-wrap items-center gap-2">
                                <span className="text-xs font-mono font-semibold text-neutral-200">
                                  {env.key}
                                </span>
                                <button
                                  type="button"
                                  onClick={() => toggleRequired(env.key)}
                                  className={`text-[10px] uppercase font-bold tracking-wider px-2 py-0.5 rounded border transition-all cursor-pointer select-none ${env.required
                                    ? "bg-amber-500/15 text-amber-400 border-amber-500/30 hover:bg-amber-500/25"
                                    : "bg-neutral-800 text-neutral-400 border-neutral-700 hover:text-neutral-200"
                                    }`}
                                  title="Click to toggle required status"
                                >
                                  {env.required ? "Required" : "Optional"}
                                </button>
                                <button
                                  type="button"
                                  onClick={() => toggleSecret(env.key)}
                                  className={`inline-flex items-center gap-1 text-[10px] uppercase font-bold tracking-wider px-2 py-0.5 rounded border transition-all cursor-pointer select-none ${env.is_secret
                                    ? "bg-violet-500/15 text-violet-400 border-violet-500/30 hover:bg-violet-500/25"
                                    : "bg-neutral-800 text-neutral-400 border-neutral-700 hover:text-neutral-200"
                                    }`}
                                  title="Click to toggle data type (Secret / Plaintext)"
                                >
                                  <Shield className="w-2.5 h-2.5" /> {env.is_secret ? "Secret" : "Plaintext"}
                                </button>
                              </div>
                              {env.description && (
                                <p className="text-[11px] text-neutral-400 mt-1 truncate">
                                  {env.description}
                                </p>
                              )}
                            </div>
                            <button
                              type="button"
                              onClick={() => handleRemoveEnv(env.key)}
                              className="text-neutral-500 hover:text-red-400 p-1.5 rounded-lg hover:bg-red-500/10 transition-colors shrink-0"
                              title="Remove field"
                            >
                              <Trash2 className="w-4 h-4" />
                            </button>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>

                  {/* Add Custom User Field Row */}
                  <div className="mt-3 p-3.5 bg-neutral-950/60 border border-dashed border-neutral-800 rounded-xl space-y-2.5">
                    <div className="text-xs font-medium text-neutral-300 flex items-center gap-1.5">
                      <Plus className="w-3.5 h-3.5 text-indigo-400" /> Add credential field for users
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      <input
                        type="text"
                        placeholder="KEY_NAME"
                        value={customKey}
                        onChange={(e) => setCustomKey(e.target.value)}
                        className="flex-1 min-w-[140px] bg-neutral-900 border border-neutral-800 rounded-lg px-3 py-1.5 text-xs text-neutral-200 uppercase font-mono placeholder-neutral-500 focus:outline-none focus:border-indigo-500"
                      />
                      <input
                        type="text"
                        placeholder="Description / Label (optional)"
                        value={customDescription}
                        onChange={(e) => setCustomDescription(e.target.value)}
                        className="flex-1 min-w-[180px] bg-neutral-900 border border-neutral-800 rounded-lg px-3 py-1.5 text-xs text-neutral-200 placeholder-neutral-500 focus:outline-none focus:border-indigo-500"
                      />
                    </div>
                    <div className="flex items-center justify-between pt-1">
                      <div className="flex items-center gap-4">
                        <label className="flex items-center gap-1.5 text-xs text-neutral-300 cursor-pointer select-none">
                          <input
                            type="checkbox"
                            checked={customRequired}
                            onChange={(e) => setCustomRequired(e.target.checked)}
                            className="rounded border-neutral-700 bg-neutral-900 text-amber-500 focus:ring-0 focus:ring-offset-0"
                          />
                          Required
                        </label>
                        <label className="flex items-center gap-1.5 text-xs text-neutral-300 cursor-pointer select-none">
                          <input
                            type="checkbox"
                            checked={customIsSecret}
                            onChange={(e) => setCustomIsSecret(e.target.checked)}
                            className="rounded border-neutral-700 bg-neutral-900 text-violet-500 focus:ring-0 focus:ring-offset-0"
                          />
                          Secret
                        </label>
                      </div>
                      <button
                        type="button"
                        onClick={handleAddCustomEnv}
                        disabled={!customKey.trim()}
                        className="px-3 py-1.5 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 text-white rounded-lg text-xs font-medium flex items-center gap-1 transition-colors"
                      >
                        <Plus className="w-3.5 h-3.5" /> Add Field
                      </button>
                    </div>
                  </div>
                </div>
              ) : (
                /* Org Shared Form */
                <div className="space-y-4">
                  <div>
                    <div className="flex items-center justify-between mb-1.5">
                      <div className="flex items-center gap-2">
                        <KeyRound className="w-4 h-4 text-violet-400" />
                        <h4 className="text-sm font-semibold text-neutral-200">
                          Environment Variables &amp; Secrets (Organization)
                        </h4>
                      </div>
                      <span className="text-[11px] text-neutral-500">
                        Secrets are encrypted with AES-GCM
                      </span>
                    </div>
                    <p className="text-xs text-neutral-400">
                      You can fill in values now or leave them blank and configure later in the Hub panel. Click badges to toggle Required or Secret.
                    </p>
                  </div>

                  {envs.length === 0 ? (
                    <div className="p-4 bg-neutral-950/60 border border-neutral-800/80 rounded-xl text-neutral-400 text-xs text-center">
                      No variables detected. Add a custom one if required.
                    </div>
                  ) : (
                    <div className="space-y-3">
                      {envs.map((env) => {
                        const isRevealed = showSecret[env.key] ?? false;
                        return (
                          <div
                            key={env.key}
                            className="p-3.5 bg-neutral-950 border border-neutral-800 rounded-xl space-y-1.5 transition-all focus-within:border-neutral-700"
                          >
                            <div className="flex items-center justify-between">
                              <div className="flex flex-wrap items-center gap-2">
                                <span className="text-xs font-mono font-semibold text-neutral-200">
                                  {env.key}
                                </span>
                                <button
                                  type="button"
                                  onClick={() => toggleRequired(env.key)}
                                  className={`text-[10px] uppercase font-bold tracking-wider px-2 py-0.5 rounded border transition-all cursor-pointer select-none ${env.required
                                    ? "bg-amber-500/15 text-amber-400 border-amber-500/30 hover:bg-amber-500/25"
                                    : "bg-neutral-800 text-neutral-400 border-neutral-700 hover:text-neutral-200"
                                    }`}
                                  title="Click to toggle required status"
                                >
                                  {env.required ? "Required" : "Optional"}
                                </button>
                                <button
                                  type="button"
                                  onClick={() => toggleSecret(env.key)}
                                  className={`inline-flex items-center gap-1 text-[10px] uppercase font-bold tracking-wider px-2 py-0.5 rounded border transition-all cursor-pointer select-none ${env.is_secret
                                    ? "bg-violet-500/15 text-violet-400 border-violet-500/30 hover:bg-violet-500/25"
                                    : "bg-neutral-800 text-neutral-400 border-neutral-700 hover:text-neutral-200"
                                    }`}
                                  title="Click to toggle data type (Secret / Plaintext)"
                                >
                                  <Shield className="w-2.5 h-2.5" /> {env.is_secret ? "Secret" : "Plaintext"}
                                </button>
                              </div>
                              <button
                                type="button"
                                onClick={() => handleRemoveEnv(env.key)}
                                className="text-neutral-500 hover:text-red-400 p-1.5 rounded-lg hover:bg-red-500/10 transition-colors shrink-0"
                                title="Remove variable"
                              >
                                <Trash2 className="w-4 h-4" />
                              </button>
                            </div>

                            {env.description && (
                              <p className="text-[11px] text-neutral-400 leading-tight">
                                {env.description}
                              </p>
                            )}

                            <div className="relative mt-1">
                              <input
                                type={env.is_secret && !isRevealed ? "password" : "text"}
                                value={env.value ?? ""}
                                onChange={(e) => handleEnvChange(env.key, e.target.value)}
                                placeholder={
                                  env.is_secret
                                    ? "Secret value (optional now, saved encrypted)"
                                    : env.default || "Enter value (optional now)"
                                }
                                className="w-full bg-neutral-900 border border-neutral-800 rounded-lg px-3 py-2 text-sm text-neutral-100 placeholder-neutral-600 focus:outline-none focus:border-violet-500 font-mono transition-colors pr-10"
                              />
                              {env.is_secret && (
                                <button
                                  type="button"
                                  onClick={() => toggleSecretVisibility(env.key)}
                                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-neutral-400 hover:text-neutral-200 p-1"
                                >
                                  {isRevealed ? (
                                    <EyeOff className="w-4 h-4" />
                                  ) : (
                                    <Eye className="w-4 h-4" />
                                  )}
                                </button>
                              )}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  )}

                  {/* Add Custom Env Row */}
                  <div className="mt-3 p-3.5 bg-neutral-950/60 border border-dashed border-neutral-800 rounded-xl space-y-2.5">
                    <div className="text-xs font-medium text-neutral-300 flex items-center gap-1.5">
                      <Plus className="w-3.5 h-3.5 text-violet-400" /> Add custom environment variable
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      <input
                        type="text"
                        placeholder="VARIABLE_NAME"
                        value={customKey}
                        onChange={(e) => setCustomKey(e.target.value)}
                        className="flex-1 min-w-[140px] bg-neutral-900 border border-neutral-800 rounded-lg px-3 py-1.5 text-xs text-neutral-200 uppercase font-mono placeholder-neutral-500 focus:outline-none focus:border-violet-500"
                      />
                      <input
                        type="text"
                        placeholder="Value (optional now)"
                        value={customVal}
                        onChange={(e) => setCustomVal(e.target.value)}
                        className="flex-1 min-w-[140px] bg-neutral-900 border border-neutral-800 rounded-lg px-3 py-1.5 text-xs text-neutral-200 font-mono placeholder-neutral-500 focus:outline-none focus:border-violet-500"
                      />
                      <input
                        type="text"
                        placeholder="Description (optional)"
                        value={customDescription}
                        onChange={(e) => setCustomDescription(e.target.value)}
                        className="flex-1 min-w-[160px] bg-neutral-900 border border-neutral-800 rounded-lg px-3 py-1.5 text-xs text-neutral-200 placeholder-neutral-500 focus:outline-none focus:border-violet-500"
                      />
                    </div>
                    <div className="flex items-center justify-between pt-1">
                      <div className="flex items-center gap-4">
                        <label className="flex items-center gap-1.5 text-xs text-neutral-300 cursor-pointer select-none">
                          <input
                            type="checkbox"
                            checked={customRequired}
                            onChange={(e) => setCustomRequired(e.target.checked)}
                            className="rounded border-neutral-700 bg-neutral-900 text-amber-500 focus:ring-0 focus:ring-offset-0"
                          />
                          Required
                        </label>
                        <label className="flex items-center gap-1.5 text-xs text-neutral-300 cursor-pointer select-none">
                          <input
                            type="checkbox"
                            checked={customIsSecret}
                            onChange={(e) => setCustomIsSecret(e.target.checked)}
                            className="rounded border-neutral-700 bg-neutral-900 text-violet-600 focus:ring-0 focus:ring-offset-0"
                          />
                          Secret
                        </label>
                      </div>
                      <button
                        type="button"
                        onClick={handleAddCustomEnv}
                        disabled={!customKey.trim()}
                        className="px-3 py-1.5 bg-violet-600 hover:bg-violet-500 disabled:opacity-40 text-white rounded-lg text-xs font-medium flex items-center gap-1 transition-colors"
                      >
                        <Plus className="w-3.5 h-3.5" /> Add
                      </button>
                    </div>
                  </div>
                </div>
              )}

              {/* CLI Positional Arguments Section (e.g. allowed directories for filesystem MCP) */}
              {cliArgs.length > 0 && (
                <div className="space-y-3 pt-2">
                  <div className="flex items-center gap-2">
                    <Terminal className="w-4 h-4 text-amber-400" />
                    <span className="text-xs font-bold uppercase tracking-wider text-neutral-300">
                      CLI Arguments Required
                    </span>
                    <span className="text-[10px] px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-300 font-mono font-bold border border-amber-500/30">
                      {cliArgs.filter((a) => a.required).length} required
                    </span>
                  </div>
                  <div className="p-3.5 bg-amber-500/5 border border-amber-500/20 rounded-xl text-xs text-amber-200/80 flex items-start gap-2.5">
                    <Info className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
                    <div>
                      This MCP server requires <span className="font-semibold text-amber-200">positional arguments</span> passed at startup (not environment variables). Fill in the values below — they will be included directly in the command line.
                    </div>
                  </div>
                  <div className="space-y-2.5">
                    {cliArgs.map((arg, idx) => (
                      <div key={arg.name} className="space-y-1">
                        <div className="flex items-center gap-2">
                          <label className="text-xs font-semibold text-neutral-300 font-mono">
                            {arg.name.replace(/_/g, " ")}
                          </label>
                          {arg.required && (
                            <span className="text-[10px] uppercase font-bold tracking-wider px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-400 border border-amber-500/30">
                              Required
                            </span>
                          )}
                        </div>
                        {arg.description && (
                          <p className="text-[11px] text-neutral-500">{arg.description}</p>
                        )}
                        <input
                          type="text"
                          value={arg.value || ""}
                          onChange={(e) => {
                            const val = e.target.value;
                            setCliArgs((prev) =>
                              prev.map((a, i) => (i === idx ? { ...a, value: val } : a))
                            );
                          }}
                          placeholder={arg.placeholder || arg.default || `Enter ${arg.name.replace(/_/g, " ")}`}
                          className="w-full bg-neutral-950 border border-amber-500/30 rounded-xl px-3.5 py-2.5 text-sm text-neutral-200 placeholder-neutral-600 focus:outline-none focus:border-amber-400 transition-colors font-mono"
                        />
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Tools Selection & Management Section */}
              <div className="space-y-3 pt-2">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Wrench className="w-4 h-4 text-violet-400" />
                    <span className="text-xs font-bold uppercase tracking-wider text-neutral-300">
                      Tools Selection (Optional)
                    </span>
                    {discoveredTools.length > 0 && (
                      <span className="text-[10px] px-2 py-0.5 rounded-full bg-violet-500/20 text-violet-300 font-mono font-bold border border-violet-500/30">
                        {selectedTools.size} / {discoveredTools.length} active
                      </span>
                    )}
                  </div>
                  <button
                    type="button"
                    onClick={handleDiscoverTools}
                    disabled={discoveringTools}
                    className="px-3 py-1.5 rounded-lg bg-neutral-800 hover:bg-neutral-700 text-neutral-300 hover:text-white text-xs font-medium transition cursor-pointer flex items-center gap-1.5 border border-neutral-700 disabled:opacity-50"
                  >
                    {discoveringTools ? (
                      <>
                        <Loader2 className="w-3.5 h-3.5 animate-spin text-violet-400" />
                        Testing &amp; Discovering...
                      </>
                    ) : (
                      <>
                        <Sparkles className="w-3.5 h-3.5 text-violet-400" />
                        {discoveredTools.length > 0 ? "Refresh Tools" : "Discover Tools"}
                      </>
                    )}
                  </button>
                </div>

                {toolDiscoveryError && (
                  <div className="p-3 rounded-xl bg-amber-500/10 border border-amber-500/20 text-amber-300 text-xs flex items-center gap-2">
                    <AlertCircle className="w-4 h-4 shrink-0 text-amber-400" />
                    <span>{toolDiscoveryError}</span>
                  </div>
                )}

                {discoveredTools.length > 0 && (
                  <div className="bg-neutral-950/70 border border-neutral-800 rounded-xl p-3.5 space-y-3">
                    <div className="flex items-center justify-between gap-2">
                      <div className="relative flex-1">
                        <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-neutral-500" />
                        <input
                          type="text"
                          value={toolSearchQuery}
                          onChange={(e) => setToolSearchQuery(e.target.value)}
                          placeholder="Filter tools by name..."
                          className="w-full pl-8 pr-2.5 py-1 bg-neutral-900 border border-neutral-800 rounded-lg text-xs text-neutral-200 placeholder-neutral-500 focus:outline-none focus:border-violet-500"
                        />
                      </div>
                      <div className="flex items-center gap-1.5 shrink-0">
                        <button
                          type="button"
                          onClick={handleSelectAllTools}
                          className="px-2 py-1 rounded bg-neutral-800 hover:bg-neutral-700 text-[11px] text-neutral-300 font-medium transition cursor-pointer"
                        >
                          All
                        </button>
                        <button
                          type="button"
                          onClick={handleDeselectAllTools}
                          className="px-2 py-1 rounded bg-neutral-800 hover:bg-neutral-700 text-[11px] text-neutral-400 font-medium transition cursor-pointer"
                        >
                          None
                        </button>
                      </div>
                    </div>

                    <div className="space-y-1.5 max-h-48 overflow-y-auto pr-1">
                      {discoveredTools
                        .filter((t) => {
                          if (!toolSearchQuery.trim()) return true;
                          const q = toolSearchQuery.toLowerCase();
                          return t.name.toLowerCase().includes(q) || (t.description && t.description.toLowerCase().includes(q));
                        })
                        .map((tool) => {
                          const isChecked = selectedTools.has(tool.name);
                          return (
                            <label
                              key={tool.name}
                              className={`flex items-start gap-2.5 p-2 rounded-lg border transition cursor-pointer text-xs select-none ${
                                isChecked
                                  ? "bg-violet-500/5 border-violet-500/30 text-neutral-200"
                                  : "bg-neutral-900/40 border-neutral-800/80 text-neutral-500 opacity-60 hover:opacity-90"
                              }`}
                            >
                              <input
                                type="checkbox"
                                checked={isChecked}
                                onChange={() => toggleSingleTool(tool.name)}
                                className="mt-0.5 rounded border-neutral-700 text-violet-600 focus:ring-violet-500 cursor-pointer"
                              />
                              <div className="min-w-0 flex-1">
                                <div className="font-mono font-bold text-neutral-200 truncate">
                                  {tool.name}
                                </div>
                                {tool.description && (
                                  <div className="text-[11px] text-neutral-400 line-clamp-1 mt-0.5">
                                    {tool.description}
                                  </div>
                                )}
                              </div>
                            </label>
                          );
                        })}
                    </div>
                  </div>
                )}
              </div>
            </>
          )}
        </form>

        {/* Footer */}
        <div className="p-4 border-t border-neutral-800 bg-neutral-950 flex items-center justify-end gap-3">
          <button
            type="button"
            onClick={onClose}
            disabled={installing}
            className="px-4 py-2 text-sm font-medium text-neutral-400 hover:text-neutral-200 hover:bg-neutral-800/80 rounded-xl transition-colors"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSubmit}
            disabled={installing || loadingSchema}
            className="px-5 py-2.5 text-sm font-medium text-white bg-violet-600 hover:bg-violet-500 disabled:opacity-50 rounded-xl shadow-lg shadow-violet-600/20 flex items-center gap-2 transition-all"
          >
            {installing ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                Configuring...
              </>
            ) : (
              <>
                <CheckCircle2 className="w-4 h-4" />
                Install MCP Server
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
