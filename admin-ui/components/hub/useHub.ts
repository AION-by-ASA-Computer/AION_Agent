"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { apiFetch } from "@/lib/api/headers";
import { apiBase } from "@/lib/api";
import { useT } from "@/lib/i18n/use-t";
import type { ToastState } from "@/components/PageToast";
import { buildCredentialFields, matchConnectorRow } from "@/lib/mcpConnectorUi";
import {
  normalizeCredentialSchema,
  type CredentialMode,
  type CredentialSchemaField,
  type IntegrationPolicyRow,
} from "@/lib/mcpIntegrationPolicy";
import { connectorOAuthSetupHints } from "@/lib/mcpOAuthSetup";
import { categorizeMcp, type McpCategory } from "@/lib/mcpCategories";
import type { McpIntegrityIssue } from "@/components/McpIntegrityBanner";
import type { McpItemRow } from "@/components/hub/ServerList";
import type { RemoteCatalogPreset } from "@/components/RemoteMcpInstallModal";
import type { DynamicWizardTarget } from "@/components/DynamicWizardModal";
import { oauthAdminSetupPending } from "@/lib/mcpOAuthSetup";

/* eslint-disable @typescript-eslint/no-explicit-any */

export type HubTab = "installed" | "catalog";
export type StatusFilter = "all" | "attention" | "disabled";

export type OAuthConfig = {
  provider: string;
  authorization_server: string;
  token_url: string;
  client_id: string;
  client_secret: string;
  scopes: string[];
  client_id_source?: string;
  /** The backend never returns the secret: this says one is stored. */
  client_secret_set?: boolean;
};

/** Order-insensitive fingerprint of the fields that get persisted. */
export function schemaSig(fields: CredentialSchemaField[]): string {
  return JSON.stringify(
    fields.map((f) => [f.key, f.label, f.type, f.required, f.description ?? ""]).sort((a, b) => String(a[0]).localeCompare(String(b[0]))),
  );
}

export type EditingPolicy = {
  enabled: boolean;
  mode: CredentialMode;
  warnings: string[];
  previewSchema: CredentialSchemaField[];
  credentialSchema: CredentialSchemaField[];
  /** Signature of the schema as last saved, to tell whether the form has unsaved schema edits. */
  savedSig: string;
};

const EMPTY_OAUTH: OAuthConfig = {
  provider: "generic",
  authorization_server: "",
  token_url: "",
  client_id: "",
  client_secret: "",
  scopes: [],
};

export type ServerStatus = "attention" | "oauth" | "system" | "disabled" | "active";

/** One status per server, worst first. The same rule drives the badge, the filters and the sort. */
export function serverStatus(row: McpItemRow): ServerStatus {
  if ((row.issues?.length ?? 0) > 0) return "attention";
  if (oauthAdminSetupPending(row.policy?.oauth_config, row.connector, row.config)) return "oauth";
  if (row.config.is_base) return "system";
  if (row.policy?.is_enabled_for_users === false) return "disabled";
  return "active";
}

export const STATUS_RANK: Record<ServerStatus, number> = { attention: 0, oauth: 1, disabled: 2, active: 3, system: 4 };

