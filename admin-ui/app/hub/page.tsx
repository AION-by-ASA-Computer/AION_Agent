"use client";

import { useState, useEffect, useMemo, useCallback } from "react";
import { apiFetch } from "@/lib/api/headers";
import {
  Search,
  Download,
  ShieldCheck,
  AlertCircle,
  Globe,
  Terminal,
  Box,
  X,
  Trash2,
  AlertTriangle,
  Users,
  MessageSquare,
  Wand2,
  GitBranch,
  Loader2,
  ExternalLink,
  Sparkles,
  Layers,
  Briefcase,
  Database,
  Code2,
  Activity,
  CheckCircle2,
  KeyRound,
  Sliders,
  SlidersHorizontal,
  Cpu,
  Shield,
  FileCode,
} from "lucide-react";
import { apiBase } from "@/lib/api";
import { PageToast, ToastState } from "@/components/PageToast";
import { buildCredentialFields, extraEnvJson, matchConnectorRow } from "@/lib/mcpConnectorUi";
import {
  CredentialMode,
  CredentialSchemaField,
  IntegrationPolicyRow,
  modeLabel,
  normalizeCredentialSchema,
} from "@/lib/mcpIntegrationPolicy";
import { CredentialSchemaEditor } from "@/components/CredentialSchemaEditor";
import { McpOAuthAdminSetupPanel } from "@/components/McpOAuthAdminSetupPanel";
import { RemoteMcpInstallModal, type RemoteCatalogPreset } from "@/components/RemoteMcpInstallModal";
import { McpIntegrityBanner, type McpIntegrityIssue } from "@/components/McpIntegrityBanner";
import { McpEnvYamlPanel } from "@/components/McpEnvYamlPanel";
import { connectorOAuthSetupHints } from "@/lib/mcpOAuthSetup";
import { SlideOver } from "@/components/ui/SlideOver";
import { KeyValueBuilder } from "@/components/KeyValueBuilder";
import { McpDataTable, type McpItemRow } from "@/components/McpDataTable";
import { MCP_CATEGORIES, categorizeMcp, type McpCategory } from "@/lib/mcpCategories";
import { DynamicWizardModal, type DynamicWizardTarget } from "@/components/DynamicWizardModal";
import { McpToolsManageModal } from "@/components/McpToolsManageModal";

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
  const [analyzingGithub, setAnalyzingGithub] = useState(false);

  const [zeroWizardOpen, setZeroWizardOpen] = useState(false);
  const [zeroWizardTarget, setZeroWizardTarget] = useState<DynamicWizardTarget | null>(null);

  const [manageToolsSlug, setManageToolsSlug] = useState<string | null>(null);

  const [remoteInstallOpen, setRemoteInstallOpen] = useState(false);
  const [remoteModalSeed, setRemoteModalSeed] = useState<{
    url?: string;
    displayName?: string;
    connectorId?: string;
  }>({});

  const [activeTab, setActiveTab] = useState<"marketplace" | "installed">("installed");
  const [mcpFilter, setMcpFilter] = useState("all");
  const [marketCategory, setMarketCategory] = useState<McpCategory>("all");

  const handleTabChange = useCallback((tab: "installed" | "marketplace") => {
    setActiveTab(tab);
    setMcpFilter("all");
  }, []);

  const [editingConfig, setEditingConfig] = useState<any>(null);
  const [configTab, setConfigTab] = useState<"runtime" | "policy">("runtime");
  const [toast, setToast] = useState<ToastState>(null);
  const [probingSlug, setProbingSlug] = useState<string | null>(null);

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
  const [userMayDisable, setUserMayDisable] = useState(true);
  const [integrityIssues, setIntegrityIssues] = useState<McpIntegrityIssue[]>([]);
  const [oauthConfig, setOauthConfig] = useState<{
    provider: string;
    authorization_server: string;
    token_url: string;
    client_id: string;
    client_secret: string;
    scopes: string[];
    client_id_source?: string;
  }>({
    provider: "generic",
    authorization_server: "",
    token_url: "",
    client_id: "",
    client_secret: "",
    scopes: [],
  });

  const fetchIntegrity = useCallback(async () => {
    try {
      const res = await apiFetch(`${apiBase()}/admin/mcp/integrity`);
      if (!res.ok) return;
      const data = await res.json();
      setIntegrityIssues(Array.isArray(data.issues) ? data.issues : []);
    } catch {
      setIntegrityIssues([]);
    }
  }, []);

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
    void fetchIntegrity();
    void ensureConnectorCatalog();
  }, [fetchIntegrations, fetchIntegrity]);

  useEffect(() => {
    if (activeTab === "marketplace") {
      void ensureConnectorCatalog();
      if (marketItems.length === 0) {
        void runMarketSearch("");
      }
    }
  }, [activeTab, marketItems.length]);

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
    const q = (qRaw || "").trim();
    setLoading(true);
    try {
      const res = await apiFetch(`${apiBase()}/admin/market/search?q=${encodeURIComponent(q)}`);
      if (!res.ok) throw new Error("Search failed");
      const data = await res.json();
      setMarketItems(data.filter((item: any) => item.source !== "Official Registry"));
      if (data.length === 0 && q) {
        setToast({ message: "No results found in Marketplace.", variant: "error" });
      }
    } catch (e: any) {
      setToast({ message: "Search error: " + e.message, variant: "error" });
    } finally {
      setLoading(false);
    }
  };

  const handleSearch = async () => {
    await runMarketSearch(searchQuery);
  };

  const openEditConfig = async (name: string, config: Record<string, unknown>) => {
    void ensureConnectorCatalog();
    let policy = integrationBySlug[name];
    try {
      const res = await apiFetch(`${apiBase()}/admin/mcp-integrations`);
      if (res.ok) {
        const data = await res.json();
        const map: Record<string, IntegrationPolicyRow> = {};
        for (const row of (data.integrations || []) as IntegrationPolicyRow[]) {
          map[row.server_slug] = row;
        }
        setIntegrationBySlug(map);
        policy = map[name] ?? policy;
      }
    } catch {
      /* use cached policy */
    }
    const args = Array.isArray(config.args) ? config.args : [];
    const env = config.env && typeof config.env === "object" && !Array.isArray(config.env) ? { ...(config.env as object) } : {};
    setUserMayDisable(policy?.user_may_disable !== false);
    setConfigTab("runtime");
    setEditingConfig({
      name,
      values: {
        ...config,
        rawArgsText: args.join("\n"),
        rawAllEnvText: JSON.stringify(env, null, 2),
        env,
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
      client_id_source: oauth.client_id_source || "",
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
      const matched = matchConnectorRow(
        slug,
        editingConfig?.values?.aion_connector_id as string | undefined,
        connectorRows as Record<string, unknown>[],
      );
      const setupHints = connectorOAuthSetupHints(matched);
      const catalogOauth = (matched?.oauth || {}) as Record<string, string>;
      const scopes =
        oauthConfig.scopes && oauthConfig.scopes.length > 0
          ? oauthConfig.scopes
          : setupHints.scopes;
      body.oauth_config = {
        provider: oauthConfig.provider || "generic",
        authorization_server:
          oauthConfig.authorization_server || catalogOauth.authorization_server || "",
        token_url: oauthConfig.token_url || catalogOauth.token_url || "",
        client_id: oauthConfig.client_id,
        client_secret: oauthConfig.client_secret,
        scopes,
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
      const newEnv = data.env || editingConfig.values.env || {};
      setEditingConfig({
        ...editingConfig,
        values: {
          ...editingConfig.values,
          env: newEnv,
          rawAllEnvText: JSON.stringify(newEnv, null, 2),
        },
      });
      setToast({ message: "Suggested env applied to local registry.", variant: "success" });
      void loadPolicyPreview(editingConfig.name, editingPolicy.mode);
      fetchRegistry();
    } catch (e: unknown) {
      setToast({ message: "Failed to apply suggested env: " + (e instanceof Error ? e.message : String(e)), variant: "error" });
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
      setAdviseResult({ steps_markdown: e instanceof Error ? e.message : "MCP advisory error" });
    } finally {
      setAdviseLoading(false);
    }
  };

  const handleSaveConfig = async () => {
    if (!editingConfig) return;
    setLoading(true);
    try {
      const v = editingConfig.values;
      const rawArgs = typeof v.rawArgsText === "string" ? v.rawArgsText : (Array.isArray(v.args) ? v.args.join("\n") : "");
      const parsedArgs = rawArgs
        .split("\n")
        .map((line: string) => line.trim())
        .filter((line: string) => line.length > 0);

      const finalEnv = v.env && typeof v.env === "object" && !Array.isArray(v.env) ? { ...v.env } : {};

      const payload: Record<string, unknown> = {
        command: typeof v.command === "string" ? v.command : "python",
        args: parsedArgs,
        env: finalEnv,
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
      const res = await apiFetch(`${apiBase()}/admin/mcp/${editingConfig.name}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error("Save failed");
      if (editingPolicy) {
        await saveIntegrationPolicy(editingConfig.name);
        await fetchIntegrations();
      }
      fetchRegistry();
      setEditingConfig(null);
      setEditingPolicy(null);
      setAdviseOpen(false);
      setAdviseResult(null);
      setToast({ message: "MCP configuration and policy saved successfully!", variant: "success" });
    } catch (e: any) {
      setToast({ message: "Error while saving: " + e.message, variant: "error" });
    } finally {
      setLoading(false);
    }
  };

  const initiateDelete = async (name: string) => {
    setLoading(true);
    try {
      const res = await apiFetch(`${apiBase()}/admin/profiles`);
      if (!res.ok) throw new Error("Failed to retrieve profiles");
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
      setToast({ message: "Error checking profiles: " + e.message, variant: "error" });
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
      void fetchIntegrations();
      void fetchIntegrity();
      setToast({
        message: `MCP '${mcpToDelete}' removed (user credentials deleted).`,
        variant: "success",
      });
      setIsDeleteModalOpen(false);
      setMcpToDelete(null);
    } catch (e: any) {
      setToast({ message: "Error during removal: " + e.message, variant: "error" });
    } finally {
      setLoading(false);
    }
  };

  const probeMcp = async (name: string) => {
    setProbingSlug(name);
    setLoading(true);
    setToast({
      message: `Testing connection to '${name}'... Probing server and discovering tools.`,
      variant: "loading",
    });
    try {
      const res = await apiFetch(`${apiBase()}/admin/mcp/${encodeURIComponent(name)}/probe`, {
        method: "POST",
      });
      const data = await res.json();
      if (!res.ok || !data.ok) {
        const errorType = data.error_type;
        const errorMsg = data.error || `Probe failed (${res.status})`;
        const hint = data.hint ? ` — ${data.hint}` : "";

        let prefix = "Probe Failed";
        if (errorType === "timeout") prefix = "Connection Timeout";
        else if (errorType === "executable_missing") prefix = "Host Environment Error";
        else if (errorType === "auth_failed") prefix = "Authentication Failed";
        else if (errorType === "process_crashed") prefix = "MCP Process Crash";
        else if (errorType === "empty_tools") prefix = "No Tools Discovered";

        setToast({
          message: `${prefix}: ${errorMsg}${hint}`,
          variant: "error",
        });
        return;
      }

      if (data.note) {
        setToast({
          message: `Probe OK: ${data.note}`,
          variant: "success",
        });
        return;
      }

      const names = (data.tools || []).map((t: { name?: string }) => t.name).filter(Boolean);
      const count = data.tool_count ?? names.length;
      setToast({
        message: `Probe OK: ${count} active ${count === 1 ? "tool" : "tools"} discovered (${names.slice(0, 8).join(", ") || "ready"})`,
        variant: "success",
      });
    } catch (e: unknown) {
      setToast({ message: "MCP Probe: " + (e instanceof Error ? e.message : String(e)), variant: "error" });
    } finally {
      setProbingSlug(null);
      setLoading(false);
    }
  };

  const handleInstallGithub = async () => {
    const url = githubUrl.trim();
    if (!url) {
      setToast({ message: "Enter a valid GitHub URL.", variant: "error" });
      return;
    }
    setAnalyzingGithub(true);
    try {
      const res = await apiFetch(`${apiBase()}/admin/market/analyze-github`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "GitHub repository analysis failed.");
      }
      const data = await res.json();
      setGithubInstallOpen(false);
      setGithubUrl("");
      setGithubDisplayName("");
      setZeroWizardTarget({
        display_name: githubDisplayName.trim() || data.package_url || "mcp_github",
        description: data.description,
        runner: data.runner,
        package_url: data.package_url,
        command_args: data.command_args,
        required_envs: data.required_envs,
        cli_args: data.cli_args || [],
        source: "GitHub",
      });
      setZeroWizardOpen(true);
    } catch (err: any) {
      setToast({ message: err.message || "Error during analysis.", variant: "error" });
    } finally {
      setAnalyzingGithub(false);
    }
  };

  const openRemoteInstall = useCallback(
    (seed?: { url?: string; displayName?: string; connectorId?: string }) => {
      setRemoteModalSeed(seed || {});
      setRemoteInstallOpen(true);
    },
    [],
  );

  const featuredRemoteConnectors = useMemo(() => {
    return (connectorRows as RemoteCatalogPreset[]).filter(
      (c) => c.featured_remote && c.install_type === "remote" && c.remote_url,
    );
  }, [connectorRows]);

  const handleInstallFromCatalog = async (connectorId: string, row?: Record<string, unknown>) => {
    if (row?.remote_url_template) {
      openRemoteInstall({
        url: String(row.remote_url || ""),
        displayName: String(row.title || connectorId),
        connectorId,
      });
      return;
    }
    setInstallingId(`catalog:${connectorId}`);
    setLoading(true);
    try {
      const res = await apiFetch(
        `${apiBase()}/admin/mcp/install-from-catalog?connector_id=${encodeURIComponent(connectorId)}`,
        { method: "POST" },
      );
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
        message: `Connector '${connectorId}' installed as '${data.server_slug || data.name}'.`,
        variant: "success",
      });
      fetchRegistry();
      setActiveTab("installed");
    } catch (e: unknown) {
      setToast({
        message: "Catalog installation: " + (e instanceof Error ? e.message : String(e)),
        variant: "error",
      });
    } finally {
      setInstallingId(null);
      setLoading(false);
    }
  };

  const displayedMarketItems = useMemo(() => {
    let items = marketItems.filter((item) => item.source !== "Official Registry");
    if (mcpFilter !== "all") {
      items = items.filter((item) => item.source === mcpFilter);
    }
    if (marketCategory !== "all" && marketCategory !== "official") {
      items = items.filter((item) => categorizeMcp(item) === marketCategory);
    }
    return items;
  }, [marketItems, mcpFilter, marketCategory]);

  const filteredFeaturedConnectors = useMemo(() => {
    if (marketCategory === "all" || marketCategory === "official") {
      return featuredRemoteConnectors;
    }
    return featuredRemoteConnectors.filter((c) => categorizeMcp(c as any) === marketCategory);
  }, [featuredRemoteConnectors, marketCategory]);

  const filteredInstalledItems = useMemo(() => {
    return Object.entries(installedItems).filter(([name, config]: [string, any]) => {
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
  }, [installedItems, searchQuery, mcpFilter]);

  const dataTableItems: McpItemRow[] = useMemo(() => {
    return filteredInstalledItems.map(([name, config]: [string, any]) => {
      const slugIssues = integrityIssues.filter(
        (i) => i.server_slug === name || i.from_slug === name,
      );
      const connector = matchConnectorRow(
        name,
        config.aion_connector_id || integrationBySlug[name]?.aion_connector_id || undefined,
        connectorRows as Record<string, unknown>[],
      );
      return {
        name,
        config,
        policy: integrationBySlug[name],
        connector,
        issues: slugIssues,
      };
    });
  }, [filteredInstalledItems, integrityIssues, integrationBySlug, connectorRows]);

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

  const renderCategoryIcon = (id: McpCategory) => {
    switch (id) {
      case "all":
        return <Layers className="w-4 h-4" />;
      case "official":
        return <Sparkles className="w-4 h-4 text-amber-400" />;
      case "productivity":
        return <Briefcase className="w-4 h-4 text-blue-400" />;
      case "database":
        return <Database className="w-4 h-4 text-emerald-400" />;
      case "developer":
        return <Code2 className="w-4 h-4 text-purple-400" />;
      case "observability":
        return <Activity className="w-4 h-4 text-rose-400" />;
      case "web":
        return <Globe className="w-4 h-4 text-sky-400" />;
      default:
        return <Box className="w-4 h-4" />;
    }
  };

  return (
    <div className="space-y-8 pb-20">
      {/* Top Header */}
      <header className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 p-6">
        <div className="space-y-1">
          <div className="flex items-center gap-3">
            <h2 className="text-3xl font-extrabold tracking-tight text-white">MCP Hub</h2>
          </div>
          <p className="text-sm text-gray-400 max-w-xl mt-1">
            Manage Model Context Protocol servers, user credential policies, and enterprise connector catalogs.
          </p>
        </div>
        {sandboxBackend === "container" && (
          <div className="flex items-center gap-3 px-4 py-2 bg-indigo-500/10 border border-indigo-500/20 rounded-2xl animate-in fade-in zoom-in duration-500 shadow-lg shadow-indigo-500/5">
            <div className="w-2 h-2 bg-indigo-500 rounded-full animate-pulse shadow-[0_0_8px_#6366f1]" />
            <div className="flex flex-col">
              <span className="text-[10px] font-black text-indigo-400 uppercase tracking-widest leading-none">Sandbox Mode</span>
              <span className="text-xs font-bold text-white mt-0.5 flex items-center gap-1.5">
                <Terminal className="w-3 h-3" />
                Container Isolation (Podman)
              </span>
            </div>
          </div>
        )}
      </header>

      {/* Primary Navigation Tabs */}
      <div className="flex border-b border-white/10 px-6 gap-8">
        <button
          onClick={() => handleTabChange("installed")}
          className={`py-4 text-sm font-bold relative transition-colors flex items-center gap-2 cursor-pointer ${activeTab === "installed" ? "text-blue-400" : "text-gray-500 hover:text-gray-300"
            }`}
        >
          <Activity className="w-4 h-4" />
          Installed Servers & Status
          <span className="px-2 py-0.5 text-[10px] bg-white/10 rounded-full text-gray-300 font-mono">
            {Object.keys(installedItems).length}
          </span>
          {activeTab === "installed" && (
            <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-blue-500 shadow-[0_0_8px_#3b82f6]" />
          )}
        </button>
        <button
          onClick={() => handleTabChange("marketplace")}
          className={`py-4 text-sm font-bold relative transition-colors flex items-center gap-2 cursor-pointer ${activeTab === "marketplace" ? "text-blue-400" : "text-gray-500 hover:text-gray-300"
            }`}
        >
          <Globe className="w-4 h-4" />
          Marketplace & Connectors
          {activeTab === "marketplace" && (
            <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-blue-500 shadow-[0_0_8px_#3b82f6]" />
          )}
        </button>
      </div>

      {/* Global Filter Bar */}
      <div className="flex flex-col sm:flex-row gap-4 px-6">
        <div className="relative flex-1 group">
          <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500 group-focus-within:text-blue-400 transition-colors" />
          <input
            type="text"
            placeholder={
              activeTab === "marketplace"
                ? "Search Marketplace (e.g. Slack, GitHub, Postgres, Claude, OpenClaw...)"
                : "Filter installed MCP servers by name, connector, or description..."
            }
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && activeTab === "marketplace" && handleSearch()}
            className="w-full bg-black/40 backdrop-blur-sm border border-white/10 rounded-xl pl-10 pr-10 py-3.5 text-sm text-white placeholder:text-gray-600 focus:border-blue-500/80 focus:ring-4 focus:ring-blue-500/10 outline-none transition-all shadow-inner font-medium"
          />
          {searchQuery && (
            <button
              onClick={() => setSearchQuery("")}
              className="absolute right-3.5 top-1/2 -translate-y-1/2 text-gray-500 hover:text-white transition-colors p-1 cursor-pointer"
            >
              <X className="w-4 h-4" />
            </button>
          )}
        </div>

        {activeTab === "marketplace" ? (
          <>
            {/* Category Dropdown Selector */}
            <div className="relative min-w-[220px]">
              <select
                value={marketCategory}
                onChange={(e) => setMarketCategory(e.target.value as McpCategory)}
                className="w-full bg-black/40 backdrop-blur-sm border border-white/10 rounded-xl px-4 py-3.5 text-sm text-white focus:border-blue-500/80 focus:ring-4 focus:ring-blue-500/10 outline-none transition-all cursor-pointer appearance-none pr-10 font-medium"
                style={{
                  backgroundImage: `url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='24' height='24' viewBox='0 0 24 24' fill='none' stroke='%239ca3af' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><polyline points='6 9 12 15 18 9'></polyline></svg>")`,
                  backgroundRepeat: "no-repeat",
                  backgroundPosition: "right 12px center",
                  backgroundSize: "16px",
                }}
              >
                {MCP_CATEGORIES.map((cat) => (
                  <option key={cat.id} value={cat.id} className="bg-[#1a1a1a] text-white">
                    {cat.label}
                  </option>
                ))}
              </select>
            </div>

            {/* Source Dropdown Selector */}
            <div className="relative min-w-[190px]">
              <select
                value={mcpFilter}
                onChange={(e) => setMcpFilter(e.target.value)}
                className="w-full bg-black/40 backdrop-blur-sm border border-white/10 rounded-xl px-4 py-3.5 text-sm text-white focus:border-blue-500/80 focus:ring-4 focus:ring-blue-500/10 outline-none transition-all cursor-pointer appearance-none pr-10 font-medium"
                style={{
                  backgroundImage: `url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='24' height='24' viewBox='0 0 24 24' fill='none' stroke='%239ca3af' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><polyline points='6 9 12 15 18 9'></polyline></svg>")`,
                  backgroundRepeat: "no-repeat",
                  backgroundPosition: "right 12px center",
                  backgroundSize: "16px",
                }}
              >
                <option value="all" className="bg-[#1a1a1a] text-white">All Sources</option>
                <option value="Smithery" className="bg-[#1a1a1a] text-white">Smithery Registry</option>
                <option value="Glama.ai" className="bg-[#1a1a1a] text-white">Glama.ai Registry</option>
                <option value="Google Cloud" className="bg-[#1a1a1a] text-white">Google Cloud</option>
                <option value="Claude Community" className="bg-[#1a1a1a] text-white">Claude Community</option>
                <option value="GitHub" className="bg-[#1a1a1a] text-white">GitHub Topic</option>
                <option value="Awesome List" className="bg-[#1a1a1a] text-white">Awesome MCP List</option>
              </select>
            </div>
          </>
        ) : (
          <div className="relative min-w-[200px]">
            <select
              value={mcpFilter}
              onChange={(e) => setMcpFilter(e.target.value)}
              className="w-full bg-black/40 backdrop-blur-sm border border-white/10 rounded-xl px-4 py-3.5 text-sm text-white focus:border-blue-500/80 focus:ring-4 focus:ring-blue-500/10 outline-none transition-all cursor-pointer appearance-none pr-10 font-medium"
              style={{
                backgroundImage: `url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='24' height='24' viewBox='0 0 24 24' fill='none' stroke='%239ca3af' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><polyline points='6 9 12 15 18 9'></polyline></svg>")`,
                backgroundRepeat: "no-repeat",
                backgroundPosition: "right 12px center",
                backgroundSize: "16px",
              }}
            >
              <option value="all" className="bg-[#1a1a1a] text-white">All Runtime Types</option>
              <option value="built_in" className="bg-[#1a1a1a] text-white">System (Built-in)</option>
              <option value="stdio" className="bg-[#1a1a1a] text-white">Local (Stdio)</option>
              <option value="sse" className="bg-[#1a1a1a] text-white">Remote (SSE)</option>
              <option value="remote-bridge" className="bg-[#1a1a1a] text-white">Remote Bridge (OAuth)</option>
              <option value="in_process" className="bg-[#1a1a1a] text-white">In-Process</option>
            </select>
          </div>
        )}

        {activeTab === "marketplace" && (
          <>
            <button
              onClick={handleSearch}
              disabled={loading || !searchQuery.trim()}
              className="w-36 py-3.5 bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white rounded-xl font-bold text-sm shadow-lg shadow-blue-500/20 transition-all transform active:scale-95 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2 select-none"
            >
              {loading && !githubInstallOpen ? (
                <>
                  <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin shrink-0" />
                  <span>SEARCH</span>
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
              className="px-4 py-3.5 bg-white/5 hover:bg-white/10 border border-white/15 text-white rounded-xl font-bold text-sm transition-all cursor-pointer disabled:opacity-50 flex items-center justify-center gap-2"
              title="Install custom GitHub repository"
            >
              <GitBranch className="w-4 h-4 text-purple-400" />
              GITHUB
            </button>
            <button
              type="button"
              onClick={() => openRemoteInstall()}
              disabled={loading || installingId !== null}
              className="px-4 py-3.5 bg-white/5 hover:bg-white/10 border border-white/15 text-white rounded-xl font-bold text-sm transition-all cursor-pointer disabled:opacity-50 flex items-center justify-center gap-2"
              title="Install remote SSE/HTTP endpoint"
            >
              <Globe className="w-4 h-4 text-sky-400" />
              REMOTE
            </button>
          </>
        )}
      </div>

      {/* GitHub Install Modal (Zero-Clone) */}
      {githubInstallOpen && (
        <div className="fixed inset-0 z-[65] bg-black/75 flex items-center justify-center p-4">
          <div className="bg-[#1a1a1a] border border-white/10 rounded-2xl max-w-lg w-full p-6 space-y-4 shadow-2xl">
            <div className="flex justify-between items-start gap-4">
              <div>
                <h3 className="text-lg font-bold text-white flex items-center gap-2">
                  <GitBranch className="w-5 h-5 text-purple-400" />
                  Install from GitHub (Zero-Clone)
                </h3>
                <p className="text-xs text-gray-400 mt-1">
                  Instant manifest analysis without cloning to disk. Configure and run on-demand via <code className="text-emerald-300">npx</code> or <code className="text-emerald-300">uvx</code>.
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
              GitHub Repository URL
              <input
                type="url"
                value={githubUrl}
                onChange={(e) => setGithubUrl(e.target.value)}
                placeholder="https://github.com/ai-zerolab/mcp-email-server"
                className="mt-1.5 w-full bg-black/40 border border-white/10 rounded-xl px-3 py-2.5 text-sm text-white placeholder:text-gray-600 focus:border-blue-500/80 outline-none font-mono"
              />
            </label>
            <label className="block text-xs font-bold text-gray-400 uppercase tracking-wider">
              Server Name / Display Name (Optional)
              <input
                type="text"
                value={githubDisplayName}
                onChange={(e) => setGithubDisplayName(e.target.value)}
                placeholder="MCP Email Server"
                className="mt-1.5 w-full bg-black/40 border border-white/10 rounded-xl px-3 py-2.5 text-sm text-white placeholder:text-gray-600 focus:border-blue-500/80 outline-none font-mono"
              />
            </label>
            <div className="flex gap-3 justify-end pt-2">
              <button
                type="button"
                onClick={() => setGithubInstallOpen(false)}
                disabled={analyzingGithub}
                className="px-4 py-2 text-sm text-gray-400 hover:text-white cursor-pointer"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleInstallGithub}
                disabled={!githubUrl.trim() || analyzingGithub}
                className="px-5 py-2.5 bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white rounded-xl text-sm font-bold disabled:opacity-50 cursor-pointer flex items-center gap-2 shadow-lg shadow-indigo-500/20"
              >
                {analyzingGithub ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Analyzing Manifests with AI...
                  </>
                ) : (
                  <>
                    <Sparkles className="w-4 h-4" /> Analyze &amp; Configure
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Remote MCP Install Modal */}
      <RemoteMcpInstallModal
        open={remoteInstallOpen}
        onClose={() => setRemoteInstallOpen(false)}
        presets={featuredRemoteConnectors}
        initialUrl={remoteModalSeed.url || ""}
        initialDisplayName={remoteModalSeed.displayName || ""}
        initialConnectorId={remoteModalSeed.connectorId || ""}
        installing={installingId === "remote:manual"}
        onInstallStart={() => setInstallingId("remote:manual")}
        onInstallEnd={() => setInstallingId(null)}
        onInstalled={(slug) => {
          setToast({
            message: `Remote MCP server installed as '${slug}'. Configure credentials in chat-ui → My Integrations.`,
            variant: "success",
          });
          fetchRegistry();
          setActiveTab("installed");
        }}
      />

      {/* Tab Content: Installed (Observability DataTable View) */}
      {activeTab === "installed" && (
        <section className="space-y-6 px-6 animate-in fade-in duration-200">
          <McpIntegrityBanner
            onRepaired={() => {
              void fetchIntegrations();
              void fetchIntegrity();
              fetchRegistry();
            }}
          />

          <div className="flex items-center justify-between">
            <h3 className="text-xs font-bold uppercase tracking-wider text-gray-400 flex items-center gap-2">
              <Activity className="w-4 h-4 text-emerald-400" />
              Active Servers Overview ({dataTableItems.length})
            </h3>
          </div>

          <McpDataTable
            items={dataTableItems}
            loading={loading}
            probingSlug={probingSlug}
            onEdit={(name, config) => void openEditConfig(name, config)}
            onProbe={(name) => void probeMcp(name)}
            onWizard={(name) => {
              const cfg = installedItems[name];
              const runner = cfg?.command === "uvx" ? "uvx" : "npx";
              const pkg =
                (cfg as any)?.zero_package ||
                (cfg?.args && cfg.args.length > 0
                  ? cfg.args[cfg.args.length - 1]
                  : name);
              const required_envs = Object.entries(cfg?.env || {}).map(([k, v]) => {
                const valStr = String(v || "");
                const isSec = valStr.startsWith("${") && valStr.endsWith("}");
                return {
                  key: k,
                  is_secret: isSec,
                  default: isSec ? "" : valStr,
                };
              });
              setZeroWizardTarget({
                id: name,
                qualified_name: name,
                display_name: name,
                description: cfg?.description || "",
                runner,
                package_url: pkg,
                required_envs,
              });
              setZeroWizardOpen(true);
            }}
            onDelete={(name) => void initiateDelete(name)}
            onAdvisor={(name) => {
              const cfg = installedItems[name];
              if (cfg) {
                setEditingConfig({ name, values: cfg });
                void runAdvise();
              }
            }}
            onManageTools={(name) => setManageToolsSlug(name)}
            advisorUrl={(name) => chatUiAdvisorUrl(name)}
          />
        </section>
      )}

      {/* Tab Content: Marketplace (Full-Width 3-Column View with Top Filters) */}
      {activeTab === "marketplace" && (
        <div className="px-6 space-y-8 animate-in fade-in duration-200">
          {/* Section: Curated / Official Connectors (Gold Border Styling) */}
          {(marketCategory === "all" || marketCategory === "official" || filteredFeaturedConnectors.length > 0) && (
            <section className="space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="text-sm font-bold uppercase tracking-wider text-emerald-300 flex items-center gap-2">
                    <Sparkles className="w-4 h-4 text-emerald-400" />
                    Official &amp; Verified Connectors ({filteredFeaturedConnectors.length})
                  </h2>
                  <p className="text-xs text-gray-400 mt-1">
                    Certified enterprise endpoints. Fast setup and per-user authentication in chat-ui.
                  </p>
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                {filteredFeaturedConnectors.map((c: Record<string, unknown>) => {
                  const id = String(c.id || "");
                  const installingThis = installingId === `catalog:${id}`;
                  const hasOAuth = Boolean(c.oauth);
                  const officialDocUrl =
                    String(c.official_doc_url || "").trim() ||
                    String(c.remote_url || "").trim() ||
                    String(c.homepage || "").trim();

                  return (
                    <div
                      key={id}
                      className="glass-card relative flex flex-col justify-between rounded-2xl border border-emerald-500/30 bg-gradient-to-br from-emerald-500/5 via-[#141417] to-[#101012] p-5.5 shadow-xl hover:border-emerald-400/70 transition-all duration-200 group"
                    >
                      <div className="space-y-3.5">
                        {/* Header: Icon + Title */}
                        <div className="flex items-start justify-between gap-3">
                          <div className="flex items-center gap-3 min-w-0">
                            <div className="w-10 h-10 rounded-xl bg-emerald-500/15 border border-emerald-500/30 flex items-center justify-center text-emerald-400 shrink-0">
                              <ShieldCheck className="w-5 h-5" />
                            </div>
                            <div className="min-w-0">
                              {officialDocUrl ? (
                                <a
                                  href={officialDocUrl}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  title={`Open documentation (${officialDocUrl})`}
                                  className="group/link inline-flex items-center gap-1.5 text-white hover:text-emerald-300 transition-colors max-w-full"
                                >
                                  <h3 className="text-base font-bold truncate">{String(c.title || id)}</h3>
                                  <ExternalLink className="w-3.5 h-3.5 opacity-60 group-hover/link:opacity-100 transition-opacity shrink-0 text-gray-400" />
                                </a>
                              ) : (
                                <h3 className="text-base font-bold text-white truncate">
                                  {String(c.title || id)}
                                </h3>
                              )}
                              <div className="text-[11px] text-gray-500 font-mono truncate">{id}</div>
                            </div>
                          </div>
                        </div>

                        {/* Description */}
                        <p className="text-xs text-gray-300/80 line-clamp-2 leading-relaxed min-h-[2.5rem]">
                          {String(c.description || "").trim() || String(c.remote_url || "")}
                        </p>

                        {/* Center Installation Type Banner (Type 1: Certified & Verified) */}
                        <div className="flex items-center gap-3 px-3.5 py-2.5 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-300">
                          <ShieldCheck className="w-4 h-4 text-emerald-400 shrink-0" />
                          <div className="min-w-0">
                            <div className="text-xs font-bold text-emerald-300 flex items-center gap-1.5">
                              <span>Certified &amp; Verified MCP</span>
                              {hasOAuth && (
                                <span className="text-[9px] px-1.5 py-0.5 bg-emerald-500/20 rounded border border-emerald-500/30 text-emerald-200 uppercase font-mono">
                                  OAuth
                                </span>
                              )}
                            </div>
                            <div className="text-[11px] text-emerald-400/80 truncate">
                              {hasOAuth
                                ? "Official integration with verified OAuth authentication"
                                : "Pre-verified official integration with direct support"}
                            </div>
                          </div>
                        </div>
                      </div>

                      {/* Footer: Action Button */}
                      <div className="pt-3.5 mt-3.5 border-t border-white/10 flex items-center justify-end">

                        {c.remote_url_template ? (
                          <button
                            type="button"
                            onClick={() =>
                              openRemoteInstall({
                                url: String(c.remote_url || ""),
                                displayName: String(c.title || id),
                                connectorId: id,
                              })
                            }
                            className="text-xs font-bold text-emerald-300 bg-emerald-500/20 border border-emerald-500/30 px-4 py-2 rounded-xl hover:bg-emerald-500/30 cursor-pointer transition"
                          >
                            Configure URL
                          </button>
                        ) : (
                          <button
                            type="button"
                            onClick={() => void handleInstallFromCatalog(id, c)}
                            disabled={installingId !== null || loading}
                            className="text-xs font-bold text-black bg-emerald-400 hover:bg-emerald-300 px-4 py-2 rounded-xl disabled:opacity-50 cursor-pointer flex items-center gap-1.5 shadow-md shadow-emerald-500/20 transition"
                          >
                            {installingThis ? (
                              <Loader2 className="w-3.5 h-3.5 animate-spin" />
                            ) : (
                              <Download className="w-3.5 h-3.5" />
                            )}
                            Install
                          </button>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </section>
          )}

          {/* Section: Community / Discovered Marketplace Items */}
          {marketCategory !== "official" && (
            <section className="space-y-4 pt-2">
              <h2 className="text-xs font-bold uppercase tracking-wider text-gray-400 flex items-center gap-2">
                <Globe className="w-3.5 h-3.5" />
                Community Modules &amp; External Sources ({displayedMarketItems.length})
              </h2>

              {loading && !githubInstallOpen ? (
                <div className="flex flex-col items-center justify-center text-center py-20 bg-[#121212]/30 border border-white/5 rounded-3xl px-4 min-h-[260px]">
                  <Loader2 className="w-10 h-10 text-blue-500 animate-spin mb-4" />
                  <p className="text-sm font-semibold text-white">Searching Marketplace...</p>
                  <p className="text-xs text-gray-500 mt-1 max-w-xs">Querying configured registries and external MCP sources.</p>
                </div>
              ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                  {displayedMarketItems.map((item) => {
                    const isInstallingThis = installingId === item.id;
                    const isThirdPartyOAuth =
                      item.install_type === "remote" ||
                      (item.source === "Smithery" && Boolean(item.deployment_url || item.is_remote || item.remote));

                    const docUrl =
                      item.url ||
                      item.homepage ||
                      (item.id?.startsWith("github:")
                        ? `https://github.com/${item.id.replace("github:", "")}`
                        : item.id?.startsWith("glama:")
                          ? `https://github.com/${item.id.replace("glama:", "")}`
                          : item.id?.startsWith("smithery:")
                            ? `https://smithery.ai/server/${item.id.replace("smithery:", "")}`
                            : item.qualified_name
                              ? (item.qualified_name.includes("/") && !item.qualified_name.startsWith("@")
                                ? `https://github.com/${item.qualified_name}`
                                : `https://smithery.ai/server/${item.qualified_name}`)
                              : item.name?.includes("/")
                                ? `https://github.com/${item.name}`
                                : undefined);

                    return (
                      <div
                        key={item.id}
                        className={`glass-card flex flex-col justify-between bg-[#141417]/90 border rounded-2xl p-5.5 backdrop-blur-md transition-all duration-200 shadow-xl group ${isThirdPartyOAuth
                          ? "border-sky-500/30 bg-gradient-to-br from-sky-500/5 via-[#141417] to-[#101012] hover:border-sky-400/70 shadow-sky-500/5 hover:shadow-sky-500/10"
                          : "border-purple-500/30 bg-gradient-to-br from-purple-500/5 via-[#141417] to-[#101012] hover:border-purple-400/70 shadow-purple-500/5 hover:shadow-purple-500/10"
                          }`}
                      >
                        {/* Top Section */}
                        <div className="space-y-3.5">
                          {/* Header: Icon + Title */}
                          <div className="flex items-start justify-between gap-3">
                            <div className="flex items-center gap-3 min-w-0">
                              {item.icon_url ? (
                                <img
                                  src={item.icon_url}
                                  alt={item.name}
                                  className="w-10 h-10 rounded-xl object-contain bg-white/5 p-1 border border-white/10 shrink-0"
                                  onError={(e) => {
                                    (e.target as HTMLElement).style.display = "none";
                                  }}
                                />
                              ) : (
                                <div
                                  className={`w-10 h-10 rounded-xl border flex items-center justify-center shrink-0 ${isThirdPartyOAuth
                                    ? "bg-sky-500/15 border-sky-500/30 text-sky-400"
                                    : "bg-purple-500/15 border-purple-500/30 text-purple-400"
                                    }`}
                                >
                                  {isThirdPartyOAuth ? <Globe className="w-5 h-5" /> : <Box className="w-5 h-5 text-purple-400" />}
                                </div>
                              )}
                              <div className="min-w-0">
                                {docUrl ? (
                                  <a
                                    href={docUrl}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    title={`Open repository or documentation (${docUrl})`}
                                    className={`group/link inline-flex items-center gap-1.5 text-white transition-colors max-w-full ${isThirdPartyOAuth ? "hover:text-sky-300" : "hover:text-purple-300"
                                      }`}
                                  >
                                    <h3 className="text-base font-bold truncate">{item.name}</h3>
                                    <ExternalLink className="w-3.5 h-3.5 opacity-60 group-hover/link:opacity-100 transition-opacity shrink-0 text-gray-400" />
                                  </a>
                                ) : (
                                  <h3 className="text-base font-bold truncate text-white">{item.name}</h3>
                                )}
                              </div>
                            </div>
                          </div>

                          {/* Description */}
                          <p className="text-xs text-gray-300/80 line-clamp-2 leading-relaxed min-h-[2.5rem]">
                            {item.description || "Compatible MCP server for executing contextual tools and prompts."}
                          </p>

                          {/* Center Installation Type Banner */}
                          {isThirdPartyOAuth ? (
                            <div className="flex items-center gap-3 px-3.5 py-2.5 rounded-xl bg-sky-500/10 border border-sky-500/20 text-sky-300">
                              <KeyRound className="w-4 h-4 text-sky-400 shrink-0" />
                              <div className="min-w-0">
                                <div className="text-xs font-bold text-sky-300 flex items-center gap-1.5">
                                  <span>Third-Party OAuth (Unverified)</span>
                                </div>
                                <div className="text-[11px] text-sky-400/80 truncate">
                                  Hosted proxy with unverified third-party OAuth login
                                </div>
                              </div>
                            </div>
                          ) : (
                            <div className="flex items-center gap-3 px-3.5 py-2.5 rounded-xl bg-purple-500/10 border border-purple-500/20 text-purple-300">
                              <Sparkles className="w-4 h-4 text-purple-400 shrink-0" />
                              <div className="min-w-0">
                                <div className="text-xs font-bold text-purple-300 flex items-center gap-1.5">
                                  <span>AI Analysis &amp; Key Setup</span>
                                </div>
                                <div className="text-[11px] text-purple-400/80 truncate">
                                  Automated key discovery &amp; environment configuration
                                </div>
                              </div>
                            </div>
                          )}
                        </div>

                        {/* Footer: Action Button */}
                        <div className="pt-3.5 mt-3.5 border-t border-white/10 flex items-center justify-end">
                          {isThirdPartyOAuth ? (
                            <button
                              type="button"
                              onClick={() => {
                                setZeroWizardTarget({
                                  id: item.id,
                                  qualified_name:
                                    item.qualified_name ||
                                    (item.id?.startsWith("smithery:")
                                      ? item.id.replace("smithery:", "")
                                      : item.id),
                                  display_name: item.name,
                                  description: item.description,
                                  icon_url: item.icon_url,
                                  runner: "node",
                                  package_url: item.deployment_url || item.url || item.qualified_name || item.name,
                                  source: item.source,
                                  url: item.url,
                                  is_remote: true,
                                  deployment_url: item.deployment_url || item.url,
                                  remote_url: item.deployment_url || item.url,
                                  install_type: "remote",
                                });
                                setZeroWizardOpen(true);
                              }}
                              disabled={installingId !== null || loading}
                              className="text-xs font-bold text-white bg-sky-600 hover:bg-sky-500 border border-sky-500/30 px-4 py-2 rounded-xl transition disabled:opacity-50 cursor-pointer shadow-md shadow-sky-600/20 flex items-center gap-1.5"
                            >
                              <Globe className="w-3.5 h-3.5" /> Install Remote
                            </button>
                          ) : (
                            <button
                              type="button"
                              onClick={() => {
                                setZeroWizardTarget({
                                  id: item.id,
                                  qualified_name:
                                    item.qualified_name ||
                                    (item.id?.startsWith("smithery:")
                                      ? item.id.replace("smithery:", "")
                                      : item.id),
                                  display_name: item.name,
                                  description: item.description,
                                  icon_url: item.icon_url,
                                  runner: item.runner || "npx",
                                  package_url: item.qualified_name || item.name,
                                  source: item.source,
                                  url: item.url,
                                  is_remote: item.remote || Boolean(item.deployment_url),
                                  deployment_url: item.deployment_url,
                                  remote_url: item.deployment_url,
                                  install_type: item.install_type,
                                });
                                setZeroWizardOpen(true);
                              }}
                              disabled={installingId !== null || loading}
                              className="text-xs font-bold text-white bg-purple-600 hover:bg-purple-500 border border-purple-500/30 px-4 py-2 rounded-xl transition disabled:opacity-50 cursor-pointer shadow-md shadow-purple-600/20 flex items-center gap-1.5"
                            >
                              <Sparkles className="w-3.5 h-3.5" /> Install MCP
                            </button>
                          )}
                        </div>
                      </div>
                    );
                  })}

                  {displayedMarketItems.length === 0 && (
                    <div className="col-span-full py-16 flex flex-col items-center justify-center text-center bg-[#121212]/30 border border-white/5 rounded-3xl px-4">
                      <Box className="w-10 h-10 text-gray-600 mb-2 animate-pulse" />
                      <p className="text-sm font-semibold text-gray-400">No modules found in this category</p>
                      <p className="text-xs text-gray-600 mt-1 max-w-xs">Use the search bar above to query global repositories.</p>
                    </div>
                  )}
                </div>
              )}
            </section>
          )}
        </div>
      )}

      {/* SlideOver Config Panel */}
      <SlideOver
        open={Boolean(editingConfig)}
        onClose={() => {
          setEditingConfig(null);
          setEditingPolicy(null);
        }}
        title={editingConfig?.name || "MCP Server Configuration"}
        subtitle="Runtime, user credentials, and environment parameters"
        icon={<Box className="w-5 h-5 text-blue-400" />}
        footer={
          <>
            <button
              type="button"
              onClick={() => {
                setEditingConfig(null);
                setEditingPolicy(null);
              }}
              className="px-5 py-2.5 bg-white/5 hover:bg-white/10 border border-white/10 rounded-xl text-sm font-semibold text-gray-300 transition cursor-pointer"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleSaveConfig}
              disabled={loading}
              className="px-6 py-2.5 bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white rounded-xl text-sm font-bold shadow-lg shadow-blue-500/20 transition cursor-pointer disabled:opacity-50"
            >
              {loading ? "Saving…" : "Save Configuration"}
            </button>
          </>
        }
      >
        {editingConfig && (
          <div className="space-y-5">
            {/* Top Navigation Tabs */}
            <div className="flex p-1 bg-black/40 rounded-2xl border border-white/10 gap-1">
              <button
                type="button"
                onClick={() => setConfigTab("runtime")}
                className={`flex-1 flex items-center justify-center gap-2 py-2.5 px-3 rounded-xl text-xs font-bold transition cursor-pointer ${configTab === "runtime"
                  ? "bg-blue-600 text-white shadow-md shadow-blue-600/20"
                  : "text-gray-400 hover:text-white hover:bg-white/5"
                  }`}
              >
                <Cpu className="w-4 h-4" />
                <span>1. Runtime & Connection</span>
              </button>
              <button
                type="button"
                onClick={() => setConfigTab("policy")}
                className={`flex-1 flex items-center justify-center gap-2 py-2.5 px-3 rounded-xl text-xs font-bold transition cursor-pointer ${configTab === "policy"
                  ? "bg-blue-600 text-white shadow-md shadow-blue-600/20"
                  : "text-gray-400 hover:text-white hover:bg-white/5"
                  }`}
              >
                <SlidersHorizontal className="w-4 h-4" />
                <span>2. Policy & Variables</span>
                {editingPolicy?.mode === "per_user" && (
                  <span className="text-[10px] px-2 py-0.5 rounded-full bg-purple-500/20 text-purple-300 border border-purple-500/30">
                    Per-User
                  </span>
                )}
                {editingPolicy?.mode === "org_shared" && (
                  <span className="text-[10px] px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">
                    Organization
                  </span>
                )}
              </button>
            </div>

            {/* TAB 1: RUNTIME & CONNECTION */}
            {configTab === "runtime" && (
              <div className="space-y-4">
                <div className="rounded-2xl border border-white/10 bg-[#161616] p-5 space-y-4 shadow-sm">
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    {/* Catalog Connector */}
                    <div className="space-y-1.5">
                      <label className="text-xs font-semibold text-gray-300 block">Catalog Connector</label>
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
                        className="w-full bg-black/50 border border-white/10 rounded-xl px-3.5 py-2.5 text-xs text-white focus:border-blue-500 outline-none cursor-pointer transition"
                      >
                        <option value="">— Auto-detect from name —</option>
                        {connectorRows.map((c: any) => (
                          <option key={c.id} value={c.id}>
                            {c.title || c.id}
                          </option>
                        ))}
                      </select>
                      {connectorFormContext.matched ? (
                        <p className="text-[11px] text-emerald-400 font-mono flex items-center gap-1 mt-1">
                          <CheckCircle2 className="w-3 h-3" /> Matched: {String((connectorFormContext.matched as { id?: string }).id)}
                        </p>
                      ) : null}
                    </div>

                    {/* Connection Type */}
                    <div className="space-y-1.5">
                      <label className="text-xs font-semibold text-gray-300 block">Connection Type</label>
                      <select
                        value={editingConfig.values.type ?? "stdio"}
                        onChange={(e) =>
                          setEditingConfig({
                            ...editingConfig,
                            values: {
                              ...editingConfig.values,
                              type: e.target.value,
                              ...(e.target.value === "sse" ? { command: undefined, args: undefined, rawArgsText: "" } : {}),
                            },
                          })
                        }
                        className="w-full bg-black/50 border border-white/10 rounded-xl px-3.5 py-2.5 text-xs text-white focus:border-blue-500 outline-none cursor-pointer transition"
                      >
                        <option value="stdio">Local (Stdio)</option>
                        <option value="sse">Remote (SSE)</option>
                        <option value="in_process">In-Process</option>
                      </select>
                    </div>
                  </div>

                  {/* SSE Endpoint */}
                  {editingConfig.values.type === "sse" ? (
                    <div className="space-y-1.5 pt-1">
                      <label className="text-xs font-semibold text-gray-300 block">Endpoint URL (SSE)</label>
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
                        className="w-full bg-black/50 border border-white/10 rounded-xl px-3.5 py-2.5 text-xs text-white font-mono focus:border-blue-500 outline-none transition"
                      />
                    </div>
                  ) : editingConfig.values.type !== "in_process" ? (
                    <>
                      {/* Command */}
                      <div className="space-y-1.5 pt-1">
                        <label className="text-xs font-semibold text-gray-300 block">Command</label>
                        <input
                          type="text"
                          value={editingConfig.values.command ?? ""}
                          onChange={(e) =>
                            setEditingConfig({
                              ...editingConfig,
                              values: { ...editingConfig.values, command: e.target.value },
                            })
                          }
                          placeholder="npx, python, node..."
                          className="w-full bg-black/50 border border-white/10 rounded-xl px-3.5 py-2.5 text-xs text-white font-mono focus:border-blue-500 outline-none transition"
                        />
                      </div>

                      {/* Arguments */}
                      <div className="space-y-1.5 pt-1">
                        <label className="text-xs font-semibold text-gray-300 block">
                          Arguments
                          <span className="ml-2 font-normal text-gray-500 text-[11px]">(one per line)</span>
                        </label>
                        <textarea
                          rows={Math.max(3, (editingConfig.values.rawArgsText ?? (editingConfig.values.args || []).join("\n")).split("\n").length + 1)}
                          value={editingConfig.values.rawArgsText ?? (editingConfig.values.args || []).join("\n")}
                          onChange={(e) => {
                            const rawArgsText = e.target.value;
                            const args = rawArgsText
                              .split("\n")
                              .map((line) => line.trim())
                              .filter((line) => line.length > 0);
                            setEditingConfig({ ...editingConfig, values: { ...editingConfig.values, rawArgsText, args } });
                          }}
                          placeholder={"mcp-server\n--port\n8080"}
                          className="w-full bg-black/50 border border-white/10 rounded-xl p-3 text-xs text-white font-mono focus:border-blue-500 outline-none resize-y min-h-[80px] transition"
                        />
                      </div>
                    </>
                  ) : null}

                  {/* Description */}
                  <div className="space-y-1.5 pt-1">
                    <label className="text-xs font-semibold text-gray-300 block">Description</label>
                    <textarea
                      value={editingConfig.values.description || ""}
                      onChange={(e) => setEditingConfig({ ...editingConfig, values: { ...editingConfig.values, description: e.target.value } })}
                      placeholder="Optional description for the MCP server..."
                      className="w-full bg-black/50 border border-white/10 rounded-xl p-3 text-xs text-white focus:border-blue-500 outline-none min-h-[70px] resize-y transition"
                    />
                  </div>
                </div>
              </div>
            )}

            {/* TAB 2: POLICY & VARIABLES */}
            {configTab === "policy" && editingPolicy && (
              <div className="space-y-4">
                <div className="rounded-2xl border border-white/10 bg-[#161616] p-5 space-y-5 shadow-sm">
                  {/* Scope Selector */}
                  <div className="space-y-2">
                    <span className="text-xs font-semibold text-gray-300 block">
                      Policy Scope & Credential Mode
                    </span>
                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5">
                      {[
                        {
                          mode: "none" as CredentialMode,
                          title: "None",
                          desc: "No variables or login required",
                          icon: Shield,
                        },
                        {
                          mode: "org_shared" as CredentialMode,
                          title: "Organization",
                          desc: "Global configuration defined by admin",
                          icon: ShieldCheck,
                        },
                        {
                          mode: "per_user" as CredentialMode,
                          title: "Per-User",
                          desc: "Different credentials per user",
                          icon: Users,
                        },
                      ].map((item) => {
                        const isSelected = editingPolicy.mode === item.mode;
                        const IconComp = item.icon;
                        return (
                          <button
                            key={item.mode}
                            type="button"
                            onClick={() => {
                              setEditingPolicy({ ...editingPolicy, mode: item.mode });
                              if (editingConfig) void loadPolicyPreview(editingConfig.name, item.mode);
                              if (item.mode === "none" && editingConfig?.values?.args) {
                                const args = editingConfig.values.args;
                                const cleaned: string[] = [];
                                let skipNext = false;
                                for (const arg of args) {
                                  if (skipNext) {
                                    skipNext = false;
                                    continue;
                                  }
                                  if (arg === "--header") {
                                    skipNext = true;
                                    continue;
                                  }
                                  cleaned.push(arg);
                                }
                                if (cleaned.length !== args.length) {
                                  setEditingConfig({
                                    ...editingConfig,
                                    values: { ...editingConfig.values, args: cleaned },
                                  });
                                }
                              }
                            }}
                            className={`p-3.5 rounded-2xl border text-left flex flex-col justify-between gap-1.5 transition cursor-pointer ${isSelected
                              ? "border-blue-500 bg-blue-500/15 text-white ring-1 ring-blue-500"
                              : "border-white/10 bg-black/40 text-gray-400 hover:text-white hover:border-white/20"
                              }`}
                          >
                            <div className="flex items-center justify-between">
                              <span className="font-bold text-xs flex items-center gap-1.5 text-white">
                                <IconComp className="w-3.5 h-3.5 text-blue-400" />
                                {item.title}
                              </span>
                              {isSelected && <span className="w-2 h-2 rounded-full bg-blue-400" />}
                            </div>
                            <span className="text-[11px] text-gray-400 leading-tight">
                              {item.desc}
                            </span>
                          </button>
                        );
                      })}
                    </div>
                  </div>

                  {/* Enable in Chat UI Checkbox */}
                  <label className="flex items-center gap-3 cursor-pointer bg-black/40 p-3.5 rounded-2xl border border-white/10 hover:border-white/20 transition">
                    <input
                      type="checkbox"
                      checked={editingPolicy.enabled}
                      onChange={(e) => setEditingPolicy({ ...editingPolicy, enabled: e.target.checked })}
                      className="rounded border-white/20 text-blue-500 focus:ring-0 w-4 h-4 cursor-pointer"
                    />
                    <div>
                      <span className="text-xs font-semibold text-gray-200 block">
                        Enable integration in Chat UI for users
                      </span>
                      <span className="text-[11px] text-gray-400 block">
                        Allows chat users to view and use this MCP server
                      </span>
                    </div>
                  </label>

                  {editingPolicy.warnings.map((w) => (
                    <p key={w} className="flex gap-2 rounded-2xl border border-amber-500/25 bg-amber-500/10 px-3.5 py-2.5 text-xs text-amber-200">
                      <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
                      <span>{w}</span>
                    </p>
                  ))}

                  {/* SUB-SECTION 1: NO POLICY */}
                  {editingPolicy.mode === "none" && (
                    <div className="rounded-2xl border border-white/5 bg-black/20 p-5 text-center text-xs text-gray-400">
                      <Shield className="w-6 h-6 text-gray-500 mx-auto mb-2" />
                      <p className="font-semibold text-gray-200">No variables or credentials required</p>
                      <p className="text-[11px] text-gray-500 mt-1 max-w-md mx-auto">
                        The MCP server runs with system runtime parameters without requiring environment variables or individual logins.
                      </p>
                    </div>
                  )}

                  {/* SUB-SECTION 2: ORGANIZATION (Environment variables configured by admin for everyone) */}
                  {editingPolicy.mode === "org_shared" && (
                    <div className="space-y-3 pt-3 border-t border-white/5">
                      <KeyValueBuilder
                        env={editingConfig.values.env || {}}
                        onChange={(nextEnv) => {
                          setEditingConfig({
                            ...editingConfig,
                            values: {
                              ...editingConfig.values,
                              env: nextEnv,
                              rawAllEnvText: JSON.stringify(nextEnv, null, 2),
                            },
                          });
                        }}
                        disabled={loading}
                      />
                    </div>
                  )}

                  {/* SUB-SECTION 3: PER USER (Credential schema filled by each user in chat) */}
                  {editingPolicy.mode === "per_user" && (
                    <div className="space-y-4 pt-3 border-t border-white/5">
                      <CredentialSchemaEditor
                        value={editingPolicy.credentialSchema}
                        onChange={(credentialSchema) =>
                          setEditingPolicy({ ...editingPolicy, credentialSchema })
                        }
                      />
                      <div className="flex flex-wrap items-center gap-3 pt-1">
                        {editingPolicy.previewSchema.length > 0 && (
                          <button
                            type="button"
                            onClick={() =>
                              setEditingPolicy({
                                ...editingPolicy,
                                credentialSchema: editingPolicy.previewSchema,
                              })
                            }
                            className="text-xs text-blue-400 hover:underline cursor-pointer font-semibold"
                          >
                            Import fields from auto-preview ({editingPolicy.previewSchema.length})
                          </button>
                        )}
                        <button
                          type="button"
                          onClick={() => void applySuggestedEnv()}
                          disabled={loading}
                          className="text-xs font-bold text-indigo-300 hover:underline cursor-pointer"
                        >
                          Apply suggested env to registry
                        </button>
                      </div>

                      <McpEnvYamlPanel
                        yaml={
                          integrationBySlug[editingConfig.name]?.suggested_env_yaml ||
                          (editingPolicy.credentialSchema.length > 0
                            ? `env:\n${editingPolicy.credentialSchema
                              .filter((f) => f.env_placeholder)
                              .map((f) => `  ${f.registry_env_key || f.key}: "${f.env_placeholder}"`)
                              .join("\n")}`
                            : "")
                        }
                      />

                      {(editingConfig?.values?.type === "remote-bridge" ||
                        oauthConfig.authorization_server ||
                        connectorFormContext.matched) && (
                          <McpOAuthAdminSetupPanel
                            connector={connectorFormContext.matched}
                            oauthConfig={oauthConfig}
                            onChange={(patch) => setOauthConfig((prev) => ({ ...prev, ...patch }))}
                          />
                        )}
                    </div>
                  )}

                  <label className="flex cursor-pointer items-center gap-2.5 text-xs text-gray-400 pt-1">
                    <input
                      type="checkbox"
                      checked={userMayDisable}
                      onChange={(e) => setUserMayDisable(e.target.checked)}
                      className="rounded border-white/20 text-blue-500 w-3.5 h-3.5 cursor-pointer"
                    />
                    Users may disable this integration from their chat profile
                  </label>
                </div>
              </div>
            )}
          </div>
        )}
      </SlideOver>

      {/* Delete Confirmation Modal */}
      {isDeleteModalOpen && mcpToDelete && (
        <div className="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 flex items-center justify-center p-4 animate-in fade-in duration-200">
          <div className="glass-card bg-[#1a1a1a] border border-white/10 rounded-3xl w-full max-w-lg overflow-hidden shadow-2xl animate-in zoom-in-95 duration-200">
            <div className="p-6 border-b border-white/10 flex justify-between items-center bg-white/5">
              <h2 className="text-xl font-bold text-white flex items-center gap-2">
                <Trash2 className="w-5 h-5 text-red-400" />
                Confirm Removal
              </h2>
              <button
                onClick={() => setIsDeleteModalOpen(false)}
                className="text-gray-500 hover:text-white transition-colors cursor-pointer"
              >
                <X className="w-6 h-6" />
              </button>
            </div>

            <div className="p-6 space-y-4">
              <div className="p-4 bg-red-500/10 border border-red-500/20 rounded-2xl text-red-300 text-sm leading-relaxed">
                <p className="font-semibold mb-1 text-lg flex items-center gap-2">
                  <AlertTriangle className="w-5 h-5 text-red-400 shrink-0" />
                  <span className="text-white font-bold">WARNING: Irreversible action</span>
                </p>
                You are about to remove the MCP module <b className="text-white font-mono">{mcpToDelete}</b> from the system. Agent profiles and users using it will no longer be able to access these tools.
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
                className="bg-red-600 hover:bg-red-500 text-white px-6 py-2.5 rounded-xl text-sm font-bold transition-all flex items-center gap-2 disabled:opacity-40 shadow-lg shadow-red-600/20 cursor-pointer"
              >
                <Trash2 className="w-4 h-4" />
                {loading ? "Removing…" : "Remove MCP"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Blocked Deletion Modal */}
      {isBlockedModalOpen && mcpToDelete && (
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
                className="text-gray-500 hover:text-white transition-colors cursor-pointer"
              >
                <X className="w-6 h-6" />
              </button>
            </div>

            <div className="p-6 space-y-4">
              <div className="p-4 bg-amber-500/10 border border-amber-500/20 rounded-2xl text-amber-300 text-sm leading-relaxed">
                <p className="font-semibold mb-1 text-lg flex items-center gap-2">
                  <span className="text-white font-bold">Module in Use</span>
                </p>
                The MCP module <b className="text-white font-mono">{mcpToDelete}</b> cannot be deleted because it is currently assigned to the following agent profiles:
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
                Remove this module from the listed profiles before uninstalling.
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
      )}

      {/* Advisory Modal */}
      {adviseOpen && (
        <div className="fixed inset-0 z-[60] bg-black/70 flex items-center justify-center p-4">
          <div className="bg-[#1a1a1a] border border-white/10 rounded-2xl max-w-lg w-full p-6 space-y-4">
            <h3 className="text-lg font-bold text-white flex items-center gap-2">
              <MessageSquare className="w-5 h-5 text-sky-400" />
              MCP Integration Advisory
            </h3>
            {adviseLoading ? (
              <p className="text-sm text-gray-400">Analysis in progress…</p>
            ) : (
              <pre className="text-xs text-gray-300 whitespace-pre-wrap max-h-96 overflow-y-auto font-mono bg-black/40 p-4 rounded-xl border border-white/5">
                {adviseResult?.steps_markdown || "No suggestions available."}
              </pre>
            )}
            <div className="flex justify-end">
              <button
                type="button"
                onClick={() => setAdviseOpen(false)}
                className="px-4 py-2 bg-white/10 hover:bg-white/15 text-white text-xs font-bold rounded-xl cursor-pointer"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Dynamic Zero-Install Wizard Modal */}
      <DynamicWizardModal
        open={zeroWizardOpen}
        target={zeroWizardTarget}
        onClose={() => {
          setZeroWizardOpen(false);
          setZeroWizardTarget(null);
        }}
        onInstalled={(serverSlug) => {
          fetchRegistry();
          void fetchIntegrations();
          void fetchIntegrity();
          setActiveTab("installed");
          setToast({
            message: `MCP server '${serverSlug}' configured and enabled (Zero-Install).`,
            variant: "success",
          });
        }}
      />

      {/* Mcp Tools Manage Modal */}
      <McpToolsManageModal
        serverSlug={manageToolsSlug}
        open={Boolean(manageToolsSlug)}
        onClose={() => setManageToolsSlug(null)}
        onSaved={() => {
          fetchRegistry();
          void fetchIntegrations();
          void fetchIntegrity();
        }}
      />

      <PageToast toast={toast} onDismiss={() => setToast(null)} />
    </div>
  );
}
