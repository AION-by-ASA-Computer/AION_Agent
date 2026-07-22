"use client";

import { useState, useEffect, useMemo, useCallback } from "react";
import { apiFetch } from "@/lib/api/headers";
import { Search, Download, ShieldCheck, AlertCircle, Globe, Terminal, Box, X, Trash2, AlertTriangle, Users, MessageSquare, Wand2, GitBranch, Loader2, ExternalLink } from "lucide-react";
import { apiBase } from "@/lib/api";
import { PageToast, ToastState } from "@/components/PageToast";
import { buildCredentialFields, extraEnvJson, matchConnectorRow } from "@/lib/mcpConnectorUi";
import {
  CredentialMode,
  CredentialSchemaField,
  IntegrationPolicyRow,
  modeLabel,
  normalizeCredentialSchema,
  policyBadges,
} from "@/lib/mcpIntegrationPolicy";
import { McpInstallWizard } from "@/components/McpInstallWizard";
import { CredentialSchemaEditor } from "@/components/CredentialSchemaEditor";

function chatUiAdvisorUrl(serverSlug: string): string {
  if (typeof window === "undefined") return "/";
  const host = window.location.hostname;
  const port = window.location.port;
  const base =
    port === "3870" || port === ""
      ? `${window.location.protocol}//${host}:8003`
      : window.location.origin;
  return `${base}/?profile=mcp_integration_advisor&context=${encodeURIComponent(serverSlug)}`;
}