export function useHub() {
  const t = useT();
  const k = "admin_hub";

  const [tab, setTab] = useState<HubTab>("installed");
  const [toast, setToast] = useState<ToastState>(null);
  const [busy, setBusy] = useState(false);

  // ── installed
  const [installed, setInstalled] = useState<Record<string, any>>({});
  const [installedLoaded, setInstalledLoaded] = useState(false);
  const [integrationBySlug, setIntegrationBySlug] = useState<Record<string, IntegrationPolicyRow>>({});
  const [integrityIssues, setIntegrityIssues] = useState<McpIntegrityIssue[]>([]);
  const [connectorRows, setConnectorRows] = useState<any[]>([]);
  const [sandboxBackend, setSandboxBackend] = useState("subprocess");
  const [query, setQuery] = useState("");
  const [runtimeFilter, setRuntimeFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [probingSlug, setProbingSlug] = useState<string | null>(null);

  // ── catalog
  const [marketItems, setMarketItems] = useState<any[]>([]);
  const [marketLoading, setMarketLoading] = useState(false);
  const [marketQuery, setMarketQuery] = useState("");
  const [marketSource, setMarketSource] = useState("all");
  const [marketCategory, setMarketCategory] = useState<McpCategory>("all");
  const [installingId, setInstallingId] = useState<string | null>(null);

  // ── dialogs
  const [githubOpen, setGithubOpen] = useState(false);
  const [githubUrl, setGithubUrl] = useState("");
  const [githubName, setGithubName] = useState("");
  const [analyzingGithub, setAnalyzingGithub] = useState(false);
  const [wizardOpen, setWizardOpen] = useState(false);
  const [wizardTarget, setWizardTarget] = useState<DynamicWizardTarget | null>(null);
  const [manageToolsSlug, setManageToolsSlug] = useState<string | null>(null);
  const [remoteOpen, setRemoteOpen] = useState(false);
  const [remoteSeed, setRemoteSeed] = useState<{ url?: string; displayName?: string; connectorId?: string }>({});
  const [deleteSlug, setDeleteSlug] = useState<string | null>(null);
  const [blockedBy, setBlockedBy] = useState<{ slug: string; profiles: string[] } | null>(null);

  // ── config dialog
  const [editing, setEditing] = useState<any>(null);
  const [editingPolicy, setEditingPolicy] = useState<EditingPolicy | null>(null);
  const [userMayDisable, setUserMayDisable] = useState(true);
  const [oauthConfig, setOauthConfig] = useState<OAuthConfig>(EMPTY_OAUTH);
  const [adviseOpen, setAdviseOpen] = useState(false);
  const [adviseLoading, setAdviseLoading] = useState(false);
  const [adviseResult, setAdviseResult] = useState<string | null>(null);

  const errText = (e: unknown) => (e instanceof Error ? e.message : String(e));

  // ───────── loaders
  const fetchRegistry = useCallback(async () => {
    try {
      const res = await apiFetch(`${apiBase()}/admin/registry`);
      if (!res.ok) throw new Error(String(res.status));
      setInstalled(await res.json());
    } catch (e) {
      console.error(e);
    } finally {
      setInstalledLoaded(true);
    }
  }, []);

  const fetchIntegrations = useCallback(async () => {
    try {
      const res = await apiFetch(`${apiBase()}/admin/mcp-integrations`);
      if (!res.ok) return null;
      const data = await res.json();
      const map: Record<string, IntegrationPolicyRow> = {};
      for (const row of (data.integrations || []) as IntegrationPolicyRow[]) map[row.server_slug] = row;
      setIntegrationBySlug(map);
      return map;
    } catch (e) {
      console.error(e);
      return null;
    }
  }, []);

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

  const fetchSettings = useCallback(async () => {
    try {
      const res = await apiFetch(`${apiBase()}/admin/settings`);
      if (!res.ok) return;
      const data = await res.json();
      const backend = (data.settings?.AION_SANDBOX_BACKEND || "subprocess").trim().toLowerCase();
      setSandboxBackend(backend === "container" ? "container" : "subprocess");
    } catch (e) {
      console.error(e);
    }
  }, []);

  const ensureConnectorCatalog = useCallback(async () => {
    if (connectorRows.length > 0) return;
    try {
      const res = await apiFetch(`${apiBase()}/admin/mcp/connector-catalog`);
      if (!res.ok) return;
      const data = await res.json();
      setConnectorRows(Array.isArray(data.connectors) ? data.connectors : []);
    } catch (e) {
      console.error(e);
    }
  }, [connectorRows.length]);

  const refreshAll = useCallback(() => {
    void fetchRegistry();
    void fetchIntegrations();
    void fetchIntegrity();
  }, [fetchRegistry, fetchIntegrations, fetchIntegrity]);

  useEffect(() => {
    void fetchRegistry();
    void fetchSettings();
    void fetchIntegrations();
    void fetchIntegrity();
    void ensureConnectorCatalog();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const runMarketSearch = useCallback(
    async (raw: string) => {
      const q = raw.trim();
      setMarketLoading(true);
      try {
        const res = await apiFetch(`${apiBase()}/admin/market/search?q=${encodeURIComponent(q)}`);
        if (!res.ok) throw new Error(String(res.status));
        const data = await res.json();
        setMarketItems(data.filter((item: any) => item.source !== "Official Registry"));
      } catch (e) {
        setToast({ message: t(`${k}.toast.search_failed`, { error: errText(e) }), variant: "error" });
      } finally {
        setMarketLoading(false);
      }
    },
    [t],
  );

  // Opening the catalog loads the featured list once, without waiting for a search.
  useEffect(() => {
    if (tab !== "catalog") return;
    void ensureConnectorCatalog();
    if (marketItems.length === 0) void runMarketSearch("");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab]);

  // ───────── derived
  const rows: McpItemRow[] = useMemo(
    () =>
      Object.entries(installed).map(([name, config]) => ({
        name,
        config,
        policy: integrationBySlug[name],
        connector: matchConnectorRow(
          name,
          config.aion_connector_id || integrationBySlug[name]?.aion_connector_id || undefined,
          connectorRows as Record<string, unknown>[],
        ),
        issues: integrityIssues.filter((i) => i.server_slug === name || i.from_slug === name),
      })),
    [installed, integrationBySlug, connectorRows, integrityIssues],
  );

  const counts = useMemo(() => {
    let attention = 0;
    let disabled = 0;
    for (const r of rows) {
      const s = serverStatus(r);
      if (s === "attention" || s === "oauth") attention++;
      if (s === "disabled") disabled++;
    }
    return { all: rows.length, attention, disabled };
  }, [rows]);

  const visibleRows = useMemo(() => {
    const q = query.trim().toLowerCase();
    return rows
      .filter((r) => {
        const s = serverStatus(r);
        if (statusFilter === "attention" && s !== "attention" && s !== "oauth") return false;
        if (statusFilter === "disabled" && s !== "disabled") return false;
        if (q) {
          const hay = `${r.name} ${r.config.description ?? ""} ${r.policy?.display_name ?? ""} ${r.config.aion_connector_id ?? ""}`.toLowerCase();
          if (!hay.includes(q)) return false;
        }
        const c = r.config;
        switch (runtimeFilter) {
          case "built_in":
            return !!c.is_base;
          case "stdio":
            return !c.is_base && (c.type === "stdio" || !c.type);
          case "sse":
          case "remote-bridge":
          case "in_process":
            return !c.is_base && c.type === runtimeFilter;
          default:
            return true;
        }
      })
      .sort((a, b) => STATUS_RANK[serverStatus(a)] - STATUS_RANK[serverStatus(b)] || a.name.localeCompare(b.name));
  }, [rows, query, runtimeFilter, statusFilter]);

  const featured = useMemo(
    () =>
      (connectorRows as RemoteCatalogPreset[]).filter(
        (c) =>
          (c.featured_remote && c.install_type === "remote" && Boolean(c.remote_url)) ||
          (c.install_type === "stdio" && c.featured_catalog),
      ),
    [connectorRows],
  );

  const featuredShown = useMemo(() => {
    const q = marketQuery.trim().toLowerCase();
    return featured.filter((c: any) => {
      if (marketCategory !== "all" && marketCategory !== "official" && categorizeMcp(c) !== marketCategory) return false;
      if (!q) return true;
      return `${c.title ?? ""} ${c.id ?? ""} ${c.description ?? ""}`.toLowerCase().includes(q);
    });
  }, [featured, marketCategory, marketQuery]);

  const communityShown = useMemo(() => {
    if (marketCategory === "official") return [];
    return marketItems.filter((item) => {
      if (marketSource !== "all" && item.source !== marketSource) return false;
      if (marketCategory !== "all" && categorizeMcp(item) !== marketCategory) return false;
      return true;
    });
  }, [marketItems, marketSource, marketCategory]);

  const formContext = useMemo(() => {
    if (!editing) return { matched: null as Record<string, unknown> | null, fields: [] as ReturnType<typeof buildCredentialFields>, knownKeys: new Set<string>() };
    const matched = matchConnectorRow(
      editing.name,
      editing.values?.aion_connector_id as string | undefined,
      connectorRows as Record<string, unknown>[],
    );
    const fields = buildCredentialFields(matched);
    return { matched, fields, knownKeys: new Set(fields.map((f) => f.key)) };
  }, [editing, connectorRows]);

  // ───────── config dialog
  const loadPolicyPreview = useCallback(
    async (slug: string, mode?: CredentialMode) => {
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
          credentialSchema: prev?.credentialSchema && prev.credentialSchema.length > 0 ? prev.credentialSchema : preview,
          savedSig: prev?.savedSig ?? schemaSig([]),
        }));
        if (data.discovery?.remote_auth_type === "oauth2") {
          setOauthConfig((prev) =>
            prev.authorization_server && prev.client_id
              ? prev
              : {
                  provider: prev.provider || data.discovery.remote_oauth_provider || "generic",
                  authorization_server: prev.authorization_server || data.discovery.remote_oauth_server || "",
                  token_url: prev.token_url || data.discovery.remote_oauth_token_url || "",
                  client_id: prev.client_id || "",
                  client_secret: prev.client_secret || "",
                  scopes: prev.scopes?.length ? prev.scopes : [],
                  client_id_source: prev.client_id_source,
                  client_secret_set: prev.client_secret_set,
                },
          );
        }
      } catch (e) {
        console.error(e);
      }
    },
    [integrationBySlug],
  );

  const openConfig = useCallback(
    async (name: string, config: Record<string, unknown>) => {
      void ensureConnectorCatalog();
      const map = await fetchIntegrations();
      const policy = (map ?? integrationBySlug)[name];
      const args = Array.isArray(config.args) ? config.args : [];
      const env =
        config.env && typeof config.env === "object" && !Array.isArray(config.env) ? { ...(config.env as object) } : {};
      setUserMayDisable(policy?.user_may_disable !== false);
      setEditing({
        name,
        values: { ...config, rawArgsText: args.join("\n"), rawAllEnvText: JSON.stringify(env, null, 2), env },
      });
      const schema = normalizeCredentialSchema(policy?.credential_schema);
      setEditingPolicy({
        enabled: policy?.is_enabled_for_users ?? false,
        mode: policy?.credential_mode ?? "none",
        warnings: [],
        previewSchema: schema,
        credentialSchema: schema,
        savedSig: schemaSig(schema),
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
        client_secret_set: Boolean(oauth.client_secret_set),
      });
      void loadPolicyPreview(name, policy?.credential_mode);
    },
    [ensureConnectorCatalog, fetchIntegrations, integrationBySlug, loadPolicyPreview],
  );

  const closeConfig = useCallback(() => {
    setEditing(null);
    setEditingPolicy(null);
    setAdviseOpen(false);
    setAdviseResult(null);
  }, []);

  const savePolicy = async (slug: string) => {
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
      if (body.schema_override) body.apply_suggested_env = true;
    }
    if (oauthConfig.authorization_server || oauthConfig.client_id) {
      const matched = matchConnectorRow(
        slug,
        editing?.values?.aion_connector_id as string | undefined,
        connectorRows as Record<string, unknown>[],
      );
      const hints = connectorOAuthSetupHints(matched);
      const catalogOauth = (matched?.oauth || {}) as Record<string, string>;
      body.oauth_config = {
        provider: oauthConfig.provider || "generic",
        authorization_server: oauthConfig.authorization_server || catalogOauth.authorization_server || "",
        token_url: oauthConfig.token_url || catalogOauth.token_url || "",
        client_id: oauthConfig.client_id,
        client_secret: oauthConfig.client_secret,
        scopes: oauthConfig.scopes?.length ? oauthConfig.scopes : hints.scopes,
      };
    } else {
      body.oauth_config = {};
    }
    const json = { "Content-Type": "application/json" };
    const res = existing
      ? await apiFetch(`${apiBase()}/admin/mcp-integrations/${encodeURIComponent(slug)}`, {
          method: "PATCH",
          headers: json,
          body: JSON.stringify(body),
        })
      : await apiFetch(`${apiBase()}/admin/mcp-integrations`, {
          method: "POST",
          headers: json,
          body: JSON.stringify({
            server_slug: slug,
            display_name: slug.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()),
            ...body,
          }),
        });
    if (!res.ok) throw new Error(await res.text());
  };

  const saveConfig = async () => {
    if (!editing) return;
    setBusy(true);
    try {
      const v = editing.values;
      const rawArgs = typeof v.rawArgsText === "string" ? v.rawArgsText : Array.isArray(v.args) ? v.args.join("\n") : "";
      const payload: Record<string, unknown> = {
        command: typeof v.command === "string" ? v.command : "python",
        args: rawArgs
          .split("\n")
          .map((l: string) => l.trim())
          .filter(Boolean),
        env: v.env && typeof v.env === "object" && !Array.isArray(v.env) ? { ...v.env } : {},
        description: typeof v.description === "string" ? v.description : "",
      };
      if (typeof v.type === "string") payload.type = v.type;
      if (typeof v.url === "string") payload.url = v.url;
      if (typeof v.remote_url === "string") payload.remote_url = v.remote_url;
      if (v.security && typeof v.security === "object" && !Array.isArray(v.security)) payload.security = { ...v.security };
      if (typeof v.aion_connector_id === "string" && v.aion_connector_id.trim()) {
        payload.aion_connector_id = v.aion_connector_id.trim();
      }
      // savePolicy runs after the PUT: send the new mode so the backend does not
      // strip the auth header using the mode still stored in the DB.
      if (editingPolicy) payload.credential_mode = editingPolicy.mode;
      const res = await apiFetch(`${apiBase()}/admin/mcp/${editing.name}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error(String(res.status));
      if (editingPolicy) await savePolicy(editing.name);
      refreshAll();
      const name = editing.name;
      closeConfig();
      setToast({ message: t(`${k}.toast.saved`, { name }), variant: "success" });
    } catch (e) {
      setToast({ message: t(`${k}.toast.save_failed`, { error: errText(e) }), variant: "error" });
    } finally {
      setBusy(false);
    }
  };

  const applySuggestedEnv = async () => {
    if (!editing || !editingPolicy) return;
    if (editingPolicy.mode !== "per_user" && editingPolicy.mode !== "org_shared") return;
    setBusy(true);
    try {
      const res = await apiFetch(
        `${apiBase()}/admin/mcp-integrations/${encodeURIComponent(editing.name)}/apply-suggested-env?credential_mode=${editingPolicy.mode}`,
        { method: "POST" },
      );
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      const env = data.env || editing.values.env || {};
      setEditing({ ...editing, values: { ...editing.values, env, rawAllEnvText: JSON.stringify(env, null, 2) } });
      setToast({ message: t(`${k}.toast.env_applied`), variant: "success" });
      void loadPolicyPreview(editing.name, editingPolicy.mode);
      void fetchRegistry();
    } catch (e) {
      setToast({ message: t(`${k}.toast.env_failed`, { error: errText(e) }), variant: "error" });
    } finally {
      setBusy(false);
    }
  };

  const runAdvise = async (slug: string) => {
    setAdviseLoading(true);
    setAdviseOpen(true);
    setAdviseResult(null);
    try {
      const res = await apiFetch(`${apiBase()}/admin/mcp-integrations/advise`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ server_slug: slug }),
      });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      setAdviseResult(data.steps_markdown || "");
    } catch (e) {
      setAdviseResult(errText(e));
    } finally {
      setAdviseLoading(false);
    }
  };

  // ───────── server actions
  const probe = async (name: string) => {
    setProbingSlug(name);
    setToast({ message: t(`${k}.toast.probing`, { name }), variant: "loading" });
    try {
      const res = await apiFetch(`${apiBase()}/admin/mcp/${encodeURIComponent(name)}/probe`, { method: "POST" });
      const data = await res.json();
      if (!res.ok || !data.ok) {
        const known = ["timeout", "executable_missing", "auth_failed", "process_crashed", "empty_tools"];
        const prefix = t(`${k}.probe.${known.includes(data.error_type) ? data.error_type : "failed"}`);
        const msg = data.error || `HTTP ${res.status}`;
        setToast({ message: `${prefix}: ${msg}${data.hint ? ` — ${data.hint}` : ""}`, variant: "error" });
        return;
      }
      if (data.note) {
        setToast({ message: t(`${k}.toast.probe_note`, { note: data.note }), variant: "success" });
        return;
      }
      const names = (data.tools || []).map((x: { name?: string }) => x.name).filter(Boolean);
      const count = data.tool_count ?? names.length;
      setToast({
        message: t(`${k}.toast.probe_ok`, { count, tools: names.slice(0, 8).join(", ") }),
        variant: "success",
      });
    } catch (e) {
      setToast({ message: t(`${k}.toast.probe_error`, { error: errText(e) }), variant: "error" });
    } finally {
      setProbingSlug(null);
    }
  };

  /** Deleting is refused while a profile still lists the server. */
  const startDelete = async (name: string) => {
    setBusy(true);
    try {
      const res = await apiFetch(`${apiBase()}/admin/profiles`);
      if (!res.ok) throw new Error(String(res.status));
      const profiles = await res.json();
      const using = profiles.filter((p: any) => p.mcp_servers?.includes(name)).map((p: any) => p.name);
      if (using.length > 0) setBlockedBy({ slug: name, profiles: using });
      else setDeleteSlug(name);
    } catch (e) {
      setToast({ message: t(`${k}.toast.profiles_failed`, { error: errText(e) }), variant: "error" });
    } finally {
      setBusy(false);
    }
  };

  const confirmDelete = async () => {
    if (!deleteSlug) return;
    setBusy(true);
    try {
      const res = await apiFetch(`${apiBase()}/admin/mcp/${deleteSlug}`, { method: "DELETE" });
      if (!res.ok) throw new Error(String(res.status));
      refreshAll();
      setToast({ message: t(`${k}.toast.removed`, { name: deleteSlug }), variant: "success" });
      setDeleteSlug(null);
    } catch (e) {
      setToast({ message: t(`${k}.toast.remove_failed`, { error: errText(e) }), variant: "error" });
    } finally {
      setBusy(false);
    }
  };

  const openWizardFor = (name: string) => {
    const cfg = installed[name];
    const runner = cfg?.command === "uvx" ? "uvx" : "npx";
    const pkg = cfg?.zero_package || (cfg?.args?.length ? cfg.args[cfg.args.length - 1] : name);
    const required_envs = Object.entries(cfg?.env || {}).map(([key, v]) => {
      const s = String(v || "");
      const secret = s.startsWith("${") && s.endsWith("}");
      return { key, is_secret: secret, default: secret ? "" : s };
    });
    setWizardTarget({
      id: name,
      qualified_name: name,
      display_name: name,
      description: cfg?.description || "",
      runner,
      package_url: pkg,
      required_envs,
    });
    setWizardOpen(true);
  };

  const openAdvisorFor = (name: string) => {
    const cfg = installed[name];
    if (!cfg) return;
    void runAdvise(name);
  };

  // ───────── catalog actions
  const openRemote = useCallback((seed?: { url?: string; displayName?: string; connectorId?: string }) => {
    setRemoteSeed(seed || {});
    setRemoteOpen(true);
  }, []);

  const installFromCatalog = async (connectorId: string, row?: Record<string, unknown>) => {
    if (row?.remote_url_template) {
      openRemote({ url: String(row.remote_url || ""), displayName: String(row.title || connectorId), connectorId });
      return;
    }
    setInstallingId(`catalog:${connectorId}`);
    try {
      const res = await apiFetch(
        `${apiBase()}/admin/mcp/install-from-catalog?connector_id=${encodeURIComponent(connectorId)}`,
        { method: "POST" },
      );
      if (!res.ok) {
        let detail = `HTTP ${res.status}`;
        try {
          const body = await res.json();
          if (body?.detail != null) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
        } catch {
          /* keep the status */
        }
        throw new Error(detail);
      }
      const data = await res.json();
      setToast({
        message: t(`${k}.toast.catalog_installed`, { id: connectorId, slug: data.server_slug || data.name }),
        variant: "success",
      });
      void fetchRegistry();
      setTab("installed");
    } catch (e) {
      setToast({ message: t(`${k}.toast.catalog_failed`, { error: errText(e) }), variant: "error" });
    } finally {
      setInstallingId(null);
    }
  };

  const openWizardForMarket = (item: any, remote: boolean) => {
    const qualified =
      item.qualified_name || (item.id?.startsWith("smithery:") ? item.id.replace("smithery:", "") : item.id);
    setWizardTarget({
      id: item.id,
      qualified_name: qualified,
      display_name: item.name,
      description: item.description,
      icon_url: item.icon_url,
      runner: remote ? "node" : item.runner || "npx",
      package_url: remote ? item.deployment_url || item.url || item.qualified_name || item.name : item.qualified_name || item.name,
      source: item.source,
      url: item.url,
      is_remote: remote,
      deployment_url: remote ? item.deployment_url || item.url : "",
      remote_url: remote ? item.deployment_url || item.url : "",
      install_type: remote ? "remote" : item.install_type || "zero-install",
    });
    setWizardOpen(true);
  };

  const analyzeGithub = async () => {
    const url = githubUrl.trim();
    if (!url) return;
    setAnalyzingGithub(true);
    try {
      const res = await apiFetch(`${apiBase()}/admin/market/analyze-github`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || t(`${k}.github.failed`));
      }
      const data = await res.json();
      setGithubOpen(false);
      setGithubUrl("");
      setGithubName("");
      setWizardTarget({
        display_name: githubName.trim() || data.package_url || "mcp_github",
        description: data.description,
        runner: data.runner,
        package_url: data.package_url,
        command_args: data.command_args,
        required_envs: data.required_envs,
        cli_args: data.cli_args || [],
        source: "GitHub",
      });
      setWizardOpen(true);
    } catch (e) {
      setToast({ message: errText(e) || t(`${k}.github.failed`), variant: "error" });
    } finally {
      setAnalyzingGithub(false);
    }
  };

  return {
    t,
    k,
    tab,
    setTab,
    toast,
    setToast,
    busy,
    sandboxBackend,
    // installed
    installedLoaded,
    rows,
    visibleRows,
    counts,
    query,
    setQuery,
    runtimeFilter,
    setRuntimeFilter,
    statusFilter,
    setStatusFilter,
    probingSlug,
    probe,
    refreshAll,
    // catalog
    marketLoading,
    marketQuery,
    setMarketQuery,
    marketSource,
    setMarketSource,
    marketCategory,
    setMarketCategory,
    runMarketSearch,
    featured,
    featuredShown,
    communityShown,
    installingId,
    installFromCatalog,
    openWizardForMarket,
    // dialogs
    githubOpen,
    setGithubOpen,
    githubUrl,
    setGithubUrl,
    githubName,
    setGithubName,
    analyzingGithub,
    analyzeGithub,
    wizardOpen,
    wizardTarget,
    closeWizard: () => {
      setWizardOpen(false);
      setWizardTarget(null);
    },
    openWizardFor,
    manageToolsSlug,
    setManageToolsSlug,
    remoteOpen,
    setRemoteOpen,
    remoteSeed,
    openRemote,
    installRemoteStart: () => setInstallingId("remote:manual"),
    installRemoteEnd: () => setInstallingId(null),
    deleteSlug,
    setDeleteSlug,
    blockedBy,
    setBlockedBy,
    startDelete,
    confirmDelete,
    // config
    editing,
    setEditing,
    editingPolicy,
    setEditingPolicy,
    userMayDisable,
    setUserMayDisable,
    oauthConfig,
    setOauthConfig,
    formContext,
    connectorRows,
    integrationBySlug,
    openConfig,
    closeConfig,
    saveConfig,
    applySuggestedEnv,
    loadPolicyPreview,
    adviseOpen,
    setAdviseOpen,
    adviseLoading,
    adviseResult,
    openAdvisorFor,
    fetchRegistry,
    fetchIntegrations,
    fetchIntegrity,
  };
}

export type Hub = ReturnType<typeof useHub>;
