"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api/headers"
import { apiBase } from "@/lib/api";
import {
  Save, Shield, Globe, Server,
  Database, Zap, Lock, RefreshCw, AlertTriangle,
  Info, CheckCircle2, Search, Settings as SettingsIcon,
  Eye, EyeOff, Plus, Trash2, Edit2, X, ChevronDown, ChevronUp, Star,
  ShieldAlert, Cloud, ScanLine, Loader2,
} from "lucide-react";
import { PolicyEditor } from "@/components/policy-editor";
import { load as yamlLoad } from "js-yaml";
import {
  embeddingProviderToProbeProvider,
  embeddingServiceUrlFromProbeBase,
  filterModelsForKind,
  formatModelDisplayName,
  hintForModel,
  LlmProbeResponse,
  modelIdsFromProbe,
  pickDefaultModel,
  probeBaseUrlFromOcrServiceUrl,
  probeBaseUrlFromServiceUrl,
  providerNeedsBaseUrl,
  providerSupportsProbe,
  runModelProbe,
  slugFromModelId,
  validateMaxChatTokens,
} from "@/lib/llm-probe";

type OcrMode = "remote" | "local";

interface Settings {
  [key: string]: string;
}

export default function SettingsPage() {
  const [settings, setSettings] = useState<Settings>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ type: 'success' | 'error', text: string } | null>(null);

  const [restarting, setRestarting] = useState(false);
  const [showApiKey, setShowApiKey] = useState(false);
  const [showOcrApiKey, setShowOcrApiKey] = useState(false);
  const [ocrMode, setOcrMode] = useState<OcrMode>("local");

  // LLM provider form — connection probe
  const [providerProbing, setProviderProbing] = useState(false);
  const [providerProbeResult, setProviderProbeResult] = useState<LlmProbeResponse | null>(null);
  const [providerProbeLatencyMs, setProviderProbeLatencyMs] = useState<number | null>(null);
  const [providerConnectionTested, setProviderConnectionTested] = useState(false);
  const [providerDiscoveredModelIds, setProviderDiscoveredModelIds] = useState<string[]>([]);
  const [providerManualModelEntry, setProviderManualModelEntry] = useState(false);

  // Embeddings — connection probe
  const [embProbing, setEmbProbing] = useState(false);
  const [embProbeResult, setEmbProbeResult] = useState<LlmProbeResponse | null>(null);
  const [embProbeLatencyMs, setEmbProbeLatencyMs] = useState<number | null>(null);
  const [embConnectionTested, setEmbConnectionTested] = useState(false);
  const [embDiscoveredModelIds, setEmbDiscoveredModelIds] = useState<string[]>([]);
  const [embManualModelEntry, setEmbManualModelEntry] = useState(false);

  // OCR remote — connection probe
  const [ocrProbing, setOcrProbing] = useState(false);
  const [ocrProbeResult, setOcrProbeResult] = useState<LlmProbeResponse | null>(null);
  const [ocrProbeLatencyMs, setOcrProbeLatencyMs] = useState<number | null>(null);
  const [ocrConnectionTested, setOcrConnectionTested] = useState(false);
  const [ocrDiscoveredModelIds, setOcrDiscoveredModelIds] = useState<string[]>([]);
  const [ocrManualModelEntry, setOcrManualModelEntry] = useState(false);

  // Filesystem Policy State
  const [fsPolicyEnabled, setFsPolicyEnabled] = useState(true);
  const [fsPolicyYaml, setFsPolicyYaml] = useState("");
  const [devTemplateYaml, setDevTemplateYaml] = useState("");
  const [exampleTemplateYaml, setExampleTemplateYaml] = useState("");
  const [customYaml, setCustomYaml] = useState("");
  const [selectedPolicyType, setSelectedPolicyType] = useState<"dev" | "production" | "custom">("dev");
  const [policySaving, setPolicySaving] = useState(false);

  // LLM Providers state
  const [llmProviders, setLlmProviders] = useState<any[]>([]);
  const [editingProvider, setEditingProvider] = useState<any>(null);
  const [showForm, setShowForm] = useState(false);
  const [formLoading, setFormLoading] = useState(false);
  const [showApiKeyField, setShowApiKeyField] = useState(false);

  const emptyProviderForm = {
    slug: '',
    display_name: '',
    provider: 'openai',
    model_name: '',
    api_base_url: '',
    api_key: '',
    timeout: 300,
    max_chat_tokens: null as number | null,
    thinking_token_budget: null as number | null,
    enabled: true,
    is_default: false,
  };

  const [providerForm, setProviderForm] = useState(emptyProviderForm);

  useEffect(() => {
    fetchSettings();
    fetchLlmProviders();
    fetchFsPolicy();
  }, []);

  const fetchLlmProviders = async () => {
    try {
      const res = await apiFetch(`${apiBase()}/admin/llm-providers`);
      const data = await res.json();
      setLlmProviders(Array.isArray(data) ? data : []);
    } catch (err) {
      console.error("Failed to fetch LLM providers", err);
    }
  };

  const handleCreateProvider = () => {
    setProviderForm(emptyProviderForm);
    setEditingProvider(null);
    resetProviderProbeState();
    setShowForm(true);
  };

  const handleEditProvider = (provider: any) => {
    setProviderForm({
      slug: provider.slug || '',
      display_name: provider.display_name || '',
      provider: provider.provider || 'openai',
      model_name: provider.model_name || '',
      api_base_url: provider.api_base_url || '',
      api_key: '',
      timeout: provider.timeout || 300,
      max_chat_tokens: provider.max_chat_tokens || null,
      thinking_token_budget: provider.thinking_token_budget || null,
      enabled: provider.enabled !== false,
      is_default: provider.is_default || false,
    });
    setEditingProvider(provider);
    setProviderConnectionTested(!!provider.model_name);
    setProviderDiscoveredModelIds(provider.model_name ? [provider.model_name] : []);
    setProviderManualModelEntry(true);
    setProviderProbeResult(null);
    setProviderProbeLatencyMs(null);
    setShowForm(true);
    setShowApiKeyField(false);
  };

  const handleDeleteProvider = async (slug: string) => {
    if (!confirm("Are you sure you want to delete this provider?")) return;
    try {
      const res = await apiFetch(`${apiBase()}/admin/llm-providers/${slug}`, {
        method: "DELETE",
      });
      if (res.ok) {
        fetchLlmProviders();
        setMessage({ type: 'success', text: "Provider deleted successfully." });
      } else {
        const data = await res.json();
        setMessage({ type: 'error', text: data.detail || "Failed to delete provider." });
      }
    } catch (err) {
      setMessage({ type: 'error', text: "Network error while deleting provider." });
    }
  };

  const handleSaveProvider = async () => {
    if (!providerForm.slug || !providerForm.display_name) {
      setMessage({ type: 'error', text: "Please fill in Slug and Display Name." });
      return;
    }
    if (!providerForm.api_key && providerForm.provider !== "ollama" && !editingProvider) {
      setMessage({ type: 'error', text: "Please provide an API key." });
      return;
    }
    if (!providerForm.api_key && providerForm.provider !== "ollama" && editingProvider) {
      // Editing without re-entering key: skip probe if model already configured
      if (!providerForm.model_name.trim()) {
        setMessage({ type: 'error', text: "Model name is required." });
        return;
      }
    } else {
      if (!providerConnectionTested) {
        const ok = await probeProviderConnection();
        if (!ok) return;
      }
      if (!providerForm.model_name.trim()) {
        setMessage({
          type: 'error',
          text: providerManualModelEntry
            ? "Enter the model name manually — the endpoint did not list any models."
            : "Select a model from the list discovered by the connection test.",
        });
        return;
      }
      if (providerForm.max_chat_tokens != null) {
        const hint = hintForModel(providerProbeResult, providerForm.model_name);
        const tokenErr = validateMaxChatTokens(
          providerForm.max_chat_tokens,
          Number(providerForm.thinking_token_budget) || 0,
          hint,
        );
        if (tokenErr) {
          setMessage({ type: 'error', text: tokenErr });
          return;
        }
      }
    }
    if (!providerForm.model_name.trim()) {
      setMessage({ type: 'error', text: "Model name is required." });
      return;
    }
    setFormLoading(true);
    try {
      const url = editingProvider
        ? `${apiBase()}/admin/llm-providers/${editingProvider.slug}`
        : `${apiBase()}/admin/llm-providers`;
      const method = editingProvider ? "PUT" : "POST";

      const body: Record<string, unknown> = {
        slug: providerForm.slug,
        display_name: providerForm.display_name,
        provider: providerForm.provider,
        model_name: providerForm.model_name,
        api_base_url: providerForm.api_base_url || null,
        timeout: providerForm.timeout,
        max_chat_tokens: providerForm.max_chat_tokens || null,
        thinking_token_budget: providerForm.thinking_token_budget || null,
        enabled: providerForm.enabled,
        is_default: providerForm.is_default || false,
      };
      if (providerForm.api_key) {
        body.api_key = providerForm.api_key;
      }

      const res = await apiFetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (res.ok) {
        setShowForm(false);
        resetProviderProbeState();
        fetchLlmProviders();
        setMessage({ type: 'success', text: "Provider saved successfully." });
      } else {
        const data = await res.json();
        setMessage({ type: 'error', text: data.detail || "Failed to save provider." });
      }
    } catch (err) {
      setMessage({ type: 'error', text: "Network error while saving provider." });
    } finally {
      setFormLoading(false);
    }
  };

  const handleSetDefaultProvider = async (slug: string) => {
    try {
      const res = await apiFetch(`${apiBase()}/admin/llm-providers/${slug}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ is_default: true }),
      });
      if (res.ok) {
        fetchLlmProviders();
        setMessage({ type: 'success', text: "Provider set as default." });
      } else {
        const data = await res.json();
        setMessage({ type: 'error', text: data.detail || "Failed to set default provider." });
      }
    } catch (err) {
      setMessage({ type: 'error', text: "Network error while setting default provider." });
    }
  };

  const handleCancelProvider = () => {
    setShowForm(false);
    setEditingProvider(null);
    setProviderForm(emptyProviderForm);
    resetProviderProbeState();
  };

  const resetProviderProbeState = () => {
    setProviderProbeResult(null);
    setProviderProbeLatencyMs(null);
    setProviderConnectionTested(false);
    setProviderDiscoveredModelIds([]);
    setProviderManualModelEntry(false);
    setProviderForm((prev) => ({ ...prev, model_name: "" }));
  };

  const applyProviderModelSelection = (modelId: string, result: LlmProbeResponse | null) => {
    const hint = hintForModel(result, modelId);
    setProviderForm((prev) => ({
      ...prev,
      model_name: modelId,
      display_name: prev.display_name || formatModelDisplayName(modelId),
      slug: prev.slug || slugFromModelId(modelId, prev.provider === "vllm" ? "local" : "default"),
      max_chat_tokens: hint?.suggested_max_chat_tokens ?? prev.max_chat_tokens,
    }));
  };

  const handleProviderTypeChange = (provider: string) => {
    setProviderForm((prev) => ({
      ...prev,
      provider,
      model_name: "",
      max_chat_tokens: provider === "ollama" ? 4096 : prev.max_chat_tokens,
      thinking_token_budget:
        provider === "gemini" || provider === "ollama" ? 0 : prev.thinking_token_budget,
    }));
    resetProviderProbeState();
  };

  const probeProviderConnection = async (): Promise<boolean> => {
    if (providerNeedsBaseUrl(providerForm.provider) && !providerForm.api_base_url.trim()) {
      setMessage({ type: "error", text: "API Base URL is required for this provider." });
      return false;
    }
    if (providerForm.provider !== "ollama" && !providerForm.api_key.trim()) {
      setMessage({ type: "error", text: "API Key is required to test the connection." });
      return false;
    }

    setProviderProbing(true);
    setMessage(null);
    setProviderProbeLatencyMs(null);
    try {
      const result = await runModelProbe(apiFetch, apiBase(), {
        provider: providerForm.provider,
        api_base_url: providerForm.api_base_url.trim() || null,
        api_key: providerForm.api_key.trim() || null,
      });
      const allIds = modelIdsFromProbe(result);
      const chatIds = filterModelsForKind(allIds, "chat");
      setProviderProbeResult(result);
      setProviderDiscoveredModelIds(chatIds);
      setProviderConnectionTested(true);
      setProviderProbeLatencyMs(result.latency_ms);
      setProviderForm((prev) => ({
        ...prev,
        api_base_url: result.base_url || prev.api_base_url,
      }));

      if (chatIds.length > 0) {
        setProviderManualModelEntry(false);
        applyProviderModelSelection(pickDefaultModel(allIds, "chat"), result);
      } else {
        setProviderManualModelEntry(true);
        setProviderForm((prev) => ({ ...prev, model_name: "" }));
      }

      if (result.warning) {
        setMessage({ type: "error", text: result.warning });
      }
      return true;
    } catch (err: unknown) {
      resetProviderProbeState();
      const msg = err instanceof Error ? err.message : "Connection test failed.";
      setMessage({ type: "error", text: msg });
      return false;
    } finally {
      setProviderProbing(false);
    }
  };

  const resetEmbProbeState = () => {
    setEmbProbeResult(null);
    setEmbProbeLatencyMs(null);
    setEmbConnectionTested(false);
    setEmbDiscoveredModelIds([]);
    setEmbManualModelEntry(false);
    setSettings((prev) => ({ ...prev, AION_EMBEDDING_MODEL: "" }));
  };

  const handleEmbeddingsProviderChange = (provider: string) => {
    setSettings((prev) => ({
      ...prev,
      AION_EMBEDDINGS_PROVIDER: provider,
      AION_EMBEDDING_MODEL: "",
      AION_EMBEDDING_URL: "",
    }));
    resetEmbProbeState();
  };

  const probeEmbConnection = async (): Promise<boolean> => {
    const serviceUrl = settings.AION_EMBEDDING_URL || "";
    const probeBase = probeBaseUrlFromServiceUrl(serviceUrl);
    const embProvider = settings.AION_EMBEDDINGS_PROVIDER || "openai";
    if (!probeBase) {
      setMessage({ type: "error", text: "Embedding service URL is required to test the connection." });
      return false;
    }
    if (embProvider !== "google" && !(settings.AION_EMBEDDINGS_API_KEY || "").trim()) {
      setMessage({ type: "error", text: "Embedding API Key is required to test the connection." });
      return false;
    }

    setEmbProbing(true);
    setMessage(null);
    setEmbProbeLatencyMs(null);
    try {
      const result = await runModelProbe(apiFetch, apiBase(), {
        provider: embeddingProviderToProbeProvider(embProvider),
        api_base_url: probeBase,
        api_key: (settings.AION_EMBEDDINGS_API_KEY || "").trim() || null,
      });
      const allIds = modelIdsFromProbe(result);
      const embIds = filterModelsForKind(allIds, "embedding");
      setEmbProbeResult(result);
      setEmbDiscoveredModelIds(embIds);
      setEmbConnectionTested(true);
      setEmbProbeLatencyMs(result.latency_ms);
      const normalizedUrl = embeddingServiceUrlFromProbeBase(result.base_url || probeBase);
      setSettings((prev) => ({
        ...prev,
        AION_EMBEDDING_URL: normalizedUrl,
        AION_EMBEDDING_MODEL:
          embIds.length > 0 ? pickDefaultModel(allIds, "embedding") : prev.AION_EMBEDDING_MODEL || "",
      }));
      setEmbManualModelEntry(embIds.length === 0);

      if (result.warning) {
        setMessage({ type: "error", text: result.warning });
      }
      return true;
    } catch (err: unknown) {
      resetEmbProbeState();
      const msg = err instanceof Error ? err.message : "Connection test failed.";
      setMessage({ type: "error", text: msg });
      return false;
    } finally {
      setEmbProbing(false);
    }
  };

  const resetOcrProbeState = () => {
    setOcrProbeResult(null);
    setOcrProbeLatencyMs(null);
    setOcrConnectionTested(false);
    setOcrDiscoveredModelIds([]);
    setOcrManualModelEntry(false);
    setSettings((prev) => ({ ...prev, AION_OCR_MODEL: "" }));
  };

  const handleOcrModeChange = (mode: OcrMode) => {
    setOcrMode(mode);
    resetOcrProbeState();
    if (mode === "local") {
      setSettings((prev) => ({
        ...prev,
        AION_OCR_BASE_URL: "",
        AION_OCR_MODEL: "",
        AION_OCR_API_KEY: "",
        AION_OCR_MAX_TOKENS: "",
        AION_OCR_TIMEOUT: "",
        AION_OCR_MAX_IMAGE_BYTES: "",
      }));
    }
  };

  const probeOcrConnection = async (): Promise<boolean> => {
    const probeBase = probeBaseUrlFromOcrServiceUrl(settings.AION_OCR_BASE_URL || "");
    if (!probeBase) {
      setMessage({ type: "error", text: "OCR service base URL is required to test the connection." });
      return false;
    }
    if (!probeBase.startsWith("http://") && !probeBase.startsWith("https://")) {
      setMessage({ type: "error", text: "OCR service URL must start with http:// or https://" });
      return false;
    }
    const apiKey = (settings.AION_OCR_API_KEY || "").trim();
    if (!apiKey || apiKey === "EMPTY") {
      setMessage({
        type: "error",
        text: "A non-empty API token is required for remote vision OCR (do not use EMPTY).",
      });
      return false;
    }

    setOcrProbing(true);
    setMessage(null);
    setOcrProbeLatencyMs(null);
    try {
      const result = await runModelProbe(apiFetch, apiBase(), {
        provider: "vllm",
        api_base_url: probeBase,
        api_key: apiKey,
      });
      const allIds = modelIdsFromProbe(result);
      const ocrIds = filterModelsForKind(allIds, "ocr");
      setOcrProbeResult(result);
      setOcrDiscoveredModelIds(ocrIds);
      setOcrConnectionTested(true);
      setOcrProbeLatencyMs(result.latency_ms);
      setSettings((prev) => ({
        ...prev,
        AION_OCR_BASE_URL: result.base_url || probeBase,
        AION_OCR_MODEL:
          ocrIds.length > 0 ? pickDefaultModel(allIds, "ocr") : prev.AION_OCR_MODEL || "",
      }));
      setOcrManualModelEntry(ocrIds.length === 0);

      if (result.warning) {
        setMessage({ type: "error", text: result.warning });
      }
      return true;
    } catch (err: unknown) {
      resetOcrProbeState();
      const msg = err instanceof Error ? err.message : "OCR connection test failed.";
      setMessage({ type: "error", text: msg });
      return false;
    } finally {
      setOcrProbing(false);
    }
  };

  const fetchSettings = async () => {
    try {
      const res = await apiFetch(`${apiBase()}/admin/settings`);
      const data = await res.json();
      const currentSettings = data.settings || {};
      setSettings(currentSettings);

      const hasOcrRemote = !!(currentSettings.AION_OCR_BASE_URL || "").trim();
      setOcrMode(hasOcrRemote ? "remote" : "local");
      if (hasOcrRemote && currentSettings.AION_OCR_MODEL) {
        setOcrConnectionTested(true);
        setOcrDiscoveredModelIds([currentSettings.AION_OCR_MODEL]);
        setOcrManualModelEntry(true);
      } else {
        setOcrConnectionTested(false);
        setOcrDiscoveredModelIds([]);
        setOcrManualModelEntry(false);
      }

      const embModel = (currentSettings.AION_EMBEDDING_MODEL || "").trim();
      const embUrl = (currentSettings.AION_EMBEDDING_URL || "").trim();
      if (embModel && embUrl) {
        setEmbConnectionTested(true);
        setEmbDiscoveredModelIds([embModel]);
        setEmbManualModelEntry(true);
      } else {
        setEmbConnectionTested(false);
        setEmbDiscoveredModelIds([]);
        setEmbManualModelEntry(false);
      }
    } catch (err) {
      console.error("Failed to fetch settings", err);
    } finally {
      setLoading(false);
    }
  };

  const fetchFsPolicy = async () => {
    try {
      const res = await apiFetch(`${apiBase()}/admin/settings/fs-policy`);
      if (res.ok) {
        const data = await res.json();
        setFsPolicyEnabled(data.enabled);
        setDevTemplateYaml(data.dev_template || "");
        setExampleTemplateYaml(data.example_template || "");

        const activeYaml = data.yaml_content || "";
        setFsPolicyYaml(activeYaml);

        // Detect if the active policy matches one of the templates
        if (activeYaml === data.dev_template) {
          setSelectedPolicyType("dev");
          setCustomYaml(data.dev_template);
        } else if (activeYaml === data.example_template) {
          setSelectedPolicyType("production");
          setCustomYaml(data.example_template);
        } else {
          setSelectedPolicyType("custom");
          setCustomYaml(activeYaml);
        }
      }
    } catch (err) {
      console.error("Failed to fetch filesystem policy", err);
    }
  };

  const saveFsPolicy = async () => {
    setPolicySaving(true);
    setMessage(null);

    let yamlToSave = "";
    if (selectedPolicyType === "dev") {
      yamlToSave = devTemplateYaml;
    } else if (selectedPolicyType === "production") {
      yamlToSave = exampleTemplateYaml;
    } else {
      yamlToSave = customYaml;
    }

    // Validate rules: no rule can have an empty or whitespace-only executable name
    if (fsPolicyEnabled) {
      try {
        const parsed = yamlLoad(yamlToSave) as any;
        if (parsed && parsed.exec && Array.isArray(parsed.exec.allowlist)) {
          for (let i = 0; i < parsed.exec.allowlist.length; i++) {
            const rule = parsed.exec.allowlist[i];
            if (!rule || typeof rule !== "object" || !rule.executable || !rule.executable.trim()) {
              setMessage({
                type: 'error',
                text: `Validation failed: Rule #${i + 1} has an empty executable name.`
              });
              setPolicySaving(false);
              return;
            }
          }
        }
      } catch (err) {
        setMessage({
          type: 'error',
          text: "Invalid YAML format. Please correct it before saving."
        });
        setPolicySaving(false);
        return;
      }
    }

    try {
      const res = await apiFetch(`${apiBase()}/admin/settings/fs-policy`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          yaml_content: yamlToSave,
          enabled: fsPolicyEnabled,
        }),
      });

      if (res.ok) {
        const data = await res.json();
        if (data.restarting) {
          setRestarting(true);
          pollHealth();
        } else {
          setMessage({ type: 'success', text: "Filesystem policy updated successfully." });
          fetchFsPolicy();
        }
      } else {
        try {
          const errData = await res.json();
          setMessage({ type: 'error', text: errData.detail || "Failed to save filesystem policy." });
        } catch {
          setMessage({ type: 'error', text: "Failed to save filesystem policy." });
        }
      }
    } catch (err) {
      setMessage({ type: 'error', text: "Network error while saving filesystem policy." });
    } finally {
      setPolicySaving(false);
    }
  };

  const handleUpdate = (key: string, value: string) => {
    setSettings(prev => ({ ...prev, [key]: value }));
  };

  const pollHealth = async () => {
    const maxAttempts = 30;
    let attempt = 0;

    await new Promise(resolve => setTimeout(resolve, 2000));

    const interval = setInterval(async () => {
      attempt++;
      try {
        const res = await fetch(`${apiBase()}/health`);
        if (res.ok) {
          const data = await res.json();
          if (data.status === "ok") {
            clearInterval(interval);
            setRestarting(false);
            setMessage({ type: 'success', text: "API Container restarted and configuration applied successfully." });
            fetchSettings();
          }
        }
      } catch (err) {
        console.log("Waiting for backend to come back online...", err);
      }

      if (attempt >= maxAttempts) {
        clearInterval(interval);
        setRestarting(false);
        setMessage({ type: 'error', text: "API Container took too long to restart. Please verify manually." });
        fetchSettings();
      }
    }, 1500);
  };

  const saveSettings = async () => {
    setSaving(true);
    setMessage(null);

    // Validation when remote OCR is configured
    if (ocrMode === "remote") {
      const probeBase = probeBaseUrlFromOcrServiceUrl(settings.AION_OCR_BASE_URL || "");
      if (!probeBase) {
        setMessage({ type: 'error', text: "OCR service base URL is required for remote vision OCR." });
        setSaving(false);
        return;
      }
      if (!probeBase.startsWith("http://") && !probeBase.startsWith("https://")) {
        setMessage({ type: 'error', text: "OCR service URL must start with http:// or https://" });
        setSaving(false);
        return;
      }
      const apiKey = (settings.AION_OCR_API_KEY || "").trim();
      if (!apiKey || apiKey === "EMPTY") {
        setMessage({ type: 'error', text: "A non-empty API token is required for remote vision OCR." });
        setSaving(false);
        return;
      }
      if (!ocrConnectionTested) {
        const ok = await probeOcrConnection();
        if (!ok) {
          setSaving(false);
          return;
        }
      }
      if (!(settings.AION_OCR_MODEL || "").trim()) {
        setMessage({
          type: 'error',
          text: ocrManualModelEntry
            ? "Enter the OCR model name manually — the endpoint did not list any models."
            : "Select an OCR model from the list discovered by the connection test.",
        });
        setSaving(false);
        return;
      }

      // Max tokens validation
      if (settings.AION_OCR_MAX_TOKENS) {
        const val = parseInt(settings.AION_OCR_MAX_TOKENS, 10);
        if (isNaN(val) || val <= 0) {
          setMessage({ type: 'error', text: "OCR Max Tokens must be a positive integer." });
          setSaving(false);
          return;
        }
      }

      // Timeout validation
      if (settings.AION_OCR_TIMEOUT) {
        const val = parseInt(settings.AION_OCR_TIMEOUT, 10);
        if (isNaN(val) || val <= 0) {
          setMessage({ type: 'error', text: "OCR Timeout must be a positive integer." });
          setSaving(false);
          return;
        }
      }

      // Max image bytes validation
      if (settings.AION_OCR_MAX_IMAGE_BYTES) {
        const val = parseInt(settings.AION_OCR_MAX_IMAGE_BYTES, 10);
        if (isNaN(val) || val <= 0) {
          setMessage({ type: 'error', text: "OCR Max Image Bytes must be a positive integer." });
          setSaving(false);
          return;
        }
      }
    }

    // Embeddings validation when URL is set
    if ((settings.AION_EMBEDDING_URL || "").trim()) {
      const embProvider = settings.AION_EMBEDDINGS_PROVIDER || "openai";
      if (embProvider !== "google" && !(settings.AION_EMBEDDINGS_API_KEY || "").trim()) {
        setMessage({ type: 'error', text: "Embedding API Key is required." });
        setSaving(false);
        return;
      }
      if (!embConnectionTested) {
        const ok = await probeEmbConnection();
        if (!ok) {
          setSaving(false);
          return;
        }
      }
      if (!(settings.AION_EMBEDDING_MODEL || "").trim()) {
        setMessage({
          type: 'error',
          text: embManualModelEntry
            ? "Enter the embedding model name manually — the endpoint did not list any models."
            : "Select an embedding model from the list discovered by the connection test.",
        });
        setSaving(false);
        return;
      }
    }

    // Build the payload
    const payloadSettings = { ...settings };
    if (ocrMode === "local") {
      payloadSettings.AION_OCR_BASE_URL = "";
      payloadSettings.AION_OCR_MODEL = "";
      payloadSettings.AION_OCR_API_KEY = "";
      payloadSettings.AION_OCR_MAX_TOKENS = "";
      payloadSettings.AION_OCR_TIMEOUT = "";
      payloadSettings.AION_OCR_MAX_IMAGE_BYTES = "";
    }

    try {
      const res = await apiFetch(`${apiBase()}/admin/settings`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ settings: payloadSettings }),
      });
      if (res.ok) {
        const data = await res.json();
        if (data.restarting) {
          setRestarting(true);
          pollHealth();
        } else {
          setMessage({ type: 'success', text: "Configuration updated successfully. Some changes may require a restart." });
          fetchSettings();
        }
      } else {
        try {
          const data = await res.json();
          setMessage({ type: 'error', text: data.detail || "Failed to save configuration." });
        } catch {
          setMessage({ type: 'error', text: "Failed to save configuration." });
        }
      }
    } catch (err) {
      setMessage({ type: 'error', text: "Network error while saving settings." });
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center h-[60vh] gap-4">
        <div className="w-12 h-12 border-4 border-blue-500/20 border-t-blue-500 rounded-full animate-spin" />
        <p className="text-gray-500 font-bold uppercase text-[10px] tracking-widest animate-pulse">Decrypting environment...</p>
      </div>
    );
  }

  return (
    <div className="max-w-6xl mx-auto space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-700">
      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <SettingsIcon className="w-4 h-4 text-blue-500" />
            <h2 className="text-[10px] font-bold uppercase tracking-[0.2em] text-gray-500">System Governance</h2>
          </div>
          <h1 className="text-3xl font-black text-white">Kernel Configuration</h1>
          <p className="text-gray-500 text-sm mt-1">Manage global environment variables and infrastructure protocols.</p>
        </div>

        <div className="flex gap-3">
          <button
            onClick={saveSettings}
            disabled={saving}
            className={`flex items-center gap-2 px-6 py-2.5 rounded-xl font-bold transition-all shadow-lg ${saving
              ? 'bg-gray-800 text-gray-500 cursor-not-allowed'
              : 'bg-blue-600 hover:bg-blue-500 text-white shadow-blue-500/20 active:scale-95'
              }`}
          >
            {saving ? (
              <div className="w-4 h-4 border-2 border-white/20 border-t-white rounded-full animate-spin" />
            ) : <Save className="w-4 h-4" />}
            {saving ? "Syncing..." : "Commit Changes"}
          </button>
        </div>
      </div>

      {message && (
        <div className={`p-4 rounded-2xl flex items-start gap-3 border animate-in zoom-in duration-300 ${message.type === 'success'
          ? 'bg-green-500/10 border-green-500/20 text-green-400'
          : 'bg-red-500/10 border-red-500/20 text-red-400'
          }`}>
          {message.type === 'success' ? <CheckCircle2 className="w-5 h-5 shrink-0" /> : <AlertTriangle className="w-5 h-5 shrink-0" />}
          <div className="text-sm font-medium">{message.text}</div>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">


        {/* LLM Providers */}
        <section className="glass-card p-6 border-[#262626] hover:border-purple-500/30 transition-colors group md:col-span-2 animate-in fade-in duration-500">
          <div className="flex items-center justify-between mb-6">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-purple-500/10 flex items-center justify-center border border-purple-500/20 group-hover:scale-110 transition-transform">
                <Server className="w-5 h-5 text-purple-500" />
              </div>
              <div>
                <h3 className="font-bold text-white">LLM Providers</h3>
                <p className="text-[10px] text-gray-500 uppercase font-bold tracking-wider">Manage Models & Credentials</p>
              </div>
            </div>
            <button
              onClick={handleCreateProvider}
              className="flex items-center gap-2 px-4 py-2 rounded-xl font-bold bg-purple-600 hover:bg-purple-500 text-white transition-all shadow-lg shadow-purple-500/20 active:scale-95"
            >
              <Plus className="w-4 h-4" />
              Add Provider
            </button>
          </div>

          {showForm && (
            <div className="mb-6 p-4 bg-white/5 rounded-2xl border border-purple-500/30 space-y-4 animate-in fade-in slide-in-from-top-2">
              <div className="flex items-center justify-between">
                <h4 className="font-bold text-white">{editingProvider ? "Edit Provider" : "New Provider"}</h4>
                <button onClick={handleCancelProvider} className="p-1.5 rounded-lg hover:bg-white/10 text-gray-400">
                  <X className="w-4 h-4" />
                </button>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="space-y-1.5">
                  <label className="text-[10px] font-bold uppercase text-gray-500 tracking-wider">Slug (unique identifier)</label>
                  <input
                    type="text"
                    value={providerForm.slug}
                    onChange={(e) => setProviderForm(p => ({ ...p, slug: e.target.value }))}
                    disabled={!!editingProvider}
                    className="w-full bg-[#0d0d0d] border border-[#262626] rounded-xl px-4 py-2.5 text-sm text-gray-200 focus:border-purple-500/50 focus:ring-1 focus:ring-purple-500/20 outline-none transition-all font-mono disabled:opacity-50"
                    placeholder="my-model"
                  />
                </div>

                <div className="space-y-1.5">
                  <label className="text-[10px] font-bold uppercase text-gray-500 tracking-wider">Display Name</label>
                  <input
                    type="text"
                    value={providerForm.display_name}
                    onChange={(e) => setProviderForm(p => ({ ...p, display_name: e.target.value }))}
                    className="w-full bg-[#0d0d0d] border border-[#262626] rounded-xl px-4 py-2.5 text-sm text-gray-200 focus:border-purple-500/50 focus:ring-1 focus:ring-purple-500/20 outline-none transition-all font-mono"
                    placeholder="My Custom Model"
                  />
                </div>

                <div className="space-y-1.5 md:col-span-2">
                  <label className="text-[10px] font-bold uppercase text-gray-500 tracking-wider">Provider</label>
                  <select
                    value={providerForm.provider}
                    onChange={(e) => handleProviderTypeChange(e.target.value)}
                    className="w-full bg-[#0d0d0d] border border-[#262626] rounded-xl px-4 py-2.5 text-sm text-gray-200 focus:border-purple-500/50 focus:ring-1 focus:ring-purple-500/20 outline-none transition-all font-mono"
                  >
                    <option value="openai">OpenAI</option>
                    <option value="anthropic">Anthropic</option>
                    <option value="gemini">Google Gemini</option>
                    <option value="ollama">Ollama</option>
                    <option value="vllm">vLLM</option>
                  </select>
                </div>

                {providerForm.provider !== "ollama" && (
                  <div className="space-y-1.5 md:col-span-2">
                    <label className="text-[10px] font-bold uppercase text-gray-500 tracking-wider">
                      API Key {editingProvider ? "(leave blank to keep existing)" : "(encrypted)"}
                    </label>
                    <div className="flex gap-2">
                      <input
                        type={showApiKeyField ? "text" : "password"}
                        value={providerForm.api_key}
                        onChange={(e) => {
                          setProviderForm((p) => ({ ...p, api_key: e.target.value }));
                          if (e.target.value) resetProviderProbeState();
                        }}
                        className="flex-1 bg-[#0d0d0d] border border-[#262626] rounded-xl px-4 py-2.5 text-sm text-gray-200 focus:border-purple-500/50 focus:ring-1 focus:ring-purple-500/20 outline-none transition-all font-mono"
                        placeholder={editingProvider ? "sk-... (only if changing)" : "sk-... (required, encrypted at rest)"}
                        autoComplete="new-password"
                      />
                      <button
                        type="button"
                        onClick={() => setShowApiKeyField(!showApiKeyField)}
                        className="p-2.5 rounded-xl bg-white/5 border border-white/10 text-gray-400 hover:text-white transition-all"
                        title={showApiKeyField ? "Hide key" : "Show key"}
                      >
                        {showApiKeyField ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                      </button>
                    </div>
                  </div>
                )}

                <div className="space-y-1.5 md:col-span-2">
                  <label className="text-[10px] font-bold uppercase text-gray-500 tracking-wider">
                    API Base URL {providerNeedsBaseUrl(providerForm.provider) ? "" : "(optional)"}
                  </label>
                  <input
                    type="text"
                    value={providerForm.api_base_url}
                    onChange={(e) => {
                      setProviderForm((p) => ({ ...p, api_base_url: e.target.value }));
                      resetProviderProbeState();
                    }}
                    className="w-full bg-[#0d0d0d] border border-[#262626] rounded-xl px-4 py-2.5 text-sm text-gray-200 focus:border-purple-500/50 focus:ring-1 focus:ring-purple-500/20 outline-none transition-all font-mono"
                    placeholder={
                      providerForm.provider === "ollama"
                        ? "http://localhost:11434/v1"
                        : providerForm.provider === "vllm"
                          ? "http://localhost:8000/v1"
                          : ""
                    }
                  />
                </div>

                {providerSupportsProbe(providerForm.provider) && (
                  <div className="md:col-span-2 flex flex-wrap items-center gap-3">
                    <button
                      type="button"
                      onClick={probeProviderConnection}
                      disabled={providerProbing}
                      className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl border border-purple-500/30 bg-purple-500/10 text-purple-300 text-sm font-semibold hover:bg-purple-500/20 transition-all disabled:opacity-50"
                    >
                      {providerProbing ? <Loader2 className="w-4 h-4 animate-spin" /> : <Zap className="w-4 h-4" />}
                      Test connection & discover models
                    </button>
                    {providerConnectionTested && providerProbeLatencyMs != null && (
                      <span className="text-xs text-emerald-400 font-mono">
                        Connection OK · {providerProbeLatencyMs}ms
                        {providerDiscoveredModelIds.length > 0
                          ? ` · ${providerDiscoveredModelIds.length} models`
                          : " · enter model manually"}
                      </span>
                    )}
                  </div>
                )}

                {!providerConnectionTested ? (
                  <div className="md:col-span-2 p-4 rounded-xl border border-dashed border-[#262626] bg-[#0a0a0a]/60 text-sm text-gray-500 flex items-start gap-3">
                    <Info className="w-5 h-5 shrink-0 mt-0.5 text-gray-600" />
                    <span>
                      Test the endpoint to discover models
                      {editingProvider ? " (optional if keeping the current model without changing credentials)" : ""}.
                    </span>
                  </div>
                ) : providerManualModelEntry ? (
                  <div className="space-y-1.5 md:col-span-2">
                    <label className="text-[10px] font-bold uppercase text-gray-500 tracking-wider">Model name (manual)</label>
                    <input
                      type="text"
                      value={providerForm.model_name}
                      onChange={(e) => {
                        const modelId = e.target.value;
                        setProviderForm((p) => ({
                          ...p,
                          model_name: modelId,
                          display_name: p.display_name || (modelId ? formatModelDisplayName(modelId) : ""),
                          slug: p.slug || (modelId ? slugFromModelId(modelId, p.provider === "vllm" ? "local" : "default") : ""),
                        }));
                      }}
                      className="w-full bg-[#0d0d0d] border border-[#262626] rounded-xl px-4 py-2.5 text-sm text-gray-200 focus:border-purple-500/50 focus:ring-1 focus:ring-purple-500/20 outline-none transition-all font-mono"
                      placeholder="Enter the exact model id served by your endpoint"
                    />
                  </div>
                ) : (
                  <div className="space-y-1.5 md:col-span-2">
                    <label className="text-[10px] font-bold uppercase text-gray-500 tracking-wider">Model (auto-discovered)</label>
                    <select
                      value={providerForm.model_name}
                      onChange={(e) => applyProviderModelSelection(e.target.value, providerProbeResult)}
                      className="w-full bg-[#0d0d0d] border border-[#262626] rounded-xl px-4 py-2.5 text-sm text-gray-200 focus:border-purple-500/50 focus:ring-1 focus:ring-purple-500/20 outline-none transition-all font-mono cursor-pointer"
                    >
                      {providerDiscoveredModelIds.map((id) => (
                        <option key={id} value={id}>
                          {id}
                        </option>
                      ))}
                    </select>
                    {hintForModel(providerProbeResult, providerForm.model_name) && (
                      <p className="text-[11px] text-gray-500 font-mono">
                        Context window:{" "}
                        {hintForModel(providerProbeResult, providerForm.model_name)?.context_window.toLocaleString()} tokens
                      </p>
                    )}
                  </div>
                )}

                <div className="space-y-1.5">
                  <label className="text-[10px] font-bold uppercase text-gray-500 tracking-wider">Timeout (seconds)</label>
                  <input
                    type="number"
                    value={providerForm.timeout}
                    onChange={(e) => setProviderForm(p => ({ ...p, timeout: parseInt(e.target.value) }))}
                    className="w-full bg-[#0d0d0d] border border-[#262626] rounded-xl px-4 py-2.5 text-sm text-gray-200 focus:border-purple-500/50 focus:ring-1 focus:ring-purple-500/20 outline-none transition-all font-mono"
                  />
                </div>

                <div className="space-y-1.5">
                  <label className="text-[10px] font-bold uppercase text-gray-500 tracking-wider">Max Chat Tokens (optional)</label>
                  <input
                    type="number"
                    value={providerForm.max_chat_tokens || ''}
                    onChange={(e) => setProviderForm(p => ({ ...p, max_chat_tokens: e.target.value ? parseInt(e.target.value) : null }))}
                    className="w-full bg-[#0d0d0d] border border-[#262626] rounded-xl px-4 py-2.5 text-sm text-gray-200 focus:border-purple-500/50 focus:ring-1 focus:ring-purple-500/20 outline-none transition-all font-mono"
                    placeholder="4096"
                  />
                </div>

                <div className="space-y-1.5">
                  <label className="text-[10px] font-bold uppercase text-gray-500 tracking-wider">Thinking Token Budget (optional)</label>
                  <input
                    type="number"
                    value={providerForm.thinking_token_budget || ''}
                    onChange={(e) => setProviderForm(p => ({ ...p, thinking_token_budget: e.target.value ? parseInt(e.target.value) : null }))}
                    className="w-full bg-[#0d0d0d] border border-[#262626] rounded-xl px-4 py-2.5 text-sm text-gray-200 focus:border-purple-500/50 focus:ring-1 focus:ring-purple-500/20 outline-none transition-all font-mono"
                    placeholder="1024"
                  />
                </div>

                <div className="flex items-center gap-3 md:col-span-2">
                  <label className="text-[10px] font-bold uppercase text-gray-500 tracking-wider">Enabled</label>
                  <button
                    onClick={() => setProviderForm(p => ({ ...p, enabled: !p.enabled }))}
                    className={`w-10 h-5 rounded-full transition-all flex items-center px-1 ${providerForm.enabled ? 'bg-purple-600' : 'bg-gray-700'}`}
                  >
                    <div className={`w-3 h-3 rounded-full bg-white transition-all ${providerForm.enabled ? 'translate-x-5' : 'translate-x-0'}`} />
                  </button>
                </div>

                <div className="flex items-center gap-3 md:col-span-2">
                  <label className="text-[10px] font-bold uppercase text-gray-500 tracking-wider">Default Provider</label>
                  <button
                    onClick={() => setProviderForm(p => ({ ...p, is_default: !p.is_default }))}
                    className={`w-10 h-5 rounded-full transition-all flex items-center px-1 ${providerForm.is_default ? 'bg-yellow-600' : 'bg-gray-700'}`}
                  >
                    <div className={`w-3 h-3 rounded-full bg-white transition-all ${providerForm.is_default ? 'translate-x-5' : 'translate-x-0'}`} />
                  </button>
                </div>
              </div>

              <div className="flex gap-3 pt-2">
                <button
                  onClick={handleSaveProvider}
                  disabled={formLoading}
                  className="flex items-center gap-2 px-6 py-2.5 rounded-xl font-bold bg-purple-600 hover:bg-purple-500 text-white transition-all shadow-lg shadow-purple-500/20 active:scale-95 disabled:opacity-50"
                >
                  {formLoading ? (
                    <div className="w-4 h-4 border-2 border-white/20 border-t-white rounded-full animate-spin" />
                  ) : <Save className="w-4 h-4" />}
                  {formLoading ? "Saving..." : "Save Provider"}
                </button>
                <button
                  onClick={handleCancelProvider}
                  className="px-6 py-2.5 rounded-xl font-bold bg-white/5 border border-white/10 text-gray-400 hover:text-white transition-all"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}

          {llmProviders.length === 0 ? (
            <div className="text-center py-12">
              <Server className="w-12 h-12 text-gray-700 mx-auto mb-3" />
              <p className="text-gray-500 text-sm">No LLM providers configured yet.</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="border-b border-[#262626]">
                    <th className="text-left p-3 text-[10px] font-bold uppercase tracking-wider text-gray-500">Slug</th>
                    <th className="text-left p-3 text-[10px] font-bold uppercase tracking-wider text-gray-500">Display Name</th>
                    <th className="text-left p-3 text-[10px] font-bold uppercase tracking-wider text-gray-500">Provider</th>
                    <th className="text-left p-3 text-[10px] font-bold uppercase tracking-wider text-gray-500">Model</th>
                    <th className="text-left p-3 text-[10px] font-bold uppercase tracking-wider text-gray-500">API URL</th>
                    <th className="text-left p-3 text-[10px] font-bold uppercase tracking-wider text-gray-500">Status</th>
                    <th className="text-center p-3 text-[10px] font-bold uppercase tracking-wider text-gray-500">Default</th>
                    <th className="text-right p-3 text-[10px] font-bold uppercase tracking-wider text-gray-500">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {llmProviders.map((provider) => (
                    <tr key={provider.id} className="border-b border-[#262626] hover:bg-white/5 transition-colors">
                      <td className="p-3">
                        <code className="text-xs bg-white/5 px-2 py-1 rounded text-purple-400">{provider.slug}</code>
                      </td>
                      <td className="p-3 text-sm text-gray-200 font-medium">{provider.display_name}</td>
                      <td className="p-3">
                        <span className="text-xs bg-purple-500/10 text-purple-400 px-2 py-1 rounded font-mono">{provider.provider}</span>
                      </td>
                      <td className="p-3">
                        <code className="text-xs bg-white/5 px-2 py-1 rounded text-gray-300">{provider.model_name}</code>
                      </td>
                      <td className="p-3">
                        {provider.api_base_url ? (
                          <code className="text-xs bg-white/5 px-2 py-1 rounded text-gray-400 truncate block max-w-[150px]">{provider.api_base_url}</code>
                        ) : (
                          <span className="text-xs text-gray-600">—</span>
                        )}
                      </td>
                      <td className="p-3">
                        <span className={`text-xs px-2 py-1 rounded font-bold uppercase ${provider.enabled ? 'bg-green-500/10 text-green-400' : 'bg-red-500/10 text-red-400'}`}>
                          {provider.enabled ? 'Active' : 'Disabled'}
                        </span>
                      </td>
                      <td className="p-3 text-center">
                        {provider.is_default ? (
                          <Star className="w-4 h-4 text-yellow-500 mx-auto" />
                        ) : (
                          <span className="text-xs text-gray-600">—</span>
                        )}
                      </td>
                      <td className="p-3 text-right">
                        <div className="flex items-center justify-end gap-2">
                          <button
                            onClick={() => handleSetDefaultProvider(provider.slug)}
                            disabled={provider.is_default}
                            className="p-1.5 rounded-lg hover:bg-yellow-500/20 text-gray-500 hover:text-yellow-400 transition-all disabled:opacity-30 disabled:cursor-not-allowed"
                            title="Set as default"
                          >
                            <Star className="w-4 h-4" />
                          </button>
                          <button
                            onClick={() => handleEditProvider(provider)}
                            className="p-1.5 rounded-lg hover:bg-white/10 text-gray-500 hover:text-white transition-all"
                            title="Edit provider"
                          >
                            <Edit2 className="w-4 h-4" />
                          </button>
                          <button
                            onClick={() => handleDeleteProvider(provider.slug)}
                            className="p-1.5 rounded-lg hover:bg-red-500/20 text-gray-500 hover:text-red-400 transition-all"
                            title="Delete provider"
                          >
                            <Trash2 className="w-4 h-4" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>


        {/* Web search & fetch */}
        <section className="glass-card p-6 border-[#262626] hover:border-cyan-500/30 transition-colors group md:col-span-2">
          <div className="flex items-center gap-3 mb-6">
            <div className="w-10 h-10 rounded-xl bg-cyan-500/10 flex items-center justify-center border border-cyan-500/20 group-hover:scale-110 transition-transform">
              <Search className="w-5 h-5 text-cyan-500" />
            </div>
            <div>
              <h3 className="font-bold text-white">Web search & page fetch</h3>
              <p className="text-[10px] text-gray-500 uppercase font-bold tracking-wider">Tavily · Brave · SearXNG · Scrapling</p>
            </div>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <ConfigToggle
              label="Tavily enabled"
              enabled={settings.AION_WEB_SEARCH_TAVILY_ENABLED === "1"}
              onChange={(e) => handleUpdate("AION_WEB_SEARCH_TAVILY_ENABLED", e ? "1" : "0")}
            />
            <ConfigToggle
              label="Brave Search enabled"
              enabled={settings.AION_WEB_SEARCH_BRAVE_ENABLED === "1"}
              onChange={(e) => handleUpdate("AION_WEB_SEARCH_BRAVE_ENABLED", e ? "1" : "0")}
            />
            <ConfigToggle
              label="SearXNG enabled"
              enabled={settings.AION_WEB_SEARCH_SEARXNG_ENABLED === "1"}
              onChange={(e) => handleUpdate("AION_WEB_SEARCH_SEARXNG_ENABLED", e ? "1" : "0")}
            />
            <ConfigToggle
              label="Scrapling stealth fetch"
              enabled={settings.AION_SCRAPLING_STEALTH_ENABLED === "1"}
              onChange={(e) => handleUpdate("AION_SCRAPLING_STEALTH_ENABLED", e ? "1" : "0")}
            />
            <ConfigInput
              label="Tavily API key"
              value={settings.AION_TAVILY_API_KEY || ""}
              onChange={(v) => handleUpdate("AION_TAVILY_API_KEY", v)}
              description="Mascherata dopo il salvataggio in lettura"
            />
            <ConfigInput
              label="Brave Search API key"
              value={settings.AION_BRAVE_SEARCH_API_KEY || ""}
              onChange={(v) => handleUpdate("AION_BRAVE_SEARCH_API_KEY", v)}
            />
            <ConfigInput
              label="SearXNG base URL"
              value={settings.AION_SEARXNG_BASE_URL || ""}
              onChange={(v) => handleUpdate("AION_SEARXNG_BASE_URL", v)}
              description="Es. https://search.example.org (no trailing slash)"
            />
            <ConfigInput
              label="Default provider"
              value={settings.AION_WEB_SEARCH_DEFAULT_PROVIDER || "tavily"}
              onChange={(v) => handleUpdate("AION_WEB_SEARCH_DEFAULT_PROVIDER", v)}
            />
            <ConfigInput
              label="Fallback order (CSV)"
              value={settings.AION_WEB_SEARCH_FALLBACK_ORDER || "brave,searxng"}
              onChange={(v) => handleUpdate("AION_WEB_SEARCH_FALLBACK_ORDER", v)}
            />
            <ConfigInput
              label="Max results"
              value={settings.AION_WEB_SEARCH_MAX_RESULTS || "8"}
              onChange={(v) => handleUpdate("AION_WEB_SEARCH_MAX_RESULTS", v)}
            />
            <ConfigInput
              label="Search timeout (sec)"
              value={settings.AION_WEB_SEARCH_TIMEOUT_SEC || "30"}
              onChange={(v) => handleUpdate("AION_WEB_SEARCH_TIMEOUT_SEC", v)}
            />
            <ConfigInput
              label="Fetch max chars"
              value={settings.AION_WEB_FETCH_MAX_CHARS || "120000"}
              onChange={(v) => handleUpdate("AION_WEB_FETCH_MAX_CHARS", v)}
            />
            <ConfigInput
              label="Fetch allowlist regex (optional)"
              value={settings.AION_WEB_FETCH_ALLOWLIST_REGEX || ""}
              onChange={(v) => handleUpdate("AION_WEB_FETCH_ALLOWLIST_REGEX", v)}
            />
            <ConfigInput
              label="Org allowed hosts (CSV, optional *.suffix)"
              value={settings.AION_WEB_SEARCH_ALLOWED_HOSTS || ""}
              onChange={(v) => handleUpdate("AION_WEB_SEARCH_ALLOWED_HOSTS", v)}
              description="Soffitto domini per web_search / web_fetch_page quando enforcement attivo"
            />
            <ConfigToggle
              label="Enforce global host allowlist"
              enabled={settings.AION_WEB_SEARCH_ENFORCE_GLOBAL_ALLOWLIST === "1"}
              onChange={(e) => handleUpdate("AION_WEB_SEARCH_ENFORCE_GLOBAL_ALLOWLIST", e ? "1" : "0")}
            />
            <ConfigToggle
              label="Require client web opt-in"
              enabled={settings.AION_WEB_SEARCH_REQUIRE_CLIENT_OPT_IN === "1"}
              onChange={(e) => handleUpdate("AION_WEB_SEARCH_REQUIRE_CLIENT_OPT_IN", e ? "1" : "0")}
            />
            <ConfigInput
              label="Native tool registry path"
              value={settings.AION_NATIVE_TOOL_REGISTRY_PATH || "config/native_tool_registry.yaml"}
              onChange={(v) => handleUpdate("AION_NATIVE_TOOL_REGISTRY_PATH", v)}
            />
          </div>
        </section>

        {/* LTM & Memory */}
        <section className="glass-card p-6 border-[#262626] hover:border-purple-500/30 transition-colors group">
          <div className="flex items-center gap-3 mb-6">
            <div className="w-10 h-10 rounded-xl bg-purple-500/10 flex items-center justify-center border border-purple-500/20 group-hover:scale-110 transition-transform">
              <Zap className="w-5 h-5 text-purple-500" />
            </div>
            <div>
              <h3 className="font-bold text-white">Autonomous Memory</h3>
              <p className="text-[10px] text-gray-500 uppercase font-bold tracking-wider">LTM & Embeddings</p>
            </div>
          </div>

          <div className="space-y-4">
            <ConfigToggle
              label="LTM Retrieval"
              enabled={settings.AION_LTM_RETRIEVAL === "1"}
              onChange={(e) => handleUpdate('AION_LTM_RETRIEVAL', e ? "1" : "0")}
            />
            <ConfigToggle
              label="LTM Auto-Extraction"
              enabled={settings.AION_LTM_EXTRACT === "1"}
              onChange={(e) => handleUpdate('AION_LTM_EXTRACT', e ? "1" : "0")}
            />
            <div className="space-y-1.5">
              <label className="text-[10px] font-bold uppercase text-gray-500 tracking-wider">Embedding Provider (AION_EMBEDDINGS_PROVIDER)</label>
              <select
                value={settings.AION_EMBEDDINGS_PROVIDER || "openai"}
                onChange={(e) => handleEmbeddingsProviderChange(e.target.value)}
                className="w-full bg-[#0d0d0d] border border-[#262626] rounded-xl px-4 py-2.5 text-sm text-gray-200 focus:border-blue-500/50 focus:ring-1 focus:ring-blue-500/20 outline-none transition-all font-mono appearance-none cursor-pointer"
              >
                <option value="openai">OpenAI-Compatible</option>
                <option value="google">Google</option>
              </select>
            </div>
            <div className="space-y-1.5">
              <label className="text-[10px] font-bold uppercase text-gray-500 tracking-wider">Embedding Service URL (AION_EMBEDDING_URL)</label>
              <input
                type="text"
                value={settings.AION_EMBEDDING_URL || ""}
                onChange={(e) => {
                  handleUpdate("AION_EMBEDDING_URL", e.target.value);
                  resetEmbProbeState();
                }}
                className="w-full bg-[#0d0d0d] border border-[#262626] rounded-xl px-4 py-2.5 text-sm text-gray-200 focus:border-blue-500/50 focus:ring-1 focus:ring-blue-500/20 outline-none transition-all font-mono"
                placeholder={
                  (settings.AION_EMBEDDINGS_PROVIDER || "openai") === "google"
                    ? "https://generativelanguage.googleapis.com/v1beta/models"
                    : "http://localhost:11434/v1/embeddings or https://api.openai.com/v1/embeddings"
                }
              />
              <p className="text-[11px] text-gray-500">
                Base URL or full <span className="font-mono">/v1/embeddings</span> path — probe uses GET /v1/models on the base.
              </p>
            </div>
            {(settings.AION_EMBEDDINGS_PROVIDER || "openai") !== "google" && (
              <div className="space-y-1.5 font-mono">
                <label className="text-[10px] font-bold uppercase text-gray-500 tracking-wider">Embedding API Key (AION_EMBEDDINGS_API_KEY)</label>
                <div className="relative">
                  <input
                    type={showApiKey ? "text" : "password"}
                    value={settings.AION_EMBEDDINGS_API_KEY || ""}
                    onChange={(e) => {
                      handleUpdate("AION_EMBEDDINGS_API_KEY", e.target.value);
                      resetEmbProbeState();
                    }}
                    placeholder="Enter Embedding API Key"
                    className="w-full bg-[#0d0d0d] border border-[#262626] rounded-xl pl-4 pr-10 py-2.5 text-sm text-gray-200 focus:border-blue-500/50 focus:ring-1 focus:ring-blue-500/20 outline-none transition-all font-mono"
                    autoComplete="new-password"
                  />
                  <button
                    type="button"
                    onClick={() => setShowApiKey(!showApiKey)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-300 transition-colors cursor-pointer"
                  >
                    {showApiKey ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                  </button>
                </div>
              </div>
            )}
            <div className="flex flex-wrap items-center gap-3">
              <button
                type="button"
                onClick={probeEmbConnection}
                disabled={embProbing}
                className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl border border-purple-500/30 bg-purple-500/10 text-purple-300 text-sm font-semibold hover:bg-purple-500/20 transition-all disabled:opacity-50"
              >
                {embProbing ? <Loader2 className="w-4 h-4 animate-spin" /> : <Zap className="w-4 h-4" />}
                Test connection & discover models
              </button>
              {embConnectionTested && embProbeLatencyMs != null && (
                <span className="text-xs text-emerald-400 font-mono">
                  Connection OK · {embProbeLatencyMs}ms
                  {embDiscoveredModelIds.length > 0
                    ? ` · ${embDiscoveredModelIds.length} embedding models`
                    : " · enter model manually"}
                </span>
              )}
            </div>
            {!embConnectionTested ? (
              <div className="p-4 rounded-xl border border-dashed border-[#262626] bg-[#0a0a0a]/60 text-sm text-gray-500 flex items-start gap-3">
                <Info className="w-5 h-5 shrink-0 mt-0.5 text-gray-600" />
                <span>Test the embedding endpoint to discover available models.</span>
              </div>
            ) : embManualModelEntry ? (
              <div className="space-y-1.5">
                <label className="text-[10px] font-bold uppercase text-gray-500 tracking-wider">Embedding model (manual)</label>
                <input
                  type="text"
                  value={settings.AION_EMBEDDING_MODEL || ""}
                  onChange={(e) => handleUpdate("AION_EMBEDDING_MODEL", e.target.value)}
                  className="w-full bg-[#0d0d0d] border border-[#262626] rounded-xl px-4 py-2.5 text-sm text-gray-200 focus:border-purple-500/50 focus:ring-1 focus:ring-purple-500/20 outline-none transition-all font-mono"
                  placeholder="e.g. text-embedding-3-small, qwen3-embedding"
                />
              </div>
            ) : (
              <div className="space-y-1.5">
                <label className="text-[10px] font-bold uppercase text-gray-500 tracking-wider">Embedding model (auto-discovered)</label>
                <select
                  value={settings.AION_EMBEDDING_MODEL || ""}
                  onChange={(e) => handleUpdate("AION_EMBEDDING_MODEL", e.target.value)}
                  className="w-full bg-[#0d0d0d] border border-[#262626] rounded-xl px-4 py-2.5 text-sm text-gray-200 focus:border-purple-500/50 focus:ring-1 focus:ring-blue-500/20 outline-none transition-all font-mono cursor-pointer"
                >
                  {embDiscoveredModelIds.map((id) => (
                    <option key={id} value={id}>
                      {id}
                    </option>
                  ))}
                </select>
              </div>
            )}
          </div>
        </section>

        {/* OCR Document Processing */}
        <section className="glass-card p-6 border-[#262626] hover:border-amber-500/30 transition-colors group md:col-span-2">
          <div className="flex items-center gap-3 mb-6">
            <div className="w-10 h-10 rounded-xl bg-amber-500/10 flex items-center justify-center border border-amber-500/20 group-hover:scale-110 transition-transform">
              <Eye className="w-5 h-5 text-amber-500" />
            </div>
            <div>
              <h3 className="font-bold text-white">OCR Document Processing</h3>
              <p className="text-[10px] text-gray-500 uppercase font-bold tracking-wider">
                MCP OCR is always available — choose local or remote vision extraction
              </p>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
            <button
              type="button"
              onClick={() => handleOcrModeChange("remote")}
              className={`p-4 rounded-xl border text-left flex flex-col gap-2 transition-all ${ocrMode === "remote"
                ? "bg-amber-500/5 border-amber-500/40 text-amber-200"
                : "bg-[#070707] border-[#222] text-gray-400 hover:text-white"
                }`}
            >
              <div className="flex items-center gap-2 font-bold text-sm">
                <Cloud className="w-4 h-4" /> Remote vision OCR (recommended)
              </div>
              <span className="text-xs opacity-90 leading-relaxed">
                OpenAI-compatible vLLM vision server (e.g. GLM-OCR). Writes <span className="font-mono">AION_OCR_*</span> variables.
              </span>
            </button>

            <button
              type="button"
              onClick={() => handleOcrModeChange("local")}
              className={`p-4 rounded-xl border text-left flex flex-col gap-2 transition-all ${ocrMode === "local"
                ? "bg-amber-500/5 border-amber-500/40 text-amber-200"
                : "bg-[#070707] border-[#222] text-gray-400 hover:text-white"
                }`}
            >
              <div className="flex items-center gap-2 font-bold text-sm">
                <ScanLine className="w-4 h-4" /> Local Python OCR (basic)
              </div>
              <span className="text-xs opacity-90 leading-relaxed">
                PDF via <span className="font-mono">pymupdf4llm</span>, images via <span className="font-mono">pytesseract</span>. Clears <span className="font-mono">AION_OCR_*</span> on save.
              </span>
            </button>
          </div>

          {ocrMode === "remote" ? (
            <div className="space-y-4">
              <div className="space-y-1.5">
                <label className="text-[10px] font-bold uppercase text-gray-500 tracking-wider">OCR Service Base URL (AION_OCR_BASE_URL)</label>
                <input
                  type="text"
                  value={settings.AION_OCR_BASE_URL || ""}
                  onChange={(e) => {
                    handleUpdate("AION_OCR_BASE_URL", e.target.value);
                    resetOcrProbeState();
                  }}
                  className="w-full bg-[#0d0d0d] border border-[#262626] rounded-xl px-4 py-2.5 text-sm text-gray-200 focus:border-amber-500/50 focus:ring-1 focus:ring-amber-500/20 outline-none transition-all font-mono"
                  placeholder="e.g. http://localhost:8002/v1"
                />
              </div>
              <div className="space-y-1.5 font-mono">
                <label className="text-[10px] font-bold uppercase text-gray-500 tracking-wider">OCR API Token (AION_OCR_API_KEY)</label>
                <div className="relative">
                  <input
                    type={showOcrApiKey ? "text" : "password"}
                    value={settings.AION_OCR_API_KEY || ""}
                    onChange={(e) => {
                      handleUpdate("AION_OCR_API_KEY", e.target.value);
                      resetOcrProbeState();
                    }}
                    placeholder="Bearer token (any non-empty value if auth is disabled)"
                    className="w-full bg-[#0d0d0d] border border-[#262626] rounded-xl pl-4 pr-10 py-2.5 text-sm text-gray-200 focus:border-amber-500/50 focus:ring-1 focus:ring-amber-500/20 outline-none transition-all font-mono"
                    autoComplete="new-password"
                  />
                  <button
                    type="button"
                    onClick={() => setShowOcrApiKey(!showOcrApiKey)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-300 transition-colors cursor-pointer"
                  >
                    {showOcrApiKey ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                  </button>
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-3">
                <button
                  type="button"
                  onClick={probeOcrConnection}
                  disabled={ocrProbing}
                  className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl border border-amber-500/30 bg-amber-500/10 text-amber-300 text-sm font-semibold hover:bg-amber-500/20 transition-all disabled:opacity-50"
                >
                  {ocrProbing ? <Loader2 className="w-4 h-4 animate-spin" /> : <Zap className="w-4 h-4" />}
                  Test connection & discover models
                </button>
                {ocrConnectionTested && ocrProbeLatencyMs != null && (
                  <span className="text-xs text-emerald-400 font-mono">
                    Connection OK · {ocrProbeLatencyMs}ms
                    {ocrDiscoveredModelIds.length > 0
                      ? ` · ${ocrDiscoveredModelIds.length} vision/OCR models`
                      : " · enter model manually"}
                  </span>
                )}
              </div>
              {!ocrConnectionTested ? (
                <div className="p-4 rounded-xl border border-dashed border-[#262626] bg-[#0a0a0a]/60 text-sm text-gray-500 flex items-start gap-3">
                  <Info className="w-5 h-5 shrink-0 mt-0.5 text-gray-600" />
                  <span>Test the vision OCR endpoint to discover models.</span>
                </div>
              ) : ocrManualModelEntry ? (
                <div className="space-y-1.5">
                  <label className="text-[10px] font-bold uppercase text-gray-500 tracking-wider">OCR model (manual)</label>
                  <input
                    type="text"
                    value={settings.AION_OCR_MODEL || ""}
                    onChange={(e) => handleUpdate("AION_OCR_MODEL", e.target.value)}
                    className="w-full bg-[#0d0d0d] border border-[#262626] rounded-xl px-4 py-2.5 text-sm text-gray-200 focus:border-amber-500/50 focus:ring-1 focus:ring-amber-500/20 outline-none transition-all font-mono"
                    placeholder="e.g. zai-org/GLM-OCR"
                  />
                </div>
              ) : (
                <div className="space-y-1.5">
                  <label className="text-[10px] font-bold uppercase text-gray-500 tracking-wider">OCR model (auto-discovered)</label>
                  <select
                    value={settings.AION_OCR_MODEL || ""}
                    onChange={(e) => handleUpdate("AION_OCR_MODEL", e.target.value)}
                    className="w-full bg-[#0d0d0d] border border-[#262626] rounded-xl px-4 py-2.5 text-sm text-gray-200 focus:border-amber-500/50 focus:ring-1 focus:ring-amber-500/20 outline-none transition-all font-mono cursor-pointer"
                  >
                    {ocrDiscoveredModelIds.map((id) => (
                      <option key={id} value={id}>
                        {id}
                      </option>
                    ))}
                  </select>
                </div>
              )}
              {ocrConnectionTested && (settings.AION_OCR_MODEL || "").trim() && (
                <>
                  <ConfigInput
                    label="OCR Max Tokens (AION_OCR_MAX_TOKENS)"
                    value={settings.AION_OCR_MAX_TOKENS || ""}
                    onChange={(v) => handleUpdate("AION_OCR_MAX_TOKENS", v)}
                  />
                  <ConfigInput
                    label="OCR Timeout in Seconds (AION_OCR_TIMEOUT)"
                    value={settings.AION_OCR_TIMEOUT || ""}
                    onChange={(v) => handleUpdate("AION_OCR_TIMEOUT", v)}
                  />
                  <ConfigInput
                    label="OCR Max Image Bytes (AION_OCR_MAX_IMAGE_BYTES)"
                    value={settings.AION_OCR_MAX_IMAGE_BYTES || ""}
                    onChange={(v) => handleUpdate("AION_OCR_MAX_IMAGE_BYTES", v)}
                  />
                </>
              )}
            </div>
          ) : (
            <div className="p-5 rounded-2xl border border-dashed border-[#262626] bg-[#0d0d0d]/30 text-sm text-gray-400 flex items-start gap-3">
              <Info className="w-8 h-8 shrink-0 text-gray-600" />
              <div className="space-y-2">
                <p>The OCR MCP tool stays active with local extractors:</p>
                <ul className="list-disc list-inside text-xs text-gray-500 space-y-1">
                  <li>PDF → <span className="font-mono">pymupdf4llm</span></li>
                  <li>Images → <span className="font-mono">pytesseract</span></li>
                </ul>
                <p className="text-xs text-amber-400/80">
                  No <span className="font-mono">AION_OCR_*</span> variables are saved in local mode.
                </p>
              </div>
            </div>
          )}
        </section>

        {/* Sandbox Security & Filesystem Exec Policy */}
        <section className="glass-card p-6 border-[#262626] hover:border-amber-500/30 transition-colors group md:col-span-2 animate-in fade-in duration-500">
          <div className="flex items-center justify-between mb-6">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-amber-500/10 flex items-center justify-center border border-amber-500/20 group-hover:scale-110 transition-transform">
                <ShieldAlert className="w-5 h-5 text-amber-500" />
              </div>
              <div>
                <h3 className="font-bold text-white">Sandbox Security & Filesystem Policy</h3>
                <p className="text-[10px] text-gray-500 uppercase font-bold tracking-wider">Configure sandbox boundaries and command allowlists</p>
              </div>
            </div>
            <button
              onClick={() => setFsPolicyEnabled(!fsPolicyEnabled)}
              className={`w-10 h-5 rounded-full transition-all flex items-center px-1 cursor-pointer ${fsPolicyEnabled ? 'bg-amber-500' : 'bg-gray-700'}`}
              title={fsPolicyEnabled ? "Disable Filesystem Policy" : "Enable Filesystem Policy"}
            >
              <div className={`w-3 h-3 bg-white rounded-full transition-transform ${fsPolicyEnabled ? 'translate-x-5' : 'translate-x-0'}`} />
            </button>
          </div>

          {fsPolicyEnabled ? (
            <div className="space-y-6">
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                {/* Dev Template Card */}
                <button
                  type="button"
                  onClick={() => setSelectedPolicyType("dev")}
                  className={`p-4 rounded-xl border text-left flex flex-col gap-1.5 transition-all cursor-pointer ${selectedPolicyType === "dev"
                    ? "bg-amber-500/5 border-amber-500/30 text-amber-300 shadow-md shadow-amber-500/5"
                    : "bg-[#070707] border-[#222] text-gray-400 hover:text-white"
                    }`}
                >
                  <div className="flex items-center gap-2 font-bold text-sm">
                    <Zap className="w-4 h-4" /> Development Policy
                  </div>
                  <span className="text-xs opacity-80">
                    Enables a minimal allowlist of commands (grep, wc, sort, python3) for local agent operations.
                  </span>
                </button>

                {/* Production Template Card */}
                <button
                  type="button"
                  onClick={() => setSelectedPolicyType("production")}
                  className={`p-4 rounded-xl border text-left flex flex-col gap-1.5 transition-all cursor-pointer ${selectedPolicyType === "production"
                    ? "bg-amber-500/5 border-amber-500/30 text-amber-300 shadow-md shadow-amber-500/5"
                    : "bg-[#070707] border-[#222] text-gray-400 hover:text-white"
                    }`}
                >
                  <div className="flex items-center gap-2 font-bold text-sm">
                    <Lock className="w-4 h-4" /> Production Policy
                  </div>
                  <span className="text-xs opacity-80">
                    Advanced template with detailed descriptions, strict path boundaries, and hardened execute constraints.
                  </span>
                </button>

                {/* Custom Policy Card */}
                <button
                  type="button"
                  onClick={() => setSelectedPolicyType("custom")}
                  className={`p-4 rounded-xl border text-left flex flex-col gap-1.5 transition-all cursor-pointer ${selectedPolicyType === "custom"
                    ? "bg-amber-500/5 border-amber-500/30 text-amber-300 shadow-md shadow-amber-500/5"
                    : "bg-[#070707] border-[#222] text-gray-400 hover:text-white"
                    }`}
                >
                  <div className="flex items-center gap-2 font-bold text-sm">
                    <SettingsIcon className="w-4 h-4" /> Custom Policy
                  </div>
                  <span className="text-xs opacity-80">
                    Manually edit and write custom command rules and directory access policies to meet your specific needs.
                  </span>
                </button>
              </div>

              {/* View/Edit – visual policy editor */}
              <div className="space-y-3">
                <div className="flex justify-between items-center">
                  <label className="text-[10px] font-bold uppercase text-gray-500 tracking-wider">
                    {selectedPolicyType === "custom" ? "Edit Policy" : "Policy Blueprint Preview (Read Only)"}
                  </label>
                  <span className="text-[10px] text-gray-500 font-mono">config/fs_policy.yaml</span>
                </div>

                {selectedPolicyType !== "custom" && (
                  <div className="p-3 bg-amber-500/10 border border-amber-500/20 rounded-xl flex items-center justify-between text-xs text-amber-400">
                    <div className="flex items-center gap-2">
                      <Info className="w-4 h-4 shrink-0" />
                      <span>You are viewing a standard template. To make edits, switch to <strong>Custom</strong>.</span>
                    </div>
                    <button
                      type="button"
                      onClick={() => {
                        setCustomYaml(selectedPolicyType === "dev" ? devTemplateYaml : exampleTemplateYaml);
                        setSelectedPolicyType("custom");
                      }}
                      className="px-3 py-1 bg-amber-500/20 hover:bg-amber-500/30 border border-amber-500/30 rounded-lg text-amber-300 font-bold transition-all text-xs active:scale-95 cursor-pointer"
                    >
                      Derive Custom from Template
                    </button>
                  </div>
                )}

                <PolicyEditor
                  value={
                    selectedPolicyType === "dev"
                      ? devTemplateYaml
                      : selectedPolicyType === "production"
                        ? exampleTemplateYaml
                        : customYaml
                  }
                  onChange={(yaml) => {
                    if (selectedPolicyType === "custom") {
                      setCustomYaml(yaml);
                    }
                  }}
                  readOnly={selectedPolicyType !== "custom"}
                />
              </div>

              {/* Save policy changes */}
              <div className="flex justify-end pt-2">
                <button
                  onClick={saveFsPolicy}
                  disabled={policySaving}
                  className={`flex items-center gap-2 px-6 py-2.5 rounded-xl font-bold transition-all shadow-lg cursor-pointer ${policySaving
                    ? 'bg-gray-800 text-gray-500 cursor-not-allowed'
                    : 'bg-amber-600 hover:bg-amber-500 text-white shadow-amber-500/20 active:scale-95'
                    }`}
                >
                  {policySaving ? (
                    <div className="w-4 h-4 border-2 border-white/20 border-t-white rounded-full animate-spin" />
                  ) : <Save className="w-4 h-4" />}
                  {policySaving ? "Committing Changes..." : "Commit Changes"}
                </button>
              </div>
            </div>
          ) : (
            <div className="p-6 rounded-2xl border border-dashed border-[#262626] bg-[#0d0d0d]/30 text-center text-gray-500 text-sm">
              <Info className="w-8 h-8 mx-auto mb-2 text-gray-600" />
              Filesystem Policy is disabled. All filesystem and command execution restrictions are off.
              <div className="flex justify-center mt-4">
                <button
                  onClick={saveFsPolicy}
                  disabled={policySaving}
                  className="flex items-center gap-2 px-6 py-2.5 rounded-xl font-bold bg-amber-600 hover:bg-amber-500 text-white transition-all active:scale-95 cursor-pointer"
                >
                  {policySaving ? (
                    <div className="w-4 h-4 border-2 border-white/20 border-t-white rounded-full animate-spin" />
                  ) : <Save className="w-4 h-4" />}
                  {policySaving ? "Committing Changes..." : "Commit Changes"}
                </button>
              </div>
            </div>
          )}
        </section>

      </div>


      {restarting && (
        <div className="fixed inset-0 bg-black/80 backdrop-blur-md flex flex-col items-center justify-center z-50 animate-in fade-in duration-300">
          <div className="bg-[#0d0d0d] border border-[#262626] rounded-3xl p-8 max-w-md w-full text-center space-y-6 shadow-2xl shadow-blue-500/10">
            <div className="relative w-20 h-20 mx-auto">
              <div className="absolute inset-0 border-4 border-blue-500/20 rounded-full" />
              <div className="absolute inset-0 border-4 border-t-blue-500 rounded-full animate-spin" />
            </div>
            <div className="space-y-2">
              <h3 className="text-xl font-bold text-white">Reinitializing AI Kernel</h3>
              <p className="text-sm text-gray-500">
                The API container is restarting to apply the new model configurations. This usually takes about 5 to 10 seconds.
              </p>
            </div>
            <div className="text-[10px] font-bold uppercase tracking-widest text-blue-500 bg-blue-500/10 px-3 py-1.5 rounded-full inline-block animate-pulse">
              Waiting for health check...
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function ConfigInput({ label, value, onChange, description }: { label: string, value: string, onChange: (v: string) => void, description?: string }) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between">
        <label className="text-[10px] font-bold uppercase text-gray-500 tracking-wider">{label}</label>
        {description && <div className="relative group/tooltip cursor-help">
          <Info className="w-3 h-3 text-gray-600" />
          <div className="absolute bottom-full right-0 mb-2 w-48 p-2 bg-black border border-[#262626] rounded-lg text-[10px] text-gray-400 invisible group-hover/tooltip:visible shadow-xl z-50">
            {description}
          </div>
        </div>}
      </div>
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full bg-[#0d0d0d] border border-[#262626] rounded-xl px-4 py-2.5 text-sm text-gray-200 focus:border-blue-500/50 focus:ring-1 focus:ring-blue-500/20 outline-none transition-all font-mono"
      />
    </div>
  );
}

function ConfigToggle({ label, enabled, onChange }: { label: string, enabled: boolean, onChange: (v: boolean) => void }) {
  return (
    <div className="flex items-center justify-between p-3 bg-white/5 rounded-xl border border-white/10 hover:border-white/20 transition-colors">
      <span className="text-xs font-bold text-gray-400 uppercase tracking-tight">{label}</span>
      <button
        onClick={() => onChange(!enabled)}
        className={`w-10 h-5 rounded-full transition-all flex items-center px-1 ${enabled ? 'bg-blue-600' : 'bg-gray-700'}`}
      >
        <div className={`w-3 h-3 bg-white rounded-full transition-transform ${enabled ? 'translate-x-5' : 'translate-x-0'}`} />
      </button>
    </div>
  );
}