export default function MCPHub() {
  const [searchQuery, setSearchQuery] = useState("");
  const [marketItems, setMarketItems] = useState<any[]>([]);
  const [installedItems, setInstalledItems] = useState<any>({});
  const [loading, setLoading] = useState(false);
  const [installingId, setInstallingId] = useState<string | null>(null);
  const [githubInstallOpen, setGithubInstallOpen] = useState(false);
  const [githubUrl, setGithubUrl] = useState("");
  const [githubDisplayName, setGithubDisplayName] = useState("");

  const [remoteInstallOpen, setRemoteInstallOpen] = useState(false);
  const [remoteUrl, setRemoteUrl] = useState("");
  const [remoteDisplayName, setRemoteDisplayName] = useState("");
  const [remoteClientId, setRemoteClientId] = useState("");
  const [remoteClientSecret, setRemoteClientSecret] = useState("");

  const [activeTab, setActiveTab] = useState<"marketplace" | "installed">("installed");
  const [mcpFilter, setMcpFilter] = useState("all");

  const handleTabChange = useCallback((tab: "installed" | "marketplace") => {
    setActiveTab(tab);
    setMcpFilter("all");
  }, []);

  const [editingConfig, setEditingConfig] = useState<any>(null);
  const [toast, setToast] = useState<ToastState>(null);

  const [isDeleteModalOpen, setIsDeleteModalOpen] = useState(false);
  const [mcpToDelete, setMcpToDelete] = useState<string | null>(null);

  const [isBlockedModalOpen, setIsBlockedModalOpen] = useState(false);
  const [blockingProfiles, setBlockingProfiles] = useState<string[]>([]);

  const [sandboxBackend, setSandboxBackend] = useState<string>("subprocess");

  const [connectorRows, setConnectorRows] = useState<any[]>([]);

  const [integrationBySlug, setIntegrationBySlug] = useState<Record<string, IntegrationPolicyRow>>({});
  const [editingPolicy, setEditingPolicy] = useState<{
    enabled: boolean;
    mode: CredentialMode;
    warnings: string[];
    previewSchema: CredentialSchemaField[];
    credentialSchema: CredentialSchemaField[];
  } | null>(null);
  const [adviseOpen, setAdviseOpen] = useState(false);
  const [adviseLoading, setAdviseLoading] = useState(false);
  const [adviseResult, setAdviseResult] = useState<{ steps_markdown?: string; warnings?: string[] } | null>(null);
  const [wizardTarget, setWizardTarget] = useState<
    | { kind: "market"; marketItemId: string; title: string }
    | { kind: "server"; serverSlug: string; title: string }
    | null
  >(null);
  const [userMayDisable, setUserMayDisable] = useState(true);
  const [oauthConfig, setOauthConfig] = useState<{
    provider: string;
    authorization_server: string;
    token_url: string;
    client_id: string;
    client_secret: string;
    scopes: string[];
  }>({
    provider: "generic",
    authorization_server: "",
    token_url: "",
    client_id: "",
    client_secret: "",
    scopes: [],
  });

  const fetchIntegrations = useCallback(async () => {
    try {
      const res = await apiFetch(`${apiBase()}/admin/mcp-integrations`);
      if (!res.ok) return;
      const data = await res.json();
      const map: Record<string, IntegrationPolicyRow> = {};
      for (const row of (data.integrations || []) as IntegrationPolicyRow[]) {
        map[row.server_slug] = row;
      }
      setIntegrationBySlug(map);
    } catch (e) {
      console.error(e);
    }
  }, []);

  const loadPolicyPreview = useCallback(async (slug: string, mode?: CredentialMode) => {
    try {
      const q = mode ? `?credential_mode=${encodeURIComponent(mode)}` : "";
      const res = await apiFetch(`${apiBase()}/admin/mcp-integrations/${encodeURIComponent(slug)}/preview${q}`);
      if (!res.ok) return;
      const data = await res.json();
      const preview = normalizeCredentialSchema(data.credential_schema);
      setEditingPolicy((prev) => ({
        enabled: prev?.enabled ?? integrationBySlug[slug]?.is_enabled_for_users ?? false,
        mode: (data.credential_mode as CredentialMode) || mode || prev?.mode || "none",
        warnings: data.warnings || [],
        previewSchema: preview,
        credentialSchema:
          prev?.credentialSchema && prev.credentialSchema.length > 0 ? prev.credentialSchema : preview,
      }));

      if (data.discovery && data.discovery.remote_auth_type === "oauth2") {
        setOauthConfig((prev) => {
          if (prev.authorization_server && prev.client_id) {
            return prev;
          }
          return {
            provider: prev.provider || data.discovery.remote_oauth_provider || "generic",
            authorization_server: prev.authorization_server || data.discovery.remote_oauth_server || "",
            token_url: prev.token_url || data.discovery.remote_oauth_token_url || "",
            client_id: prev.client_id || "",
            client_secret: prev.client_secret || "",
            scopes: prev.scopes && prev.scopes.length > 0 ? prev.scopes : [],
          };
        });
      }
    } catch (e) {
      console.error(e);
    }
  }, [integrationBySlug]);

  useEffect(() => {
    fetchRegistry();
    fetchSettings();
    void fetchIntegrations();
  }, [fetchIntegrations]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const focus = new URLSearchParams(window.location.search).get("focus");
    if (focus === "integrations") setActiveTab("installed");
  }, []);

  const fetchSettings = async () => {
    try {
      const res = await apiFetch(`${apiBase()}/admin/settings`);
      if (res.ok) {
        const data = await res.json();
        const backend = (data.settings?.AION_SANDBOX_BACKEND || "subprocess").trim().toLowerCase();
        setSandboxBackend(backend === "container" ? "container" : "subprocess");
      }
    } catch (e) {
      console.error("Failed to fetch settings", e);
    }
  };

  const fetchRegistry = async () => {
    try {
      const res = await apiFetch(`${apiBase()}/admin/registry`);
      if (!res.ok) throw new Error("Error retrieving registry");
      const data = await res.json();
      setInstalledItems(data);
    } catch (e: any) {
      console.error(e);
    }
  };

  const ensureConnectorCatalog = async () => {
    if (connectorRows.length > 0) return;
    try {
      const res = await apiFetch(`${apiBase()}/admin/mcp/connector-catalog`);
      if (!res.ok) return;
      const data = await res.json();
      setConnectorRows(Array.isArray(data.connectors) ? data.connectors : []);
    } catch (e) {
      console.error(e);
    }
  };

  const runMarketSearch = async (qRaw: string) => {
    const q = qRaw.trim();
    if (!q) return;
    setLoading(true);
    try {
      const res = await apiFetch(`${apiBase()}/admin/market/search?q=${encodeURIComponent(q)}`);
      if (!res.ok) throw new Error("Search failed");
      const data = await res.json();
      setMarketItems(data.filter((item: any) => item.source !== "Official Registry"));
      if (data.length === 0) {
        setToast({ message: "No results found in the Marketplace.", variant: "error" });
      }
    } catch (e: any) {
      setToast({ message: "Error during search: " + e.message, variant: "error" });
    } finally {
      setLoading(false);
    }
  };

  const handleSearch = async () => {
    if (!searchQuery) return;
    await runMarketSearch(searchQuery);
  };

  const openEditConfig = async (name: string, config: Record<string, unknown>) => {
    void ensureConnectorCatalog();
    // Do not sync from registry: the schema may have been configured manually
    // or via AI wizard. Use sync-from-registry only explicitly from a dedicated button.
    await fetchIntegrations();
    const policy = integrationBySlug[name];
    setUserMayDisable(policy?.user_may_disable !== false);
    setEditingConfig({
      name,
      values: {
        ...config,
        env: config.env && typeof config.env === "object" && !Array.isArray(config.env) ? { ...(config.env as object) } : {},
      },
    });
    const schema = normalizeCredentialSchema(policy?.credential_schema);
    setEditingPolicy({
      enabled: policy?.is_enabled_for_users ?? false,
      mode: policy?.credential_mode ?? "none",
      warnings: [],
      previewSchema: schema,
      credentialSchema: schema,
    });

    const oauth = policy?.oauth_config || {};
    setOauthConfig({
      provider: oauth.provider || "generic",
      authorization_server: oauth.authorization_server || "",
      token_url: oauth.token_url || "",
      client_id: oauth.client_id || "",
      client_secret: oauth.client_secret || "",
      scopes: oauth.scopes || [],
    });

    void loadPolicyPreview(name, policy?.credential_mode);
  };

  const saveIntegrationPolicy = async (slug: string) => {
    if (!editingPolicy) return;
    const existing = integrationBySlug[slug];
    const body: Record<string, unknown> = {
      is_enabled_for_users: editingPolicy.enabled,
      credential_mode: editingPolicy.mode,
      requires_user_credentials: editingPolicy.mode === "per_user",
      user_may_disable: userMayDisable,
    };
    if (editingPolicy.mode === "per_user") {
      body.credential_schema = editingPolicy.credentialSchema;
      body.schema_override = editingPolicy.credentialSchema.length > 0;
      if (body.schema_override) {
        body.apply_suggested_env = true;
      }
    }

    if (oauthConfig.authorization_server || oauthConfig.client_id) {
      body.oauth_config = {
        provider: oauthConfig.provider || "generic",
        authorization_server: oauthConfig.authorization_server,
        token_url: oauthConfig.token_url,
        client_id: oauthConfig.client_id,
        client_secret: oauthConfig.client_secret,
        scopes: oauthConfig.scopes || [],
      };
    } else {
      body.oauth_config = {};
    }
    if (existing) {
      const res = await apiFetch(`${apiBase()}/admin/mcp-integrations/${encodeURIComponent(slug)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error(await res.text());
    } else {
      const res = await apiFetch(`${apiBase()}/admin/mcp-integrations`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          server_slug: slug,
          display_name: slug.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()),
          ...body,
        }),
      });
      if (!res.ok) throw new Error(await res.text());
    }
  };

  const applySuggestedEnv = async () => {
    if (!editingConfig || !editingPolicy) return;
    if (editingPolicy.mode !== "per_user" && editingPolicy.mode !== "org_shared") return;
    setLoading(true);
    try {
      const res = await apiFetch(
        `${apiBase()}/admin/mcp-integrations/${encodeURIComponent(editingConfig.name)}/apply-suggested-env?credential_mode=${editingPolicy.mode}`,
        { method: "POST" },
      );
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      setEditingConfig({
        ...editingConfig,
        values: { ...editingConfig.values, env: data.env || editingConfig.values.env },
      });
      setToast({ message: "Suggested env applied to local registry.", variant: "success" });
      void loadPolicyPreview(editingConfig.name, editingPolicy.mode);
      fetchRegistry();
    } catch (e: unknown) {
      setToast({ message: "Suggested env error: " + (e instanceof Error ? e.message : String(e)), variant: "error" });
    } finally {
      setLoading(false);
    }
  };

  const runAdvise = async () => {
    if (!editingConfig) return;
    setAdviseLoading(true);
    setAdviseOpen(true);
    try {
      const res = await apiFetch(`${apiBase()}/admin/mcp-integrations/advise`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ server_slug: editingConfig.name }),
      });
      if (!res.ok) throw new Error(await res.text());
      setAdviseResult(await res.json());
    } catch (e: unknown) {
      setAdviseResult({ steps_markdown: e instanceof Error ? e.message : "Advisory error" });
    } finally {
      setAdviseLoading(false);
    }
  };

  const handleSaveConfig = async () => {
    if (!editingConfig) return;
    setLoading(true);
    try {
      const v = editingConfig.values;
      const payload: Record<string, unknown> = {
        command: typeof v.command === "string" ? v.command : "python",
        args: Array.isArray(v.args) ? v.args : [],
        env: v.env && typeof v.env === "object" && !Array.isArray(v.env) ? { ...v.env } : {},
        description: typeof v.description === "string" ? v.description : "",
      };
      if (typeof v.type === "string") {
        payload.type = v.type;
      }
      if (typeof v.url === "string") {
        payload.url = v.url;
      }
      if (v.security && typeof v.security === "object" && !Array.isArray(v.security)) {
        payload.security = { ...v.security };
      }
      if (typeof v.aion_connector_id === "string" && v.aion_connector_id.trim()) {
        payload.aion_connector_id = v.aion_connector_id.trim();
      }
      if (v.type === "sse" || v.type === "remote-bridge") {
        payload.oauth = {
          client_id: oauthConfig.client_id || undefined,
          client_secret: oauthConfig.client_secret || undefined,
        };
      }
      const res = await apiFetch(`${apiBase()}/admin/mcp/${editingConfig.name}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error("Update failed");
      if (editingPolicy) {
        await saveIntegrationPolicy(editingConfig.name);
        await fetchIntegrations();
      }
      fetchRegistry();
      setEditingConfig(null);
      setEditingPolicy(null);
      setAdviseOpen(false);
      setAdviseResult(null);
      setToast({ message: "Configuration and user policies updated!", variant: "success" });
    } catch (e: any) {
      setToast({ message: "Error during update: " + e.message, variant: "error" });
    } finally {
      setLoading(false);
    }
  };

  const initiateDelete = async (name: string) => {
    setLoading(true);
    try {
      const res = await apiFetch(`${apiBase()}/admin/profiles`);
      if (!res.ok) throw new Error("Error loading profiles");
      const profiles = await res.json();

      const referencingProfiles = profiles
        .filter((p: any) => p.mcp_servers?.includes(name))
        .map((p: any) => p.name);

      if (referencingProfiles.length > 0) {
        setMcpToDelete(name);
        setBlockingProfiles(referencingProfiles);
        setIsBlockedModalOpen(true);
        return;
      }

      setMcpToDelete(name);
      setIsDeleteModalOpen(true);
    } catch (e: any) {
      setToast({ message: "Error during profile check: " + e.message, variant: "error" });
    } finally {
      setLoading(false);
    }
  };

  const confirmDelete = async () => {
    if (!mcpToDelete) return;
    setLoading(true);
    try {
      const res = await apiFetch(`${apiBase()}/admin/mcp/${mcpToDelete}`, { method: "DELETE" });
      if (!res.ok) throw new Error("Deletion failed");
      fetchRegistry();
      setToast({ message: `MCP '${mcpToDelete}' removed successfully!`, variant: "success" });
      setIsDeleteModalOpen(false);
      setMcpToDelete(null);
    } catch (e: any) {
      setToast({ message: "Error during removal: " + e.message, variant: "error" });
    } finally {
      setLoading(false);
    }
  };

  const probeMcp = async (name: string) => {
    setLoading(true);
    try {
      const res = await apiFetch(`${apiBase()}/admin/mcp/${encodeURIComponent(name)}/probe`, {
        method: "POST",
      });
      const data = await res.json();
      if (!res.ok || !data.ok) {
        throw new Error(data.error || `Probe failed (${res.status})`);
      }
      const names = (data.tools || []).map((t: { name?: string }) => t.name).filter(Boolean);
      setToast({
        message: `Probe OK: ${data.tool_count ?? names.length} tools — ${names.slice(0, 8).join(", ") || "no names"}`,
        variant: "success",
      });
    } catch (e: unknown) {
      setToast({ message: "MCP Probe: " + (e instanceof Error ? e.message : String(e)), variant: "error" });
    } finally {
      setLoading(false);
    }
  };

  const handleInstallGithub = async () => {
    const url = githubUrl.trim();
    if (!url) {
      setToast({ message: "Enter a valid GitHub URL.", variant: "error" });
      return;
    }
    setInstallingId("github:manual");
    setLoading(true);
    try {
      const res = await apiFetch(`${apiBase()}/admin/market/install-github`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          url,
          display_name: githubDisplayName.trim() || undefined,
        }),
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
      setToast({
        message: `Repository installed as '${data.name}'. Open the wizard to configure credentials and env.`,
        variant: "success",
      });
      setGithubInstallOpen(false);
      setGithubUrl("");
      setGithubDisplayName("");
      fetchRegistry();
      setActiveTab("installed");
    } catch (e: unknown) {
      setToast({
        message: "GitHub Installation: " + (e instanceof Error ? e.message : String(e)),
        variant: "error",
      });
    } finally {
      setInstallingId(null);
      setLoading(false);
    }
  };

  const handleInstallRemote = async () => {
    const url = remoteUrl.trim();
    if (!url) {
      setToast({ message: "Enter a valid remote URL.", variant: "error" });
      return;
    }
    setInstallingId("remote:manual");
    setLoading(true);
    try {
      const res = await apiFetch(`${apiBase()}/admin/market/install-remote`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          url,
          display_name: remoteDisplayName.trim() || undefined,
          client_id: remoteClientId.trim() || undefined,
          client_secret: remoteClientSecret.trim() || undefined,
        }),
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
      setToast({
        message: `Remote MCP installed as '${data.name}'.`,
        variant: "success",
      });
      setRemoteInstallOpen(false);
      setRemoteUrl("");
      setRemoteDisplayName("");
      setRemoteClientId("");
      setRemoteClientSecret("");
      fetchRegistry();
      setActiveTab("installed");
    } catch (e: unknown) {
      setToast({
        message: "Remote Installation failed: " + (e instanceof Error ? e.message : String(e)),
        variant: "error",
      });
    } finally {
      setInstallingId(null);
      setLoading(false);
    }
  };

  const handleInstall = async (itemId: string) => {
    setInstallingId(itemId);
    try {
      const res = await apiFetch(`${apiBase()}/admin/market/install?item_id=${encodeURIComponent(itemId)}`, {
        method: "POST",
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
        console.error("[MCP Hub] install failed", itemId, detail);
        throw new Error(detail);
      }
      const data = await res.json();
      setToast({
        message: `Installation of '${data.name}' completed. Go to Installed → Edit configuration: fill in the credential fields (without JSON) or the catalog has already associated the connector type.`,
        variant: "success",
      });
      fetchRegistry();
      setActiveTab("installed");
    } catch (e: any) {
      setToast({ message: "Error during installation: " + (e?.message || String(e)), variant: "error" });
    } finally {
      setInstallingId(null);
    }
  };

  const displayedMarketItems = useMemo(() => {
    if (mcpFilter === "all") return marketItems.filter((item) => item.source !== "Official Registry");
    return marketItems.filter((item) => item.source !== "Official Registry" && item.source === mcpFilter);
  }, [marketItems, mcpFilter]);

  const filteredInstalledItems = Object.entries(installedItems).filter(([name, config]: [string, any]) => {
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      const match = name.toLowerCase().includes(q) || (config.description && config.description.toLowerCase().includes(q));
      if (!match) return false;
    }
    if (mcpFilter !== "all") {
      if (mcpFilter === "built_in") return !!config.is_base;
      if (mcpFilter === "stdio") return !config.is_base && (config.type === "stdio" || !config.type);
      if (mcpFilter === "sse") return config.type === "sse";
      if (mcpFilter === "remote-bridge") return config.type === "remote-bridge";
      if (mcpFilter === "in_process") return config.type === "in_process";
    }
    return true;
  });

  const connectorFormContext = useMemo(() => {
    if (!editingConfig) {
      return { matched: null as Record<string, unknown> | null, fields: [] as ReturnType<typeof buildCredentialFields>, knownKeys: new Set<string>() };
    }
    const matched = matchConnectorRow(
      editingConfig.name,
      editingConfig.values?.aion_connector_id as string | undefined,
      connectorRows as Record<string, unknown>[],
    );
    const fields = buildCredentialFields(matched);
    const knownKeys = new Set(fields.map((f) => f.key));
    return { matched, fields, knownKeys };
  }, [editingConfig, connectorRows]);

  return (
    <div className="space-y-8 pb-20">
      {/* Header */}
      <header className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 p-6">
        <div className="space-y-1">
          <h2 className="text-3xl font-extrabold tracking-tight text-white">MCP Hub</h2>
          <p className="text-md text-gray-400 max-w-xl mt-2">
            Discover and install modular capabilities from various marketplaces.
          </p>
        </div>
        {sandboxBackend === "container" && (
          <div className="flex items-center gap-3 px-4 py-2 bg-indigo-500/10 border border-indigo-500/20 rounded-2xl animate-in fade-in zoom-in duration-500 shadow-lg shadow-indigo-500/5">
            <div className="w-2 h-2 bg-indigo-500 rounded-full animate-pulse shadow-[0_0_8px_#6366f1]" />
            <div className="flex flex-col">
              <span className="text-[10px] font-black text-indigo-400 uppercase tracking-widest leading-none">Sandbox Mode</span>
              <span className="text-xs font-bold text-white mt-0.5 flex items-center gap-1.5">
                <Terminal className="w-3 h-3" />
                Container isolation (Podman)
              </span>
            </div>
          </div>
        )}
      </header>
      {/* Tabs */}
      <div className="flex border-b border-white/10 px-6 gap-8">
        <button
          onClick={() => handleTabChange("installed")}
          className={`py-4 text-sm font-bold relative transition-colors flex items-center gap-2 cursor-pointer ${activeTab === "installed" ? "text-blue-400" : "text-gray-500 hover:text-gray-300"
            }`}
        >
          Installed Modules
          <span className="px-2 py-0.5 text-[10px] bg-white/10 rounded-full text-gray-300 font-mono">
            {Object.keys(installedItems).length}
          </span>
          {activeTab === "installed" && (
            <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-blue-500 shadow-[0_0_8px_#3b82f6]" />
          )}
        </button>
        <button
          onClick={() => handleTabChange("marketplace")}
          className={`py-4 text-sm font-bold relative transition-colors cursor-pointer ${activeTab === "marketplace" ? "text-blue-400" : "text-gray-500 hover:text-gray-300"
            }`}
        >
          Marketplace Discover
          {activeTab === "marketplace" && (
            <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-blue-500 shadow-[0_0_8px_#3b82f6]" />
          )}
        </button>
      </div>


      {/* Search Bar */}
      <div className="flex flex-col sm:flex-row gap-4 px-6">
        <div className="relative flex-1 group">
          <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500 group-focus-within:text-blue-400 transition-colors" />
          <input
            type="text"
            placeholder={
              activeTab === "marketplace"
                ? "Search Marketplace (Claude, OpenClaw, Custom...)"
                : "Filter installed MCP servers by name or description..."
            }
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && activeTab === "marketplace" && handleSearch()}
            className="w-full bg-black/40 backdrop-blur-sm border border-white/10 rounded-xl pl-10 pr-10 py-3.5 text-sm text-white placeholder:text-gray-600 focus:border-blue-500/80 focus:ring-4 focus:ring-blue-500/10 outline-none transition-all shadow-inner"
          />
          {searchQuery && (
            <button
              onClick={() => setSearchQuery("")}
              className="absolute right-3.5 top-1/2 -translate-y-1/2 text-gray-500 hover:text-white transition-colors p-1"
            >
              <X className="w-4 h-4" />
            </button>
          )}
        </div>

        <div className="relative min-w-[200px]">
          <select
            value={mcpFilter}
            onChange={(e) => setMcpFilter(e.target.value)}
            className="w-full bg-black/40 backdrop-blur-sm border border-white/10 rounded-xl px-4 py-3.5 text-sm text-white focus:border-blue-500/80 focus:ring-4 focus:ring-blue-500/10 outline-none transition-all cursor-pointer appearance-none pr-10 font-medium"
            style={{
              backgroundImage: `url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='24' height='24' viewBox='0 0 24 24' fill='none' stroke='%239ca3af' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><polyline points='6 9 12 15 18 9'></polyline></svg>")`,
              backgroundRepeat: "no-repeat",
              backgroundPosition: "right 12px center",
              backgroundSize: "16px"
            }}
          >
            {activeTab === "marketplace" ? (
              <>
                <option value="all" className="bg-[#1a1a1a] text-white">All Sources (All Sources)</option>
                <option value="Glama.ai" className="bg-[#1a1a1a] text-white">Glama.ai</option>
                <option value="Google Cloud" className="bg-[#1a1a1a] text-white">Google Cloud</option>
                <option value="Claude Community" className="bg-[#1a1a1a] text-white">Claude Community</option>
                <option value="GitHub" className="bg-[#1a1a1a] text-white">GitHub Topic</option>
                <option value="Awesome List" className="bg-[#1a1a1a] text-white">Awesome List</option>
              </>
            ) : (
              <>
                <option value="all" className="bg-[#1a1a1a] text-white">All Types (All Types)</option>
                <option value="built_in" className="bg-[#1a1a1a] text-white">Built-in (System)</option>
                <option value="stdio" className="bg-[#1a1a1a] text-white">Local (Stdio)</option>
                <option value="sse" className="bg-[#1a1a1a] text-white">Remote (SSE)</option>
                <option value="remote-bridge" className="bg-[#1a1a1a] text-white">Remote Bridge (mcp-remote)</option>
                <option value="in_process" className="bg-[#1a1a1a] text-white">In-Process</option>
              </>
            )}
          </select>
        </div>
        {activeTab === "marketplace" && (
          <>
            <button
              onClick={handleSearch}
              disabled={loading || !searchQuery.trim()}
              className="w-40 py-3.5 bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white rounded-xl font-bold text-sm shadow-lg shadow-blue-500/20 transition-all transform active:scale-95 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2 select-none"
            >
              {loading && !githubInstallOpen ? (
                <>
                  <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin shrink-0" />
                  <span>SEARCHING</span>
                </>
              ) : (
                <>
                  <Search className="w-4 h-4 shrink-0" />
                  <span>SEARCH</span>
                </>
              )}
            </button>
            <button
              type="button"
              onClick={() => setGithubInstallOpen(true)}
              disabled={loading || installingId !== null}
              className="px-5 py-3.5 bg-white/5 hover:bg-white/10 border border-white/15 text-white rounded-xl font-bold text-sm transition-all cursor-pointer disabled:opacity-50 flex items-center justify-center gap-2"
              title="Install from GitHub URL even if it doesn't appear in search results"
            >
              <GitBranch className="w-4 h-4" />
              FROM GITHUB
            </button>
            <button
              type="button"
              onClick={() => setRemoteInstallOpen(true)}
              disabled={loading || installingId !== null}
              className="px-5 py-3.5 bg-white/5 hover:bg-white/10 border border-white/15 text-white rounded-xl font-bold text-sm transition-all cursor-pointer disabled:opacity-50 flex items-center justify-center gap-2"
              title="Install from remote URL (HTTP/SSE/Streamable)"
            >
              <Globe className="w-4 h-4" />
              REMOTE
            </button>
          </>
        )}
      </div>

      {githubInstallOpen && (
        <div className="fixed inset-0 z-[65] bg-black/75 flex items-center justify-center p-4">
          <div className="bg-[#1a1a1a] border border-white/10 rounded-2xl max-w-lg w-full p-6 space-y-4 shadow-2xl">
            <div className="flex justify-between items-start gap-4">
              <div>
                <h3 className="text-lg font-bold text-white flex items-center gap-2">
                  <GitBranch className="w-5 h-5" />
                  Install from GitHub
                </h3>
                <p className="text-xs text-gray-400 mt-1">
                  Clone into <code className="text-emerald-300">mcp_servers/</code> even if the repo isn't in the marketplace.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setGithubInstallOpen(false)}
                className="text-gray-500 hover:text-white p-1 cursor-pointer"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            <label className="block text-xs font-bold text-gray-400 uppercase tracking-wider">
              Repository URL
              <input
                type="url"
                value={githubUrl}
                onChange={(e) => setGithubUrl(e.target.value)}
                placeholder="https://github.com/ai-zerolab/mcp-email-server"
                className="mt-1.5 w-full bg-black/40 border border-white/10 rounded-xl px-3 py-2.5 text-sm text-white placeholder:text-gray-600 focus:border-blue-500/80 outline-none"
              />
            </label>
            <label className="block text-xs font-bold text-gray-400 uppercase tracking-wider">
              Server name (optional)
              <input
                type="text"
                value={githubDisplayName}
                onChange={(e) => setGithubDisplayName(e.target.value)}
                placeholder="mcp-email-server"
                className="mt-1.5 w-full bg-black/40 border border-white/10 rounded-xl px-3 py-2.5 text-sm text-white placeholder:text-gray-600 focus:border-blue-500/80 outline-none"
              />
            </label>
            <div className="flex gap-3 justify-end pt-2">
              <button
                type="button"
                onClick={() => setGithubInstallOpen(false)}
                className="px-4 py-2 text-sm text-gray-400 hover:text-white cursor-pointer"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => void handleInstallGithub()}
                disabled={installingId !== null || !githubUrl.trim()}
                className="px-5 py-2.5 bg-blue-600 hover:bg-blue-500 text-white rounded-xl text-sm font-bold disabled:opacity-50 cursor-pointer flex items-center gap-2"
              >
                {installingId === "github:manual" ? (
                  <>Installing…</>
                ) : (
                  <>
                    <Download className="w-4 h-4" /> Install
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}
      {remoteInstallOpen && (
        <div className="fixed inset-0 z-[65] bg-black/75 flex items-center justify-center p-4">
          <div className="bg-[#1a1a1a] border border-white/10 rounded-2xl max-w-lg w-full p-6 space-y-4 shadow-2xl">
            <div className="flex justify-between items-start gap-4">
              <div>
                <h3 className="text-lg font-bold text-white flex items-center gap-2">
                  <Globe className="w-5 h-5 text-indigo-400" />
                  Install from Remote URL
                </h3>
              </div>
              <button
                type="button"
                onClick={() => {
                  setRemoteInstallOpen(false);
                  setRemoteUrl("");
                  setRemoteDisplayName("");
                  setRemoteClientId("");
                  setRemoteClientSecret("");
                }}
                className="text-gray-500 hover:text-white p-1 cursor-pointer"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            <label className="block text-xs font-bold text-gray-400 uppercase tracking-wider">
              Remote Endpoint URL
              <input
                type="url"
                value={remoteUrl}
                onChange={(e) => setRemoteUrl(e.target.value)}
                placeholder="https://...../mcp"
                className="mt-1.5 w-full bg-black/40 border border-white/10 rounded-xl px-3 py-2.5 text-sm text-white placeholder:text-gray-600 focus:border-blue-500/80 outline-none"
              />
            </label>
            <label className="block text-xs font-bold text-gray-400 uppercase tracking-wider">
              Display name (optional)
              <input
                type="text"
                value={remoteDisplayName}
                onChange={(e) => setRemoteDisplayName(e.target.value)}
                placeholder="..."
                className="mt-1.5 w-full bg-black/40 border border-white/10 rounded-xl px-3 py-2.5 text-sm text-white placeholder:text-gray-600 focus:border-blue-500/80 outline-none"
              />
            </label>
            <div className="grid grid-cols-2 gap-4">
              <label className="block text-xs font-bold text-gray-400 uppercase tracking-wider">
                OAuth Client ID (optional)
                <input
                  type="text"
                  value={remoteClientId}
                  onChange={(e) => setRemoteClientId(e.target.value)}
                  placeholder="e.g. client-id"
                  className="mt-1.5 w-full bg-black/40 border border-white/10 rounded-xl px-3 py-2.5 text-sm text-white placeholder:text-gray-600 focus:border-blue-500/80 outline-none"
                />
              </label>
              <label className="block text-xs font-bold text-gray-400 uppercase tracking-wider">
                OAuth Client Secret (optional)
                <input
                  type="password"
                  value={remoteClientSecret}
                  onChange={(e) => setRemoteClientSecret(e.target.value)}
                  placeholder="e.g. client-secret"
                  className="mt-1.5 w-full bg-black/40 border border-white/10 rounded-xl px-3 py-2.5 text-sm text-white placeholder:text-gray-600 focus:border-blue-500/80 outline-none"
                />
              </label>
            </div>
            <div className="flex gap-3 justify-end pt-2">
              <button
                type="button"
                onClick={() => {
                  setRemoteInstallOpen(false);
                  setRemoteUrl("");
                  setRemoteDisplayName("");
                  setRemoteClientId("");
                  setRemoteClientSecret("");
                }}
                className="px-4 py-2 text-sm text-gray-400 hover:text-white cursor-pointer"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => void handleInstallRemote()}
                disabled={installingId !== null || !remoteUrl.trim()}
                className="px-5 py-2.5 bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl text-sm font-bold disabled:opacity-50 cursor-pointer flex items-center gap-2"
              >
                {installingId === "remote:manual" ? (
                  <>Installing…</>
                ) : (
                  <>
                    <Download className="w-4 h-4" /> Install
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}
      {/* Tab Content: Marketplace */}
      {activeTab === "marketplace" && (
        <div className="px-6 animate-in fade-in duration-200">
          {loading && !githubInstallOpen ? (
            <div className="flex flex-col items-center justify-center text-center py-20 bg-[#121212]/30 border border-white/5 rounded-3xl px-4 min-h-[300px]">
              <Loader2 className="w-10 h-10 text-blue-500 animate-spin mb-4" />
              <p className="text-sm font-semibold text-white">Searching the Marketplace...</p>
              <p className="text-xs text-gray-500 mt-1 max-w-xs leading-relaxed">We are querying the configured registries and MCP sources.</p>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              {displayedMarketItems.map((item) => {
                const isInstallingThis = installingId === item.id;
                return (
                  <div key={item.id} className="glass-card flex flex-col bg-[#121212]/80 border border-white/5 hover:border-blue-500/50 rounded-2xl backdrop-blur-sm transition-all duration-200 shadow-xl group">
                    <div className="p-6 flex-1 space-y-4">
                      <div className="flex items-start justify-between">
                        <div className="p-3 bg-blue-500/10 border border-blue-500/20 rounded-xl group-hover:bg-blue-500/20 transition-colors">
                          <Globe className="w-6 h-6 text-blue-400" />
                        </div>
                        <div className="text-[10px] font-bold uppercase tracking-widest text-gray-400 bg-white/5 border border-white/10 px-2.5 py-1 rounded-lg font-mono">
                          {item.source}
                        </div>
                      </div>
                      <div>
                        <a
                          href={item.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="group/link flex items-center gap-2 text-white hover:text-blue-400 transition-colors"
                        >
                          <h3 className="text-xl font-bold truncate">{item.name}</h3>
                          <ExternalLink className="w-4 h-4 opacity-0 group-hover/link:opacity-100 transition-opacity shrink-0" />
                        </a>
                        <p className="text-sm text-gray-400 mt-1 line-clamp-2">{item.description || "Experimental MCP Server from the community."}</p>
                      </div>
                    </div>
                    <div className="p-4 border-t border-white/5 bg-black/20 flex items-center justify-between rounded-b-2xl">
                      <div className="flex items-center gap-2 text-[10px] font-bold text-gray-500 uppercase font-mono">
                        {item.install_type === "remote" ? (
                          <>
                            <Globe className="w-3 h-3 text-blue-400" /> Remote
                          </>
                        ) : item.install_type === "binary" ? (
                          <>
                            <Box className="w-3 h-3 text-emerald-400" /> Binary
                          </>
                        ) : item.install_type === "git" ? (
                          <>
                            <GitBranch className="w-3 h-3 text-purple-400" /> Git
                          </>
                        ) : (
                          <>
                            <Terminal className="w-3 h-3 text-gray-400" /> Stdio
                          </>
                        )}
                      </div>
                      <div className="flex items-center gap-2">
                        {item.install_type !== "remote" && (
                          <button
                            type="button"
                            onClick={() =>
                              setWizardTarget({
                                kind: "market",
                                marketItemId: item.id,
                                title: item.name || item.id,
                              })
                            }
                            disabled={installingId !== null || loading}
                            className="flex items-center gap-1.5 text-xs font-bold text-indigo-300 bg-indigo-500/10 border border-indigo-500/20 px-3 py-2 rounded-xl hover:bg-indigo-500/20 disabled:opacity-50 cursor-pointer"
                          >
                            <Wand2 className="w-3.5 h-3.5" /> WIZARD
                          </button>
                        )}
                        <button
                          onClick={() => handleInstall(item.id)}
                          disabled={installingId !== null || loading}
                          className="flex items-center gap-2 text-xs font-bold text-blue-400 bg-blue-500/10 border border-blue-500/20 px-4 py-2 rounded-xl hover:bg-blue-500/20 hover:border-blue-500/40 transition-all disabled:opacity-50 cursor-pointer shadow-lg shadow-blue-500/5"
                        >
                          <Download className="w-3.5 h-3.5" /> {isInstallingThis ? "INSTALLING..." : "INSTALL"}
                        </button>
                      </div>
                    </div>
                  </div>
                );
              })}

              {displayedMarketItems.length === 0 && (
                <div className="col-span-full py-20 flex flex-col items-center justify-center text-center bg-[#121212]/30 border border-white/5 rounded-3xl px-4">
                  <Box className="w-12 h-12 text-gray-600 mb-3 animate-pulse" />
                  <p className="text-sm font-semibold text-gray-400">Enter a query to browse the Marketplace</p>
                  <p className="text-xs text-gray-600 mt-1 max-w-xs">Search for modular features and expand agent capabilities.</p>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Tab Content: Installed */}
      {activeTab === "installed" && (
        <section className="space-y-6 px-6 animate-in fade-in duration-200">
          <div className="flex items-center justify-between">
            <h2 className="text-xs font-bold uppercase tracking-wider text-gray-400 flex items-center gap-2">
              <div className="w-2 h-2 bg-green-500 rounded-full animate-pulse"></div>
              Currently Installed Modules ({filteredInstalledItems.length})
            </h2>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {filteredInstalledItems.map(([name, config]: [string, any]) => (
              <div key={name} className="glass-card bg-[#121212]/80 border border-white/5 hover:border-white/15 rounded-2xl backdrop-blur-sm transition-all duration-200 shadow-xl group flex flex-col justify-between">
                <div className="p-6">
                  <div className="flex items-start justify-between mb-3">
                    <div className="space-y-1 min-w-0 pr-2">
                      <h3 className="font-bold text-lg text-white truncate">{name}</h3>
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="w-1.5 h-1.5 bg-green-500 rounded-full animate-pulse"></span>
                        <span className="text-[10px] text-green-400 font-bold uppercase tracking-wide">Active</span>
                        {config.is_base && (
                          <span className="text-[10px] bg-blue-500/10 text-blue-400 border border-blue-500/20 px-2 py-0.5 rounded-md font-bold uppercase tracking-wider font-mono">
                            Built-in
                          </span>
                        )}
                        {config.type === "sse" && (
                          <span className="text-[10px] bg-cyan-500/10 text-cyan-400 border border-cyan-500/20 px-2 py-0.5 rounded-md font-bold uppercase tracking-wider font-mono">
                            Remote (SSE)
                          </span>
                        )}
                        {config.type === "remote-bridge" && (
                          <span className="text-[10px] bg-purple-500/10 text-purple-400 border border-purple-500/20 px-2 py-0.5 rounded-md font-bold uppercase tracking-wider font-mono">
                            🌐 Remote Bridge
                          </span>
                        )}
                        {config.type === "in_process" && (
                          <span className="text-[10px] bg-amber-500/10 text-amber-400 border border-amber-500/20 px-2 py-0.5 rounded-md font-bold uppercase tracking-wider font-mono">
                            In-Process
                          </span>
                        )}
                      </div>
                    </div>
                    <div className="p-2.5 bg-white/5 border border-white/10 rounded-xl text-gray-400 shrink-0">
                      {config.type === "sse" || config.type === "remote-bridge" ? (
                        <Globe className="w-5 h-5 text-blue-400" />
                      ) : (
                        <Box className="w-5 h-5 text-gray-300" />
                      )}
                    </div>
                  </div>
                  <p className="text-sm text-gray-400 line-clamp-2">{config.description || "No description available."}</p>
                  {policyBadges(integrationBySlug[name]).length > 0 && (
                    <div className="flex flex-wrap gap-1.5 mt-3">
                      {policyBadges(integrationBySlug[name]).map((b) => (
                        <span
                          key={b}
                          className="text-[9px] font-bold uppercase tracking-wide text-indigo-300 bg-indigo-500/10 border border-indigo-500/25 px-2 py-0.5 rounded-md"
                        >
                          {b}
                        </span>
                      ))}
                    </div>
                  )}
                  {!config.is_base && (
                    <p className="text-[10px] text-gray-500 leading-snug mt-3 mb-1">
                      Unified hub: credentials, chat policies, and env in the Edit configuration button.
                    </p>
                  )}
                </div>
                <div className="flex gap-3 border-t border-white/5 p-4 bg-black/20 rounded-b-2xl">
                  <button
                    onClick={() => void openEditConfig(name, config)}
                    className="flex-1 py-2.5 bg-white/10 hover:bg-white/15 border border-white/10 rounded-xl text-[11px] font-bold text-white transition-all shadow-md cursor-pointer text-center"
                  >
                    EDIT CONFIG
                  </button>
                  {config.type === "remote-bridge" && (
                    <div className="px-3 py-2.5 bg-blue-500/10 border border-blue-500/20 rounded-xl text-[10px] font-bold text-blue-300 flex items-center gap-1" title="OAuth authentication is handled by the end user via chat-ui">
                      <Users className="w-3.5 h-3.5 shrink-0" />
                      <span>OAuth user</span>
                    </div>
                  )}
                  {!config.is_base && (
                    <>
                      <button
                        type="button"
                        onClick={() => void probeMcp(name)}
                        disabled={loading}
                        className="px-3 py-2.5 bg-emerald-500/10 hover:bg-emerald-500/20 border border-emerald-500/20 rounded-xl text-[10px] font-bold text-emerald-300 transition-all cursor-pointer"
                        title="Probe list_tools"
                      >
                        PROBE
                      </button>
                      {config.type !== "sse" && config.type !== "remote-bridge" && (
                        <button
                          type="button"
                          onClick={() => setWizardTarget({ kind: "server", serverSlug: name, title: name })}
                          className="px-3 py-2.5 bg-indigo-500/10 hover:bg-indigo-500/20 border border-indigo-500/20 rounded-xl text-[11px] font-bold text-indigo-300 transition-all cursor-pointer"
                          title="Wizard guidato"
                        >
                          <Wand2 className="w-4 h-4" />
                        </button>
                      )}
                    </>
                  )}
                  {!config.is_base ? (
                    <button
                      onClick={() => initiateDelete(name)}
                      className="px-4 py-2.5 bg-red-500/10 hover:bg-red-500/20 border border-red-500/20 rounded-xl text-[11px] font-bold text-red-400 hover:text-red-300 transition-all cursor-pointer"
                    >
                      REMOVE
                    </button>
                  ) : (
                    <div className="px-4 py-2.5 bg-gray-500/10 border border-gray-500/20 rounded-xl text-[11px] font-bold text-gray-500 flex items-center justify-center cursor-not-allowed font-mono">
                      SYSTEM MCP
                    </div>
                  )}
                </div>
              </div>
            ))}

            {filteredInstalledItems.length === 0 && (
              <div className="col-span-full py-16 flex flex-col items-center justify-center text-center bg-[#121212]/30 border border-white/5 rounded-2xl px-4">
                <Box className="w-8 h-8 text-gray-600 mb-2" />
                <p className="text-sm font-semibold text-gray-400">No installed MCP found</p>
                <p className="text-xs text-gray-600 mt-1">No module matches the search criteria.</p>
              </div>
            )}
          </div>
        </section>
      )}

      {/* Config Modal */}
      {editingConfig && (
        <div className="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 flex items-center justify-center p-4 animate-in fade-in duration-200">
          <div className="glass-card bg-[#1a1a1a] border border-white/10 rounded-3xl w-full max-w-2xl max-h-[90vh] overflow-y-auto overflow-x-hidden p-8 space-y-6 shadow-2xl animate-in zoom-in-95 duration-200 relative">
            <div className="absolute top-0 right-0 w-64 h-64 bg-blue-500/5 rounded-full blur-3xl pointer-events-none" />

            <div className="flex justify-between items-center border-b border-white/10 pb-5">
              <div className="flex items-center gap-3">
                <div className="p-2.5 bg-blue-500/10 border border-blue-500/20 rounded-xl text-blue-400">
                  <Box className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="text-xl font-bold text-white font-mono">{editingConfig.name}</h3>
                  <p className="text-xs text-gray-400">MCP Configuration</p>
                </div>
              </div>
              <button onClick={() => setEditingConfig(null)} className="p-2 text-gray-500 hover:text-white hover:bg-white/5 rounded-xl transition-colors">
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="space-y-5">
              <div className="space-y-2">
                <label className="text-xs font-bold uppercase tracking-wider text-gray-400 block">Connector Type (Catalog)</label>
                <select
                  value={(editingConfig.values.aion_connector_id as string | undefined) ?? ""}
                  onChange={(e) =>
                    setEditingConfig({
                      ...editingConfig,
                      values: {
                        ...editingConfig.values,
                        aion_connector_id: e.target.value ? e.target.value : undefined,
                      },
                    })
                  }
                  className="w-full bg-black/40 border border-white/10 rounded-xl p-3.5 text-sm text-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 outline-none cursor-pointer"
                >
                  <option value="">— Auto-detect from name —</option>
                  {connectorRows.map((c: any) => (
                    <option key={c.id} value={c.id}>
                      {c.title || c.id}
                    </option>
                  ))}
                </select>
                {connectorFormContext.matched ? (
                  <p className="text-[11px] text-emerald-400/90">
                    Guided form: <span className="font-mono text-white">{String((connectorFormContext.matched as { id?: string }).id)}</span>
                  </p>
                ) : (
                  <p className="text-[11px] text-gray-500">No cataloged connector associated: use the JSON at the bottom or choose a type above.</p>
                )}
              </div>

              {editingPolicy && (
                <div className="space-y-4 rounded-2xl border border-indigo-500/25 bg-indigo-500/[0.08] p-4">
                  <div className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-wider text-indigo-300/90">
                    <Users className="w-3.5 h-3.5" />
                    User availability (chat)
                  </div>
                  {/* <label className="flex items-center gap-3 cursor-pointer">
                    <input type="checkbox" checked={editingPolicy.enabled} onChange={(e) => setEditingPolicy({ ...editingPolicy, enabled: e.target.checked })} className="rounded border-white/20" />
                    <span className="text-sm text-gray-200">Enable edit in chat-ui for users</span>
                  </label> */}
                  <div className="flex flex-wrap gap-3 text-sm text-gray-300">
                    {(["none", "org_shared", "per_user"] as CredentialMode[]).map((m) => (
                      <label key={m} className="flex items-center gap-1.5 cursor-pointer">
                        <input type="radio" name="credential_mode" checked={editingPolicy.mode === m} onChange={() => {
                          setEditingPolicy({ ...editingPolicy, mode: m });
                          if (editingConfig) void loadPolicyPreview(editingConfig.name, m);
                          // Quando "none" è selezionato, pulisci gli --header dagli args
                          if (m === "none" && editingConfig?.values?.args) {
                            const args = editingConfig.values.args;
                            const cleaned: string[] = [];
                            let skipNext = false;
                            for (const arg of args) {
                              if (skipNext) { skipNext = false; continue; }
                              if (arg === "--header") { skipNext = true; continue; }
                              cleaned.push(arg);
                            }
                            if (cleaned.length !== args.length) {
                              setEditingConfig({ ...editingConfig, values: { ...editingConfig.values, args: cleaned } });
                            }
                          }
                        }} />
                        {modeLabel(m)}
                      </label>
                    ))}
                  </div>
                  {editingPolicy.warnings.map((w) => (
                    <p key={w} className="text-[11px] text-amber-300 flex gap-1"><AlertTriangle className="w-3.5 h-3.5 shrink-0" />{w}</p>
                  ))}
                  {editingPolicy.mode === "per_user" && (
                    <>
                      <CredentialSchemaEditor
                        value={editingPolicy.credentialSchema}
                        onChange={(credentialSchema) =>
                          setEditingPolicy({ ...editingPolicy, credentialSchema })
                        }
                      />
                      {editingPolicy.previewSchema.length > 0 && (
                        <button
                          type="button"
                          onClick={() =>
                            setEditingPolicy({
                              ...editingPolicy,
                              credentialSchema: editingPolicy.previewSchema,
                            })
                          }
                          className="text-xs text-gray-400 underline hover:text-white"
                        >
                          Import fields from auto-preview ({editingPolicy.previewSchema.length})
                        </button>
                      )}
                      <button type="button" onClick={() => void applySuggestedEnv()} disabled={loading} className="text-xs font-bold text-indigo-300 underline">
                        Apply suggested env to registry
                      </button>

                      {/* OAuth info banner — OAuth authentication is delegated to the end user */}
                      <div className="flex items-start gap-3 rounded-xl border border-blue-500/20 bg-blue-500/[0.06] p-4 mt-3">
                        <Users className="w-4 h-4 text-blue-300 shrink-0 mt-0.5" />
                        <div>
                          <div className="text-[10px] font-bold uppercase tracking-wider text-blue-300 mb-1">
                            OAuth Authentication — user-managed
                          </div>
                          <p className="text-[11px] text-gray-400 leading-relaxed">
                            If this remote MCP server requires OAuth, authentication is performed by each end user via the <span className="font-semibold text-white">My Integrations</span> section in chat-ui. The admin does not need to authenticate: ensure the policy is set to <span className="font-mono text-indigo-300">per_user</span> and the server exposes standard discovery endpoints.
                          </p>
                        </div>
                      </div>
                    </>
                  )
                  }
                  <label className="flex items-center gap-2 text-sm text-gray-300 cursor-pointer">
                    <input type="checkbox" checked={userMayDisable} onChange={(e) => setUserMayDisable(e.target.checked)} />
                    User can disable this integration
                  </label>
                  <div className="flex gap-3">
                    {editingConfig?.values?.type !== "sse" && editingConfig?.values?.type !== "remote-bridge" && (
                      <button type="button" onClick={() => void runAdvise()} className="text-xs font-bold text-blue-300">Ask the assistant</button>
                    )}
                    <a href={editingConfig ? chatUiAdvisorUrl(editingConfig.name) : "#"} target="_blank" rel="noopener noreferrer" className="text-xs text-gray-400 hover:text-white">Open chat-ui</a>
                  </div>
                </div >
              )}

              {
                connectorFormContext.fields.length > 0 && editingPolicy?.mode === "org_shared" ? (
                  <div className="space-y-4 rounded-2xl border border-emerald-500/20 bg-emerald-500/[0.06] p-4">
                    <div className="text-[10px] font-bold uppercase tracking-wider text-emerald-300/90">Organization Credentials</div>
                    {connectorFormContext.fields.map((field) => (
                      <div key={field.key} className="space-y-1.5">
                        <label className="text-xs font-semibold text-gray-200 flex items-center gap-2">
                          {field.label}
                          <span className="text-[10px] font-mono text-gray-500">{field.key}</span>
                          {field.required ? <span className="text-red-400">*</span> : <span className="text-gray-600 text-[10px]">(opt.)</span>}
                        </label>
                        <input
                          type={field.secret ? "password" : "text"}
                          autoComplete="off"
                          value={String((editingConfig.values.env || {})[field.key] ?? "")}
                          onChange={(e) => {
                            const next = { ...(editingConfig.values.env || {}) };
                            next[field.key] = e.target.value;
                            setEditingConfig({ ...editingConfig, values: { ...editingConfig.values, env: next } });
                          }}
                          className="w-full bg-black/50 border border-white/10 rounded-xl p-3 text-sm text-white placeholder:text-gray-600 focus:border-emerald-500/70 outline-none"
                          placeholder={field.required ? "Required" : "Optional"}
                        />
                      </div>
                    ))}
                    {Array.isArray((connectorFormContext.matched as { integration_hints?: unknown[] })?.integration_hints) &&
                      ((connectorFormContext.matched as { integration_hints?: unknown[] }).integration_hints?.length ?? 0) > 0 ? (
                      <div className="pt-2 space-y-2 border-t border-white/10 mt-2">
                        <div className="text-[10px] font-bold uppercase tracking-wider text-gray-500">Same secret elsewhere</div>
                        {(connectorFormContext.matched as { integration_hints: { id?: string; label_it?: string; note_it?: string }[] }).integration_hints.map(
                          (h) => (
                            <div key={h.id || h.label_it} className="text-[11px] text-gray-400 leading-relaxed rounded-lg bg-black/30 p-2 border border-white/5">
                              <span className="font-bold text-gray-300">{h.label_it || h.id}</span>
                              {h.note_it ? <span className="block mt-1">{h.note_it}</span> : null}
                            </div>
                          ),
                        )}
                      </div>
                    ) : null}
                  </div>
                ) : null
              }

              <div className="space-y-2">
                <label className="text-xs font-bold uppercase tracking-wider text-gray-400 block">Connection Type</label>
                <select
                  value={editingConfig.values.type ?? "stdio"}
                  onChange={(e) =>
                    setEditingConfig({
                      ...editingConfig,
                      values: {
                        ...editingConfig.values,
                        type: e.target.value,
                        ...(e.target.value === "sse" ? { command: undefined, args: undefined } : {})
                      },
                    })
                  }
                  className="w-full bg-black/40 border border-white/10 rounded-xl p-3.5 text-sm text-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 outline-none cursor-pointer"
                >
                  <option value="stdio">Local (Stdio)</option>
                  <option value="sse">Remote (SSE)</option>
                  <option value="in_process">In-Process</option>
                </select>
              </div>

              {
                editingConfig.values.type === "sse" || editingConfig.values.type === "remote-bridge" ? (
                  <div className="space-y-4">
                    <div className="space-y-2">
                      <label className="text-xs font-bold uppercase tracking-wider text-gray-400 block">SSE Endpoint URL</label>
                      <input
                        type="text"
                        value={editingConfig.values.url ?? ""}
                        onChange={(e) =>
                          setEditingConfig({
                            ...editingConfig,
                            values: { ...editingConfig.values, url: e.target.value },
                          })
                        }
                        placeholder="https://example.com/sse"
                        className="w-full bg-black/40 border border-white/10 rounded-xl p-3.5 text-sm text-white placeholder:text-gray-600 focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 outline-none transition-all shadow-inner font-mono"
                      />
                    </div>
                    <div className="grid grid-cols-2 gap-4">
                      <div className="space-y-2">
                        <label className="text-xs font-bold uppercase tracking-wider text-gray-400 block">OAuth Client ID (Optional)</label>
                        <input
                          type="text"
                          value={oauthConfig.client_id ?? ""}
                          onChange={(e) =>
                            setOauthConfig({
                              ...oauthConfig,
                              client_id: e.target.value,
                            })
                          }
                          placeholder="e.g. client-id"
                          className="w-full bg-black/40 border border-white/10 rounded-xl p-3.5 text-sm text-white placeholder:text-gray-600 focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 outline-none transition-all shadow-inner"
                        />
                      </div>
                      <div className="space-y-2">
                        <label className="text-xs font-bold uppercase tracking-wider text-gray-400 block">OAuth Client Secret (Optional)</label>
                        <input
                          type="password"
                          value={oauthConfig.client_secret ?? ""}
                          onChange={(e) =>
                            setOauthConfig({
                              ...oauthConfig,
                              client_secret: e.target.value,
                            })
                          }
                          placeholder="e.g. client-secret"
                          className="w-full bg-black/40 border border-white/10 rounded-xl p-3.5 text-sm text-white placeholder:text-gray-600 focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 outline-none transition-all shadow-inner"
                        />
                      </div>
                    </div>
                  </div>
                ) : editingConfig.values.type !== "in_process" ? (
                  <>
                    <div className="space-y-2">
                      <label className="text-xs font-bold uppercase tracking-wider text-gray-400 block">Command</label>
                      <input
                        type="text"
                        value={editingConfig.values.command ?? ""}
                        onChange={(e) =>
                          setEditingConfig({
                            ...editingConfig,
                            values: { ...editingConfig.values, command: e.target.value },
                          })
                        }
                        placeholder="npx"
                        className="w-full bg-black/40 border border-white/10 rounded-xl p-3.5 text-sm text-white placeholder:text-gray-600 focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 outline-none transition-all shadow-inner font-mono"
                      />
                    </div>
                    <div className="space-y-2">
                      <label className="text-xs font-bold uppercase tracking-wider text-gray-400 block">
                        Arguments
                        <span className="ml-2 font-normal normal-case tracking-normal text-gray-500">(one argument per line)</span>
                      </label>
                      <textarea
                        rows={Math.max(3, (editingConfig.values.args || []).length + 1)}
                        value={(editingConfig.values.args || []).join("\n")}
                        onChange={(e) => {
                          const args = e.target.value
                            .split("\n")
                            .map((line) => line.trimEnd())
                            .filter((line, i, arr) => line !== "" || i < arr.length - 1);
                          setEditingConfig({ ...editingConfig, values: { ...editingConfig.values, args } });
                        }}
                        placeholder={"mcp-server\n--port\n8080"}
                        className="w-full bg-black/40 border border-white/10 rounded-xl p-3.5 text-sm text-white placeholder:text-gray-600 focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 outline-none transition-all shadow-inner font-mono resize-none leading-relaxed"
                      />
                    </div>
                  </>
                ) : null
              }

              <div className="space-y-2">
                <label className="text-xs font-bold uppercase tracking-wider text-gray-400 block">Description</label>
                <textarea
                  value={editingConfig.values.description || ""}
                  onChange={(e) => setEditingConfig({ ...editingConfig, values: { ...editingConfig.values, description: e.target.value } })}
                  placeholder="MCP server description..."
                  className="w-full bg-black/40 border border-white/10 rounded-xl p-3.5 text-sm text-white placeholder:text-gray-600 focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 outline-none transition-all shadow-inner min-h-[100px]"
                />
              </div>

              <details className="rounded-xl border border-white/10 bg-black/20 p-3 group">
                <summary className="text-xs font-bold text-gray-400 cursor-pointer list-none flex items-center justify-between">
                  <span>Advanced — extra variables (keys not in form only)</span>
                  <span className="text-[10px] text-gray-600 group-open:text-gray-400">JSON</span>
                </summary>
                <textarea
                  value={extraEnvJson(editingConfig.values.env as Record<string, string> | undefined, connectorFormContext.knownKeys)}
                  onChange={(e) => {
                    try {
                      const parsed = JSON.parse(e.target.value) as Record<string, string>;
                      if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) return;
                      const env = { ...(editingConfig.values.env || {}) };
                      for (const key of Object.keys(env)) {
                        if (!connectorFormContext.knownKeys.has(key)) delete env[key];
                      }
                      for (const [key, val] of Object.entries(parsed)) {
                        if (!connectorFormContext.knownKeys.has(key)) env[key] = String(val ?? "");
                      }
                      setEditingConfig({ ...editingConfig, values: { ...editingConfig.values, env } });
                    } catch {
                      /* */
                    }
                  }}
                  spellCheck={false}
                  className="w-full min-h-[100px] mt-3 bg-black/40 border border-white/10 rounded-xl p-3 text-xs text-white font-mono"
                  placeholder='{ "CUSTOM_KEY": "..." }'
                />
              </details>

              <details className="rounded-xl border border-white/10 bg-black/20 p-3 group">
                <summary className="text-xs font-bold text-gray-400 cursor-pointer list-none">Advanced — all environment variables (JSON)</summary>
                <textarea
                  value={JSON.stringify(editingConfig.values.env ?? {}, null, 2)}
                  onChange={(e) => {
                    try {
                      const parsed = JSON.parse(e.target.value);
                      if (parsed !== null && typeof parsed === "object" && !Array.isArray(parsed)) {
                        setEditingConfig({
                          ...editingConfig,
                          values: { ...editingConfig.values, env: parsed as Record<string, string> },
                        });
                      }
                    } catch {
                      /* */
                    }
                  }}
                  spellCheck={false}
                  className="w-full min-h-[120px] mt-3 bg-black/40 border border-white/10 rounded-xl p-3 text-xs text-white font-mono"
                />
              </details>

              <div className={`flex items-center justify-between p-4 rounded-2xl border transition-all ${sandboxBackend === "container" ? 'bg-indigo-500/5 border-indigo-500/20' : 'bg-white/5 border-white/10 opacity-80'}`}>
                <div className="space-y-0.5">
                  <div className="text-sm font-bold text-white flex items-center gap-2">
                    Session sandbox backend
                    {sandboxBackend === "container" && <div className="w-1.5 h-1.5 bg-indigo-500 rounded-full animate-pulse" />}
                  </div>
                  <div className="text-[10px] text-gray-400 uppercase tracking-wider">
                    {sandboxBackend === "container"
                      ? "AION_SANDBOX_BACKEND=container (Podman/Docker per sessione)"
                      : "AION_SANDBOX_BACKEND=subprocess (env scrub, dev/macOS)"}
                  </div>
                </div>
                <div className={`px-3 py-1 rounded-lg text-[10px] font-bold uppercase tracking-wider ${sandboxBackend === "container" ? 'bg-indigo-600/20 text-indigo-300' : 'bg-gray-800 text-gray-400'}`}>
                  {sandboxBackend}
                </div>
              </div>
            </div >

            <div className="flex gap-4 pt-4 border-t border-white/10">
              <button
                onClick={handleSaveConfig}
                disabled={loading}
                className="flex-1 py-3.5 bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white rounded-xl font-bold text-sm transition-all shadow-lg shadow-blue-500/20 disabled:opacity-50 cursor-pointer transform active:scale-98"
              >
                {loading ? "SAVING..." : "SAVE CONFIGURATION"}
              </button>
              <button
                onClick={() => setEditingConfig(null)}
                className="px-6 py-3.5 bg-white/10 hover:bg-white/15 border border-white/10 rounded-xl font-bold transition-all text-white text-sm cursor-pointer"
              >
                CANCEL
              </button>
            </div>
          </div >
        </div >
      )}

      {/* Delete Confirmation Modal */}
      {
        isDeleteModalOpen && mcpToDelete && (
          <div className="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 flex items-center justify-center p-4 animate-in fade-in duration-200">
            <div className="glass-card bg-[#1a1a1a] border border-white/10 rounded-3xl w-full max-w-lg overflow-hidden shadow-2xl animate-in zoom-in-95 duration-200">
              <div className="p-6 border-b border-white/10 flex justify-between items-center bg-white/5">
                <h2 className="text-xl font-bold text-white flex items-center gap-2">
                  <Trash2 className="w-5 h-5 text-red-400" />
                  Confirm Removal
                </h2>
                <button
                  onClick={() => setIsDeleteModalOpen(false)}
                  className="text-gray-500 hover:text-white transition-colors"
                >
                  <X className="w-6 h-6" />
                </button>
              </div>

              <div className="p-6 space-y-4">
                <div className="p-4 bg-red-500/10 border border-red-500/20 rounded-2xl text-red-300 text-sm leading-relaxed">
                  <p className="font-semibold mb-1 text-lg flex items-center gap-2">
                    <AlertTriangle className="w-5 h-5 text-red-400 shrink-0" />
                    <span className="text-white font-bold">
                      WARNING: irreversible operation
                    </span>
                  </p>
                  You are about to remove the MCP module <b className="text-white font-mono">{mcpToDelete}</b> from the system. Agent profiles that use it will no longer be able to access its features.
                </div>
              </div>

              <div className="p-6 border-t border-white/10 flex justify-end gap-3 bg-black/20">
                <button
                  onClick={() => setIsDeleteModalOpen(false)}
                  className="px-5 py-2.5 text-sm font-semibold text-gray-400 hover:text-white transition-colors cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  onClick={confirmDelete}
                  disabled={loading}
                  className="bg-red-600 hover:bg-red-500 text-white px-6 py-2.5 rounded-xl text-sm font-bold transition-all flex items-center gap-2 disabled:opacity-40 disabled:cursor-not-allowed shadow-lg shadow-red-600/20 cursor-pointer"
                >
                  <Trash2 className="w-4 h-4" />
                  {loading ? "Removing..." : "Remove MCP"}
                </button>
              </div>
            </div>
          </div>
        )
      }

      {/* Blocked Deletion Modal */}
      {
        isBlockedModalOpen && mcpToDelete && (
          <div className="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 flex items-center justify-center p-4 animate-in fade-in duration-200">
            <div className="glass-card bg-[#1a1a1a] border border-white/10 rounded-3xl w-full max-w-lg overflow-hidden shadow-2xl animate-in zoom-in-95 duration-200">
              <div className="p-6 border-b border-white/10 flex justify-between items-center bg-white/5">
                <h2 className="text-xl font-bold text-white flex items-center gap-2">
                  <AlertTriangle className="w-5 h-5 text-amber-400" />
                  Removal Blocked
                </h2>
                <button
                  onClick={() => {
                    setIsBlockedModalOpen(false);
                    setMcpToDelete(null);
                  }}
                  className="text-gray-500 hover:text-white transition-colors"
                >
                  <X className="w-6 h-6" />
                </button>
              </div>

              <div className="p-6 space-y-4">
                <div className="p-4 bg-amber-500/10 border border-amber-500/20 rounded-xl text-amber-300 text-sm leading-relaxed">
                  <p className="font-semibold mb-1 text-lg flex items-center gap-2">
                    <span className="text-white font-bold">Module in Use</span>
                  </p>
                  The MCP module <b className="text-white font-mono">{mcpToDelete}</b> cannot be removed because it is currently associated with the following agent profiles:
                </div>

                <div className="space-y-2 max-h-40 overflow-y-auto pr-1 custom-scrollbar">
                  {blockingProfiles.map((pName) => (
                    <div key={pName} className="p-3 bg-black/40 border border-white/5 rounded-xl text-sm text-gray-200 font-semibold flex items-center gap-2">
                      <span className="w-2 h-2 rounded-full bg-blue-500"></span>
                      {pName}
                    </div>
                  ))}
                </div>

                <p className="text-xs text-gray-400 italic pt-2">
                  Remove this MCP module from the indicated profiles before proceeding with uninstallation.
                </p>
              </div>

              <div className="p-6 border-t border-white/10 flex justify-end bg-black/20">
                <button
                  onClick={() => {
                    setIsBlockedModalOpen(false);
                    setMcpToDelete(null);
                  }}
                  className="bg-white/10 hover:bg-white/15 text-white px-6 py-2.5 rounded-xl text-sm font-bold transition-all cursor-pointer"
                >
                  Got it
                </button>
              </div>
            </div>
          </div>
        )
      }

      {
        adviseOpen && (
          <div className="fixed inset-0 z-[60] bg-black/70 flex items-center justify-center p-4">
            <div className="bg-[#1a1a1a] border border-white/10 rounded-2xl max-w-lg w-full p-6 space-y-4">
              <h3 className="text-lg font-bold text-white">MCP Integration Advisory</h3>
              {adviseLoading ? (
                <p className="text-sm text-gray-400">Analysis in progress…</p>
              ) : (
                <pre className="text-xs text-gray-300 whitespace-pre-wrap">{adviseResult?.steps_markdown || "No results"}</pre>
              )}
              <button type="button" onClick={() => setAdviseOpen(false)} className="text-sm text-gray-400 hover:text-white">Close</button>
            </div>
          </div>
        )
      }

      {
        wizardTarget && (
          <McpInstallWizard
            title={wizardTarget.title}
            serverSlug={wizardTarget.kind === "server" ? wizardTarget.serverSlug : undefined}
            marketItemId={wizardTarget.kind === "market" ? wizardTarget.marketItemId : undefined}
            onClose={() => setWizardTarget(null)}
            onDone={() => {
              fetchRegistry();
              void fetchIntegrations();
              setActiveTab("installed");
            }}
          />
        )
      }

      <PageToast toast={toast} onDismiss={() => setToast(null)} />
    </div >
  );
}
