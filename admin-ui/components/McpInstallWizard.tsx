"use client";

import { useState, useEffect, useRef } from "react";
import { apiFetch } from "@/lib/api/headers";
import { apiBase } from "@/lib/api";
import { readApiErrorMessage } from "@/lib/apiErrors";
import { X, Loader2, Sparkles, AlertTriangle, CheckCircle, ChevronDown, ChevronRight, Wand2 } from "lucide-react";
import { CredentialSchemaEditor } from "@/components/CredentialSchemaEditor";
import { normalizeCredentialSchema, type CredentialSchemaField } from "@/lib/mcpIntegrationPolicy";

type WizardProps = {
  title: string;
  serverSlug?: string;
  marketItemId?: string;
  onClose: () => void;
  onDone: () => void;
};

type ConfigSuggestion = {
  credential_mode: string;
  requires_user_credentials: boolean;
  is_enabled_for_users: boolean;
  user_may_disable: boolean;
  apply_suggested_env: boolean;
  suggested_env: Record<string, string>;
  credential_schema: Array<{ key: string; label: string; type: string; required: boolean }>;
  warnings: string[];
  rationale?: string;
  _source?: string;
};

export function McpInstallWizard({ title, serverSlug, marketItemId, onClose, onDone }: WizardProps) {
  const [step, setStep] = useState(1);
  const [loading, setLoading] = useState(false);
  const [loadingText, setLoadingText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [resolvedSlug, setResolvedSlug] = useState(serverSlug || "");
  const [advise, setAdvise] = useState<Record<string, unknown> | null>(null);
  const [stepsMd, setStepsMd] = useState("");
  const [configSuggestion, setConfigSuggestion] = useState<ConfigSuggestion | null>(null);
  const [editableCredentialSchema, setEditableCredentialSchema] = useState<CredentialSchemaField[]>([]);
  const [llmUsed, setLlmUsed] = useState(false);
  const [llmError, setLlmError] = useState<string | null>(null);
  const [registryYaml, setRegistryYaml] = useState("");
  const [credentialMode, setCredentialMode] = useState("per_user");
  const [enableUsers, setEnableUsers] = useState(true);
  const [userMayDisable, setUserMayDisable] = useState(true);
  const [applyEnv, setApplyEnv] = useState(true);
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
  const [expandedSections, setExpandedSections] = useState<Record<string, boolean>>({
    analysis: true,
    config: false,
    env: false,
  });

  const loadingIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const dotsRef = useRef(0);

  const isMarketInstall = Boolean(marketItemId);

  // Dots animation during loading
  useEffect(() => {
    if (loading && step === 1) {
      dotsRef.current = 0;
      loadingIntervalRef.current = setInterval(() => {
        dotsRef.current = (dotsRef.current + 1) % 4;
        setLoadingText("AI is analyzing the MCP server" + ".".repeat(dotsRef.current));
      }, 400);
    } else {
      if (loadingIntervalRef.current) {
        clearInterval(loadingIntervalRef.current);
        loadingIntervalRef.current = null;
      }
      setLoadingText("");
    }
    return () => {
      if (loadingIntervalRef.current) clearInterval(loadingIntervalRef.current);
    };
  }, [loading, step]);

  function toggleSection(section: string) {
    setExpandedSections((prev) => ({ ...prev, [section]: !prev[section] }));
  }

  async function startWizard() {
    setLoading(true);
    setError(null);
    setLoadingText("AI is analyzing the MCP server");
    try {
      const body: Record<string, string> = {};
      if (marketItemId) body.market_item_id = marketItemId;
      else if (serverSlug) body.server_slug = serverSlug;
      const res = await apiFetch(`${apiBase()}/admin/mcp/install-wizard/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        throw new Error(await readApiErrorMessage(res));
      }
      const data = await res.json();
      const adv = data.advise || {};

      setResolvedSlug(data.server_slug || "");
      setAdvise(adv);
      setStepsMd((adv as { steps_markdown?: string })?.steps_markdown || "");
      setLlmUsed(Boolean((adv as { llm_used?: boolean })?.llm_used));
      setLlmError((adv as { llm_error?: string | null })?.llm_error || null);

      // Config suggestion strutturata
      const cfg = (adv as { config_suggestion?: ConfigSuggestion })?.config_suggestion;
      if (cfg) {
        setConfigSuggestion(cfg);
        setEditableCredentialSchema(normalizeCredentialSchema(cfg.credential_schema));
        setCredentialMode(cfg.credential_mode || "per_user");
        setEnableUsers(cfg.is_enabled_for_users);
        setUserMayDisable(cfg.user_may_disable);
        setApplyEnv(cfg.apply_suggested_env);
      } else {
        const mode = (adv as { credential_mode?: string })?.credential_mode || "per_user";
        setCredentialMode(mode);
        setEnableUsers(mode !== "none");
        setUserMayDisable(mode === "per_user");
        setApplyEnv(mode === "per_user");
      }

      // Env YAML
      const env = (adv as { suggested_env?: Record<string, string> })?.suggested_env || {};
      const yaml = (adv as { suggested_registry_env_yaml?: string })?.suggested_registry_env_yaml || "";
      setRegistryYaml(yaml || `env:\n${Object.entries(env).map(([k, v]) => `  ${k}: "${v}"`).join("\n")}`);

      const discovery = data.preview?.discovery;
      if (discovery && discovery.remote_auth_type === "oauth2") {
        setOauthConfig({
          provider: discovery.remote_oauth_provider || "generic",
          authorization_server: discovery.remote_oauth_server || "",
          token_url: discovery.remote_oauth_token_url || "",
          client_id: "",
          client_secret: "",
          scopes: [],
        });
      }

      setStep(2);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Error starting wizard");
    } finally {
      setLoading(false);
    }
  }

  async function commit() {
    setLoading(true);
    setError(null);
    try {
      const policyBody: Record<string, unknown> = {
        credential_mode: credentialMode,
        is_enabled_for_users: enableUsers,
        requires_user_credentials: credentialMode === "per_user",
        user_may_disable: userMayDisable,
        apply_suggested_env: applyEnv,
      };
      if (credentialMode === "per_user" && editableCredentialSchema.length > 0) {
        policyBody.credential_schema = editableCredentialSchema;
        policyBody.schema_override = true;
      }
      if (configSuggestion?.suggested_env && Object.keys(configSuggestion.suggested_env).length > 0) {
        policyBody.suggested_env = configSuggestion.suggested_env;
      }
      if (credentialMode === "per_user" && (oauthConfig.authorization_server || oauthConfig.client_id)) {
        policyBody.oauth_config = {
          provider: oauthConfig.provider || "generic",
          authorization_server: oauthConfig.authorization_server,
          token_url: oauthConfig.token_url,
          client_id: oauthConfig.client_id,
          client_secret: oauthConfig.client_secret,
          scopes: oauthConfig.scopes || [],
        };
      }
      const res = await apiFetch(`${apiBase()}/admin/mcp/install-wizard/commit`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          server_slug: resolvedSlug,
          registry_patch: {},
          policy: policyBody,
        }),
      });
      if (!res.ok) throw new Error(await readApiErrorMessage(res));
      onDone();
      onClose();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setLoading(false);
    }
  }

  // Renderizza markdown semplice (grassetto, elenchi, codice inline)
  function renderSimpleMd(text: string) {
    return text
      .split("\n")
      .map((line, i) => {
        // Titoli
        if (line.startsWith("### ")) return `<h4 class="text-sm font-bold text-white mt-3 mb-1">${line.slice(4)}</h4>`;
        if (line.startsWith("## ")) return `<h3 class="text-base font-bold text-indigo-300 mt-4 mb-1">${line.slice(3)}</h3>`;
        if (line.startsWith("# ")) return `<h3 class="text-lg font-bold text-indigo-300 mt-4 mb-1">${line.slice(2)}</h3>`;
        // Separatore
        if (line.trim() === "---") return '<hr class="border-white/10 my-2" />';
        // Codice inline
        let processed = line.replace(/`([^`]+)`/g, '<code class="bg-white/10 px-1 rounded text-xs font-mono text-emerald-300">$1</code>');
        // Grassetto
        processed = processed.replace(/\*\*([^*]+)\*\*/g, '<strong class="text-white">$1</strong>');
        if (processed.trim() === "") return "<br />";
        return `<p class="text-xs text-gray-300 leading-relaxed">${processed}</p>`;
      })
      .join("");
  }

  return (
    <div className="fixed inset-0 z-[70] bg-black/80 flex items-center justify-center p-4">
      <div className="bg-[#1a1a1a] border border-white/10 rounded-2xl max-w-2xl w-full p-6 space-y-4 max-h-[90vh] overflow-y-auto">
        <div className="flex justify-between items-center">
          <h3 className="text-lg font-bold text-white flex items-center gap-2">
            <Wand2 className="w-5 h-5 text-indigo-400" />
            Setup wizard — {title}
          </h3>
          <button type="button" onClick={onClose} className="text-gray-500 hover:text-white">
            <X className="w-5 h-5" />
          </button>
        </div>

        {error && (
          <div className="p-3 bg-red-500/10 border border-red-500/20 rounded-lg text-sm text-red-400 flex items-start gap-2">
            <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
            {error}
          </div>
        )}

        {/* STEP 1: Avvio + loading AI */}
        {step === 1 && (
          <div className="space-y-4 text-sm text-gray-300">
            <p>
              {isMarketInstall
                ? "The server will be installed from the marketplace. AI will analyze the server to determine the optimal configuration."
                : "AI will analyze the MCP server to determine credential mode, required variables, and deployment policy."}
            </p>

            {loading ? (
              <div className="flex flex-col items-center justify-center py-8 space-y-4">
                <div className="relative">
                  <div className="w-16 h-16 rounded-2xl bg-indigo-500/10 border border-indigo-500/20 flex items-center justify-center">
                    <Sparkles className="w-8 h-8 text-indigo-400 animate-pulse" />
                  </div>
                  <div className="absolute -top-1 -right-1 w-3 h-3 bg-indigo-500 rounded-full animate-ping" />
                </div>
                <p className="text-indigo-300 font-medium text-sm animate-pulse">{loadingText}</p>
                <p className="text-gray-500 text-xs">AI is examining the registry, connector catalog, and environment variables...</p>
              </div>
            ) : (
              <button
                type="button"
                disabled={loading}
                onClick={() => void startWizard()}
                className="w-full py-3 bg-indigo-600 hover:bg-indigo-500 rounded-xl font-bold text-white flex items-center justify-center gap-2 disabled:opacity-50"
              >
                {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
                {loading ? "Analysis in progress..." : "Start AI analysis"}
              </button>
            )}
          </div>
        )}

        {/* STEP 2: Risultati analisi + configurazione */}
        {step === 2 && (
          <div className="space-y-4 text-sm">
            {/* Server info + AI badge */}
            <div className="flex items-center justify-between">
              <p className="text-gray-400">
                Server: <span className="font-mono text-white bg-white/5 px-2 py-0.5 rounded">{resolvedSlug}</span>
              </p>
              <div className="flex items-center gap-2">
                {llmUsed ? (
                  <span className="flex items-center gap-1 text-[10px] font-bold bg-indigo-500/20 text-indigo-300 border border-indigo-500/30 px-2 py-0.5 rounded-full">
                    <Sparkles className="w-3 h-3" /> ANALISI AI
                  </span>
                ) : (
                  <span className="flex items-center gap-1 text-[10px] font-bold bg-amber-500/20 text-amber-300 border border-amber-500/30 px-2 py-0.5 rounded-full">
                    <AlertTriangle className="w-3 h-3" /> TEMPLATE
                    {llmError ? ` — ${llmError}` : " — AI non disponibile"}
                  </span>
                )}
              </div>
            </div>

            {/* Analisi AI (markdown renderizzato) */}
            {stepsMd && (
              <div>
                <button
                  type="button"
                  onClick={() => toggleSection("analysis")}
                  className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-gray-400 hover:text-white mb-2 w-full text-left"
                >
                  {expandedSections.analysis ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
                  AI Analysis {llmUsed && <Sparkles className="w-3 h-3 text-indigo-400" />}
                </button>
                {expandedSections.analysis && (
                  <div
                    className="text-xs bg-black/60 border border-white/10 p-4 rounded-xl text-gray-300 max-h-64 overflow-y-auto leading-relaxed space-y-1"
                    dangerouslySetInnerHTML={{ __html: renderSimpleMd(stepsMd) }}
                  />
                )}
              </div>
            )}

            {/* Config suggerita — formato leggibile */}
            {configSuggestion && (
              <div>
                <button
                  type="button"
                  onClick={() => toggleSection("config")}
                  className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-gray-400 hover:text-white mb-2 w-full text-left"
                >
                  {expandedSections.config ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
                  Suggested configuration
                  <span className={`text-[10px] font-mono px-1.5 py-0.5 rounded ${
                    configSuggestion.credential_mode === "per_user" ? "text-indigo-300 bg-indigo-500/10" :
                    configSuggestion.credential_mode === "org_shared" ? "text-emerald-300 bg-emerald-500/10" :
                    "text-gray-400 bg-white/5"
                  }`}>
                    {configSuggestion.credential_mode}
                  </span>
                  {configSuggestion._source === "ai" && (
                    <span className="text-[10px] text-indigo-400/70 flex items-center gap-1"><Sparkles className="w-3 h-3" />AI</span>
                  )}
                </button>
                {expandedSections.config && (
                  <div className="space-y-3 text-xs bg-black/40 border border-white/10 p-4 rounded-xl">
                    {/* Mode + rationale */}
                    <div className="flex items-start gap-2 p-2 rounded-lg bg-white/[0.03]">
                      <div className={`w-2 h-2 rounded-full mt-1 shrink-0 ${
                        configSuggestion.credential_mode === "per_user" ? "bg-indigo-400" :
                        configSuggestion.credential_mode === "org_shared" ? "bg-emerald-400" : "bg-gray-400"
                      }`} />
                      <div>
                        <p className="font-medium text-gray-200">
                          Mode: <span className="font-mono text-white">{configSuggestion.credential_mode}</span>
                          {" — "}{configSuggestion.credential_mode === "per_user" ? "Each user sets up their own credentials" :
                           configSuggestion.credential_mode === "org_shared" ? "Organization-shared credentials" :
                           "No credentials required"}
                        </p>
                        {configSuggestion.rationale && (
                          <p className="text-gray-500 mt-1 leading-relaxed">{configSuggestion.rationale}</p>
                        )}
                      </div>
                    </div>

                    {credentialMode === "per_user" && (
                      <>
                        <CredentialSchemaEditor
                          value={editableCredentialSchema}
                          onChange={setEditableCredentialSchema}
                        />

                        {/* OAuth info banner — OAuth authentication is delegated to the end user */}
                        <div className="flex items-start gap-3 rounded-xl border border-blue-500/20 bg-blue-500/[0.06] p-4 mt-3">
                          <span className="text-blue-300 mt-0.5 shrink-0 text-sm">🔑</span>
                          <div>
                            <div className="text-[10px] font-bold uppercase tracking-wider text-blue-300 mb-1">
                              OAuth Authentication — user-managed
                            </div>
                            <p className="text-[11px] text-gray-400 leading-relaxed">
                              If this server requires OAuth, each user will authenticate themselves from the <span className="font-semibold text-white">My Integrations</span> section in chat-ui. Set the policy to <span className="font-mono text-indigo-300">per_user</span> to enable it.
                            </p>
                          </div>
                        </div>
                      </>
                    )}

                    {/* Env variables */}
                    {configSuggestion.suggested_env && Object.keys(configSuggestion.suggested_env).length > 0 && (
                      <div className="space-y-2">
                        <p className="text-[10px] font-bold uppercase tracking-wider text-gray-500">
                          Environment Variables ({Object.keys(configSuggestion.suggested_env).length})
                        </p>
                        <div className="space-y-1 font-mono">
                          {Object.entries(configSuggestion.suggested_env).map(([k, v]) => (
                            <div key={k} className="flex items-center gap-2 text-[10px] p-1.5 rounded bg-black/30">
                              <span className="text-emerald-300 font-bold shrink-0">{k}</span>
                              <span className="text-gray-500">=</span>
                              <span className="text-gray-400 truncate">{String(v)}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Raw JSON (collapsed by default) */}
                    <details className="text-[10px]">
                      <summary className="text-gray-600 cursor-pointer hover:text-gray-400">JSON raw</summary>
                      <pre className="mt-1 text-gray-500 whitespace-pre-wrap overflow-x-auto">
                        {JSON.stringify(configSuggestion, null, 2)}
                      </pre>
                    </details>
                  </div>
                )}
              </div>
            )}

            {/* Warnings */}
            {configSuggestion?.warnings && configSuggestion.warnings.length > 0 && (
              <div className="space-y-1">
                {configSuggestion.warnings.map((w, i) => (
                  <div key={i} className="flex items-start gap-2 text-[11px] text-amber-300 bg-amber-500/10 border border-amber-500/20 rounded-lg p-2">
                    <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
                    {w}
                  </div>
                ))}
              </div>
            )}

            {/* Env YAML */}
            <div>
              <button
                type="button"
                onClick={() => toggleSection("env")}
                className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-gray-400 hover:text-white mb-2 w-full text-left"
              >
                {expandedSections.env ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
                Suggested environment variables
              </button>
              {expandedSections.env && (
                <pre className="text-xs bg-black/40 p-3 rounded-lg text-emerald-200/90 whitespace-pre-wrap max-h-40 overflow-auto font-mono">
                  {registryYaml || "# nessuna variabile suggerita"}
                </pre>
              )}
            </div>

            {/* Policy options (pre-filled by AI config) */}
            <div className="space-y-3 rounded-xl border border-white/10 bg-white/[0.03] p-4">
              <p className="text-[10px] font-bold uppercase tracking-wider text-gray-500">Deployment policy</p>

              <label className="flex items-center gap-2 text-gray-300 cursor-pointer">
                <input
                  type="radio"
                  name="credMode"
                  checked={credentialMode === "none"}
                  onChange={() => setCredentialMode("none")}
                  className="accent-indigo-500"
                />
                <span>No credentials <span className="text-gray-500 text-[10px]">(public or internal server)</span></span>
              </label>
              <label className="flex items-center gap-2 text-gray-300 cursor-pointer">
                <input
                  type="radio"
                  name="credMode"
                  checked={credentialMode === "org_shared"}
                  onChange={() => setCredentialMode("org_shared")}
                  className="accent-indigo-500"
                />
                <span>Organization <span className="text-gray-500 text-[10px]">(shared credentials via .env)</span></span>
              </label>
              <label className="flex items-center gap-2 text-gray-300 cursor-pointer">
                <input
                  type="radio"
                  name="credMode"
                  checked={credentialMode === "per_user"}
                  onChange={() => setCredentialMode("per_user")}
                  className="accent-indigo-500"
                />
                <span>Per user <span className="text-gray-500 text-[10px]">(each user sets up their own credentials)</span></span>
              </label>

              <div className="border-t border-white/5 pt-3 space-y-2">
                <label className="flex items-center gap-2 text-gray-300 cursor-pointer">
                  <input type="checkbox" checked={enableUsers} onChange={(e) => setEnableUsers(e.target.checked)} className="accent-indigo-500 rounded" />
                  Distribute to users (chat-ui)
                </label>
                <label className="flex items-center gap-2 text-gray-300 cursor-pointer">
                  <input type="checkbox" checked={userMayDisable} onChange={(e) => setUserMayDisable(e.target.checked)} className="accent-indigo-500 rounded" />
                  User can disable this integration
                </label>
                {(credentialMode === "per_user" || credentialMode === "org_shared") && (
                  <label className="flex items-center gap-2 text-gray-300 cursor-pointer">
                    <input type="checkbox" checked={applyEnv} onChange={(e) => setApplyEnv(e.target.checked)} className="accent-indigo-500 rounded" />
                    Applica env suggerito {credentialMode === "per_user" ? "(${AION_USER_*})" : "(da .env)"}
                  </label>
                )}
              </div>
            </div>

            {/* Actions */}
            <div className="flex gap-2 pt-2">
              <button type="button" onClick={() => setStep(1)} className="flex-1 py-2.5 border border-white/10 rounded-lg text-gray-400 hover:text-white hover:border-white/20 transition-colors">
                ← Back
              </button>
              <button
                type="button"
                disabled={loading}
                onClick={() => void commit()}
                className="flex-1 py-2.5 bg-indigo-600 hover:bg-indigo-500 rounded-lg font-bold text-white flex items-center justify-center gap-2 disabled:opacity-50 transition-colors"
              >
                {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <CheckCircle className="w-4 h-4" />}
                {loading ? "Saving…" : "Save & deploy"}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
