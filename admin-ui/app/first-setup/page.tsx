"use client";

import { useEffect, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import {
  Server,
  Zap,
  Search,
  ShieldAlert,
  Eye,
  EyeOff,
  ChevronRight,
  ChevronLeft,
  Sparkles,
  Check,
  Loader2,
  KeyRound,
} from "lucide-react";
import { apiBase } from "@/lib/api";
import { apiFetch } from "@/lib/api/headers";
import { fetchAuthStatus } from "@/lib/auth/status";
import { cn } from "@/lib/cn";
import { SsoConfigPanel } from "@/components/sso/SsoConfigPanel";
import { AdminBrand } from "@/components/brand/AdminBrand";
import { AuthAlert, AuthHeading, AuthShell, SsoProviderIcon } from "@/components/auth/AuthShell";
import { inputCls, outlineBtn, solidBtn } from "@/components/ui/classes";
import { Select } from "@/components/ui/Select";
import { ChoiceList, Field, Group, ModelField, Mono, Note, ProbeBar, Switch } from "@/components/settings/ui";
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

type Step = "llm" | "embeddings" | "ocr" | "search" | "policy" | "sso" | "review";

const monoInputCls = cn(inputCls, "font-mono text-[13px]");
const fieldGridCls = "grid grid-cols-1 gap-x-5 gap-y-5 md:grid-cols-2";

export default function FirstSetupPage() {
  const router = useRouter();
  const [currentStep, setCurrentStep] = useState<Step>("llm");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const [restarting, setRestarting] = useState(false);

  // --- Step SSO State ---
  // "none" = SSO disattivato; altrimenti provider scelto (va verificato prima di procedere)
  const [ssoProvider, setSsoProvider] = useState<"none" | "microsoft" | "google">("none");
  const [ssoValidated, setSsoValidated] = useState(false);
  const ssoStatus = { enabled: ssoProvider !== "none", validated: ssoProvider !== "none" && ssoValidated };

  // --- Step 1: LLM Provider State ---
  const [llmForm, setLlmForm] = useState({
    slug: "default-llm",
    display_name: "Default LLM",
    provider: "openai",
    model_name: "",
    api_base_url: "",
    api_key: "",
    timeout: 120,
    max_chat_tokens: 8192,
    thinking_token_budget: 12000,
  });
  const [showLlmKey, setShowLlmKey] = useState(false);
  const [llmProbing, setLlmProbing] = useState(false);
  const [llmProbeResult, setLlmProbeResult] = useState<LlmProbeResponse | null>(null);
  const [llmProbeLatencyMs, setLlmProbeLatencyMs] = useState<number | null>(null);
  const [llmConnectionTested, setLlmConnectionTested] = useState(false);
  const [llmDiscoveredModelIds, setLlmDiscoveredModelIds] = useState<string[]>([]);
  const [llmManualModelEntry, setLlmManualModelEntry] = useState(false);

  // --- Step 2: Embeddings State ---
  const [embForm, setEmbForm] = useState({
    provider: "openai",
    model: "",
    url: "",
    api_key: "",
  });
  const [showEmbKey, setShowEmbKey] = useState(false);
  const [embProbing, setEmbProbing] = useState(false);
  const [embProbeResult, setEmbProbeResult] = useState<LlmProbeResponse | null>(null);
  const [embProbeLatencyMs, setEmbProbeLatencyMs] = useState<number | null>(null);
  const [embConnectionTested, setEmbConnectionTested] = useState(false);
  const [embDiscoveredModelIds, setEmbDiscoveredModelIds] = useState<string[]>([]);
  const [embManualModelEntry, setEmbManualModelEntry] = useState(false);

  // --- Step 3: OCR State ---
  const [ocrForm, setOcrForm] = useState({
    base_url: "",
    model: "",
    api_key: "",
    max_tokens: 8192,
    timeout: 120,
    max_image_bytes: 20971520,
  });
  const [ocrMode, setOcrMode] = useState<OcrMode>("local");
  const [showOcrKey, setShowOcrKey] = useState(false);
  const [ocrProbing, setOcrProbing] = useState(false);
  const [ocrProbeResult, setOcrProbeResult] = useState<LlmProbeResponse | null>(null);
  const [ocrProbeLatencyMs, setOcrProbeLatencyMs] = useState<number | null>(null);
  const [ocrConnectionTested, setOcrConnectionTested] = useState(false);
  const [ocrDiscoveredModelIds, setOcrDiscoveredModelIds] = useState<string[]>([]);
  const [ocrManualModelEntry, setOcrManualModelEntry] = useState(false);

  // --- Step 4: Web Search State ---
  const [searchForm, setSearchForm] = useState({
    tavily_enabled: true,
    tavily_key: "",
    brave_enabled: false,
    brave_key: "",
    searxng_enabled: false,
    searxng_url: "",
    default_provider: "tavily",
    fallback_order: "brave,searxng",
  });
  const [showTavilyKey, setShowTavilyKey] = useState(false);
  const [showBraveKey, setShowBraveKey] = useState(false);

  // --- Step 5: Filesystem Policy State ---
  const [policyEnabled, setPolicyEnabled] = useState(true);
  const [policyTemplate, setPolicyTemplate] = useState<"dev" | "example">("dev");
  const [policyYaml, setPolicyYaml] = useState("");
  const [devTemplateYaml, setDevTemplateYaml] = useState("");
  const [exampleTemplateYaml, setExampleTemplateYaml] = useState("");

  // Load policy templates from backend on mount
  useEffect(() => {
    async function loadPolicyData() {
      try {
        const res = await apiFetch(`${apiBase()}/admin/settings/fs-policy`);
        if (res.ok) {
          const data = await res.json();
          setDevTemplateYaml(data.dev_template);
          setExampleTemplateYaml(data.example_template);
          setPolicyYaml(data.dev_template || data.yaml_content);
        }
      } catch (err) {
        console.error("Failed to load filesystem policy templates", err);
      }
    }
    loadPolicyData();
  }, []);

  const handleTemplateChange = (type: "dev" | "example") => {
    setPolicyTemplate(type);
    if (type === "dev") {
      setPolicyYaml(devTemplateYaml);
    } else {
      setPolicyYaml(exampleTemplateYaml);
    }
  };

  const resetLlmProbeState = () => {
    setLlmProbeResult(null);
    setLlmProbeLatencyMs(null);
    setLlmConnectionTested(false);
    setLlmDiscoveredModelIds([]);
    setLlmManualModelEntry(false);
    setLlmForm((prev) => ({ ...prev, model_name: "" }));
  };

  const resetEmbProbeState = () => {
    setEmbProbeResult(null);
    setEmbProbeLatencyMs(null);
    setEmbConnectionTested(false);
    setEmbDiscoveredModelIds([]);
    setEmbManualModelEntry(false);
    setEmbForm((prev) => ({ ...prev, model: "" }));
  };

  const applyLlmModelSelection = (modelId: string, result: LlmProbeResponse | null) => {
    const hint = hintForModel(result, modelId);
    setLlmForm((prev) => ({
      ...prev,
      model_name: modelId,
      display_name: formatModelDisplayName(modelId),
      slug: slugFromModelId(modelId, prev.provider === "vllm" ? "local" : "default"),
      max_chat_tokens: hint?.suggested_max_chat_tokens ?? prev.max_chat_tokens,
    }));
  };

  const handleLlmProviderChange = (provider: string) => {
    const providerLabels: Record<string, { slug: string; display_name: string }> = {
      openai: { slug: "default-llm", display_name: "Default LLM" },
      anthropic: { slug: "default-llm", display_name: "Default LLM" },
      gemini: { slug: "default-llm", display_name: "Default LLM" },
      ollama: { slug: "local-ollama", display_name: "Ollama LLM" },
      vllm: { slug: "local-vllm", display_name: "vLLM Model" },
    };
    const meta = providerLabels[provider] ?? providerLabels.openai;
    setLlmForm((prev) => ({
      ...prev,
      provider,
      slug: meta.slug,
      display_name: meta.display_name,
      model_name: "",
      max_chat_tokens: provider === "ollama" ? 4096 : 8192,
      thinking_token_budget: provider === "gemini" || provider === "ollama" ? 0 : 12000,
    }));
    resetLlmProbeState();
  };

  const handleEmbProviderChange = (provider: string) => {
    setEmbForm((prev) => ({
      ...prev,
      provider,
      model: "",
      url: "",
    }));
    resetEmbProbeState();
  };

  const probeLlmConnection = async (): Promise<boolean> => {
    if (providerNeedsBaseUrl(llmForm.provider) && !llmForm.api_base_url.trim()) {
      setError("API Base URL is required for this provider.");
      return false;
    }
    if (llmForm.provider !== "ollama" && !llmForm.api_key.trim()) {
      setError("API Key is required to test the connection.");
      return false;
    }

    setLlmProbing(true);
    setError(null);
    setLlmProbeLatencyMs(null);
    try {
      const result = await runModelProbe(apiFetch, apiBase(), {
        provider: llmForm.provider,
        api_base_url: llmForm.api_base_url.trim() || null,
        api_key: llmForm.api_key.trim() || null,
      });
      const allIds = modelIdsFromProbe(result);
      const chatIds = filterModelsForKind(allIds, "chat");
      setLlmProbeResult(result);
      setLlmDiscoveredModelIds(chatIds);
      setLlmConnectionTested(true);
      setLlmProbeLatencyMs(result.latency_ms);
      setLlmForm((prev) => ({
        ...prev,
        api_base_url: result.base_url || prev.api_base_url,
      }));

      if (chatIds.length > 0) {
        setLlmManualModelEntry(false);
        applyLlmModelSelection(pickDefaultModel(allIds, "chat"), result);
      } else {
        setLlmManualModelEntry(true);
        setLlmForm((prev) => ({ ...prev, model_name: "" }));
      }

      if (result.warning) {
        setError(result.warning);
      }
      return true;
    } catch (err: any) {
      resetLlmProbeState();
      setError(err.message || "Connection test failed.");
      return false;
    } finally {
      setLlmProbing(false);
    }
  };

  const probeEmbConnection = async (): Promise<boolean> => {
    const probeBase = probeBaseUrlFromServiceUrl(embForm.url);
    if (!probeBase) {
      setError("Embedding service URL is required to test the connection.");
      return false;
    }
    const isSelfHosted = embForm.provider === "vllm" || embForm.provider === "ollama";
    if (embForm.provider !== "google" && !isSelfHosted && !embForm.api_key.trim()) {
      const host = probeBase.replace(/^https?:\/\//i, "").split(/[/:]/)[0].toLowerCase();
      if (!["localhost", "127.0.0.1", "host.docker.internal", "gateway.docker.internal"].includes(host) && !host.endsWith(".local") && !host.endsWith(".internal")) {
        setError("API Key is required to test the connection.");
        return false;
      }
    }

    setEmbProbing(true);
    setError(null);
    setEmbProbeLatencyMs(null);
    try {
      const result = await runModelProbe(apiFetch, apiBase(), {
        provider: embeddingProviderToProbeProvider(embForm.provider),
        api_base_url: probeBase,
        api_key: embForm.api_key.trim() || null,
      });
      const allIds = modelIdsFromProbe(result);
      const embIds = filterModelsForKind(allIds, "embedding");
      setEmbProbeResult(result);
      setEmbDiscoveredModelIds(embIds);
      setEmbConnectionTested(true);
      setEmbProbeLatencyMs(result.latency_ms);
      setEmbForm((prev) => ({
        ...prev,
        url: embeddingServiceUrlFromProbeBase(result.base_url || probeBase),
      }));

      if (embIds.length > 0) {
        setEmbManualModelEntry(false);
        setEmbForm((prev) => ({
          ...prev,
          model: pickDefaultModel(allIds, "embedding"),
        }));
      } else {
        setEmbManualModelEntry(true);
        setEmbForm((prev) => ({ ...prev, model: "" }));
      }

      if (result.warning) {
        setError(result.warning);
      }
      return true;
    } catch (err: any) {
      resetEmbProbeState();
      setError(err.message || "Connection test failed.");
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
    setOcrForm((prev) => ({ ...prev, model: "" }));
  };

  const handleOcrModeChange = (mode: OcrMode) => {
    setOcrMode(mode);
    resetOcrProbeState();
    if (mode === "local") {
      setOcrForm((prev) => ({
        ...prev,
        base_url: "",
        model: "",
        api_key: "",
      }));
    }
  };

  const probeOcrConnection = async (): Promise<boolean> => {
    const probeBase = probeBaseUrlFromOcrServiceUrl(ocrForm.base_url);
    if (!probeBase) {
      setError("OCR service base URL is required to test the connection.");
      return false;
    }
    if (!probeBase.startsWith("http://") && !probeBase.startsWith("https://")) {
      setError("OCR service URL must start with http:// or https://");
      return false;
    }
    const apiKey = ocrForm.api_key.trim();
    if (!apiKey || apiKey === "EMPTY") {
      setError(
        "A non-empty API token is required for remote vision OCR (use any placeholder if the server has no auth — do not use EMPTY).",
      );
      return false;
    }

    setOcrProbing(true);
    setError(null);
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
      setOcrForm((prev) => ({
        ...prev,
        base_url: result.base_url || probeBase,
      }));

      if (ocrIds.length > 0) {
        setOcrManualModelEntry(false);
        setOcrForm((prev) => ({
          ...prev,
          model: pickDefaultModel(allIds, "ocr"),
        }));
      } else {
        setOcrManualModelEntry(true);
        setOcrForm((prev) => ({ ...prev, model: "" }));
      }

      if (result.warning) {
        setError(result.warning);
      }
      return true;
    } catch (err: any) {
      resetOcrProbeState();
      setError(err.message || "OCR connection test failed.");
      return false;
    } finally {
      setOcrProbing(false);
    }
  };

  // --- Sequential Saving Flow ---
  const handleSave = async () => {
    setLoading(true);
    setError(null);
    try {
      // 1. Save LLM Provider
      const llmRes = await apiFetch(`${apiBase()}/admin/llm-providers`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          slug: llmForm.slug,
          display_name: llmForm.display_name,
          provider: llmForm.provider,
          model_name: llmForm.model_name,
          api_base_url: llmForm.api_base_url || null,
          api_key: llmForm.api_key || null,
          timeout: llmForm.timeout,
          max_chat_tokens: llmForm.max_chat_tokens || null,
          thinking_token_budget: llmForm.thinking_token_budget || null,
          enabled: true,
          is_default: true,
        }),
      });

      if (!llmRes.ok) {
        const errData = await llmRes.json();
        throw new Error(`LLM Provider Save Failed: ${errData.detail || "Unknown error"}`);
      }

      // 2. Save Filesystem Policy
      const policyRes = await apiFetch(`${apiBase()}/admin/settings/fs-policy`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          yaml_content: policyYaml,
          enabled: policyEnabled,
        }),
      });

      if (!policyRes.ok) {
        const errData = await policyRes.json();
        throw new Error(`Filesystem Policy Save Failed: ${errData.detail || "Unknown error"}`);
      }

      // 3. Save General Settings & Complete Setup
      const settingsPayload = {
        settings: {
          // Embeddings
          AION_EMBEDDINGS_PROVIDER: embForm.provider,
          AION_EMBEDDING_MODEL: embForm.model,
          AION_EMBEDDING_URL: embForm.url,
          AION_EMBEDDINGS_API_KEY: embForm.api_key,
          // OCR — remote vision server only; local mode clears env (MCP uses pymupdf/tesseract)
          AION_OCR_BASE_URL: ocrMode === "remote" ? ocrForm.base_url : "",
          AION_OCR_MODEL: ocrMode === "remote" ? ocrForm.model : "",
          AION_OCR_API_KEY: ocrMode === "remote" ? ocrForm.api_key : "",
          AION_OCR_MAX_TOKENS: ocrMode === "remote" ? String(ocrForm.max_tokens) : "",
          AION_OCR_TIMEOUT: ocrMode === "remote" ? String(ocrForm.timeout) : "",
          AION_OCR_MAX_IMAGE_BYTES: ocrMode === "remote" ? String(ocrForm.max_image_bytes) : "",
          // Web Search
          AION_WEB_SEARCH_TAVILY_ENABLED: searchForm.tavily_enabled ? "1" : "0",
          AION_TAVILY_API_KEY: searchForm.tavily_key,
          AION_WEB_SEARCH_BRAVE_ENABLED: searchForm.brave_enabled ? "1" : "0",
          AION_BRAVE_SEARCH_API_KEY: searchForm.brave_key,
          AION_WEB_SEARCH_SEARXNG_ENABLED: searchForm.searxng_enabled ? "1" : "0",
          AION_SEARXNG_BASE_URL: searchForm.searxng_url,
          AION_WEB_SEARCH_DEFAULT_PROVIDER: searchForm.default_provider,
          AION_WEB_SEARCH_FALLBACK_ORDER: searchForm.fallback_order,
          // LLM Limits
          AION_CHAT_MAX_TOKENS: String(llmForm.max_chat_tokens),
          AION_THINKING_TOKEN_BUDGET: String(llmForm.thinking_token_budget),
          // Setup Completion Flag
          AION_FIRST_SETUP_COMPLETE: "1",
          ...(ssoStatus.enabled && ssoStatus.validated ? { AION_CHAT_PASSWORD_AUTH: "1" } : {})
        },
      };

      if (ssoStatus.enabled && ssoStatus.validated) {
        const provRes = await apiFetch(`${apiBase()}/admin/sso/providers`);
        if (provRes.ok) {
          const provData = await provRes.json();
          // Provider scelto nello step SSO (deve essere validato, altrimenti il backend rifiuta con 409)
          const active = provData.find((p: any) => p.provider === ssoProvider);
          if (active && active.provider) {
             const modeRes = await apiFetch(`${apiBase()}/admin/auth/login-mode`, {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ mode: active.provider })
             });
             if (!modeRes.ok) {
               let code = "";
               try { code = (await modeRes.json())?.detail?.code || ""; } catch {}
               throw new Error(`Attivazione SSO fallita${code ? ` (${code})` : ""}. Torna allo step SSO e ripeti la verifica.`);
             }
          }
        }
      }

      const settingsRes = await apiFetch(`${apiBase()}/admin/settings`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(settingsPayload),
      });

      if (!settingsRes.ok) {
        const errData = await settingsRes.json();
        throw new Error(`Settings Save Failed: ${errData.detail || "Unknown error"}`);
      }

      const settingsData = await settingsRes.json();
      if (settingsData.restarting) {
        setRestarting(true);
        pollHealth();
      } else {
        setSuccessMsg("Configuration saved successfully!");
        await fetchAuthStatus(true); // force reload
        setTimeout(() => router.replace("/"), 1000);
      }
    } catch (err: any) {
      setError(err.message || "An error occurred during setup save.");
      setLoading(false);
    }
  };

  const pollHealth = async () => {
    const maxAttempts = 30;
    let attempt = 0;
    await new Promise((resolve) => setTimeout(resolve, 2000));

    const interval = setInterval(async () => {
      attempt++;
      try {
        const res = await fetch(`${apiBase()}/health`);
        if (res.ok) {
          const data = await res.json();
          if (data.status === "ok") {
            clearInterval(interval);
            setRestarting(false);
            setSuccessMsg("System initialized successfully! Redirecting...");
            await fetchAuthStatus(true); // reload auth status cache
            setTimeout(() => {
              window.location.replace("/");
            }, 1000);
          }
        }
      } catch (err) {
        console.log("Waiting for AION kernel to restart...", err);
      }

      if (attempt >= maxAttempts) {
        clearInterval(interval);
        setRestarting(false);
        setError("AION kernel took too long to restart. Please refresh the page manually.");
        setLoading(false);
      }
    }, 1500);
  };

  const stepsOrder: Step[] = ["llm", "embeddings", "ocr", "search", "policy", "sso", "review"];

  const handleNext = async () => {
    setError(null);
    if (currentStep === "llm") {
      if (providerNeedsBaseUrl(llmForm.provider) && !llmForm.api_base_url.trim()) {
        setError("API Base URL is required for this provider.");
        return;
      }
      if (llmForm.provider !== "ollama" && !llmForm.api_key.trim()) {
        setError("API Key is required.");
        return;
      }
      if (!llmConnectionTested) {
        const ok = await probeLlmConnection();
        if (!ok) return;
      }
      if (!llmForm.model_name.trim()) {
        setError(
          llmManualModelEntry
            ? "Enter the model name manually — the endpoint did not list any models."
            : "Select a model from the list discovered by the connection test.",
        );
        return;
      }
      const hint = hintForModel(llmProbeResult, llmForm.model_name);
      const tokenErr = validateMaxChatTokens(
        llmForm.max_chat_tokens,
        Number(llmForm.thinking_token_budget) || 0,
        hint,
      );
      if (tokenErr) {
        setError(tokenErr);
        return;
      }
      const idx = stepsOrder.indexOf(currentStep);
      setCurrentStep(stepsOrder[idx + 1]);
      return;
    }
    if (currentStep === "embeddings") {
      if (!embForm.url.trim()) {
        setError("Embedding service URL is required.");
        return;
      }
      if (embForm.provider !== "google" && !embForm.api_key.trim()) {
        setError("Embedding API Key is required.");
        return;
      }
      if (!embConnectionTested) {
        const ok = await probeEmbConnection();
        if (!ok) return;
      }
      if (!embForm.model.trim()) {
        setError(
          embManualModelEntry
            ? "Enter the embedding model name manually — the endpoint did not list any models."
            : "Select an embedding model from the list discovered by the connection test.",
        );
        return;
      }
      const idx = stepsOrder.indexOf(currentStep);
      setCurrentStep(stepsOrder[idx + 1]);
      return;
    }
    if (currentStep === "ocr") {
      if (ocrMode === "remote") {
        const probeBase = probeBaseUrlFromOcrServiceUrl(ocrForm.base_url);
        if (!probeBase) {
          setError("OCR service base URL is required for remote vision OCR.");
          return;
        }
        if (!probeBase.startsWith("http://") && !probeBase.startsWith("https://")) {
          setError("OCR service URL must start with http:// or https://");
          return;
        }
        const apiKey = ocrForm.api_key.trim();
        if (!apiKey || apiKey === "EMPTY") {
          setError("A non-empty API token is required for remote vision OCR.");
          return;
        }
        if (!ocrConnectionTested) {
          const ok = await probeOcrConnection();
          if (!ok) return;
        }
        if (!ocrForm.model.trim()) {
          setError(
            ocrManualModelEntry
              ? "Enter the OCR model name manually — the endpoint did not list any models."
              : "Select an OCR model from the list discovered by the connection test.",
          );
          return;
        }
        if (ocrForm.max_tokens <= 0) {
          setError("OCR Max Tokens must be a positive integer.");
          return;
        }
        if (ocrForm.timeout <= 0) {
          setError("OCR Timeout must be a positive integer.");
          return;
        }
        if (ocrForm.max_image_bytes <= 0) {
          setError("OCR Max Image Bytes must be a positive integer.");
          return;
        }
      }
      const idx = stepsOrder.indexOf(currentStep);
      setCurrentStep(stepsOrder[idx + 1]);
      return;
    }

    if (currentStep === "sso") {
      if (ssoStatus.enabled && !ssoStatus.validated) {
        setError("Devi verificare l'account (Salva e verifica) per poter procedere con SSO abilitato. Oppure disabilitalo.");
        return;
      }
      const idx = stepsOrder.indexOf(currentStep);
      setCurrentStep(stepsOrder[idx + 1]);
      return;
    }

    const idx = stepsOrder.indexOf(currentStep);
    setCurrentStep(stepsOrder[idx + 1]);
  };

  // --- Render Steps ---
  if (restarting) {
    return (
      <AuthShell>
        <div role="status">
          <AuthHeading
            icon={<Loader2 className="h-5 w-5 animate-spin" aria-hidden />}
            title="Restarting AION Kernel"
            description="Applying your environment configurations and booting up the agent ecosystem. This will take a few seconds..."
          />
        </div>
      </AuthShell>
    );
  }

  const currIdx = stepsOrder.indexOf(currentStep);

  return (
    <div className="relative min-h-[100dvh] w-full overflow-x-hidden bg-background px-4 py-10 text-foreground sm:py-14">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 top-0 h-[26rem] bg-[radial-gradient(55%_100%_at_50%_0%,hsl(var(--primary)/0.09),transparent)]"
      />

      <div className="auth-enter relative mx-auto flex w-full max-w-3xl flex-col gap-8">
        {/* Header */}
        <header className="flex flex-col items-center gap-5 text-center">
          <AdminBrand className="h-11 max-w-[150px] sm:h-12 sm:max-w-[160px]" />
          <div className="space-y-2">
            <h1 className="text-2xl font-semibold tracking-[-0.02em] text-balance sm:text-3xl">Configure AION System</h1>
            <p className="mx-auto max-w-md text-sm leading-relaxed text-pretty text-muted-foreground">
              Initialize your local environment parameters to activate your autonomous coding agent.
            </p>
          </div>
        </header>

        {/* Stepper Progress */}
        <nav aria-label="First Setup Wizard" className="mx-auto flex w-full max-w-lg flex-col items-center gap-3">
          <p className="aion-section-label">First Setup Wizard</p>
          <ol className="flex w-full items-center">
            {stepsOrder.map((step, idx) => {
              const isActive = step === currentStep;
              const isCompleted = idx < currIdx;
              return (
                <li
                  key={step}
                  aria-current={isActive ? "step" : undefined}
                  className="flex flex-1 items-center last:flex-none"
                >
                  <span
                    className={cn(
                      "flex size-8 shrink-0 items-center justify-center rounded-full border text-xs font-semibold tabular-nums transition-colors duration-200",
                      isActive
                        ? "border-primary bg-primary text-primary-foreground shadow-sm shadow-primary/25"
                        : isCompleted
                          ? "border-success/40 bg-success/10 text-success"
                          : "border-border bg-card text-muted-foreground",
                    )}
                  >
                    {isCompleted ? (
                      <>
                        <Check className="h-4 w-4" aria-hidden />
                        <span className="sr-only">{idx + 1}</span>
                      </>
                    ) : (
                      idx + 1
                    )}
                  </span>
                  {idx < stepsOrder.length - 1 && (
                    <span
                      aria-hidden
                      className={cn(
                        "mx-1.5 h-px flex-1 transition-colors duration-200 sm:mx-2",
                        idx < currIdx ? "bg-success/50" : "bg-border",
                      )}
                    />
                  )}
                </li>
              );
            })}
          </ol>
        </nav>

        {/* Error / Success Messages */}
        {error && <AuthAlert>{error}</AuthAlert>}
        {successMsg && <AuthAlert tone="success">{successMsg}</AuthAlert>}

        {/* Main Card */}
        <section className="rounded-2xl border border-border/70 bg-card/80 p-5 shadow-[0_10px_32px_-16px_hsl(var(--foreground)/0.22)] backdrop-blur-sm sm:p-7">
          {/* Step 1: LLM Provider */}
          {currentStep === "llm" && (
            <div className="flex flex-col gap-6">
              <StepHeader
                icon={<Server className="h-5 w-5" aria-hidden />}
                title="1. Default LLM Provider"
                description="Enter the endpoint and credentials, test the connection, then pick a model from the discovered list."
              />

              <div className={fieldGridCls}>
                <Field label="LLM Provider" wide>
                  <Select
                    value={llmForm.provider}
                    onChange={handleLlmProviderChange}
                    options={[
                      { value: "openai", label: "OpenAI" },
                      { value: "anthropic", label: "Anthropic (Claude)" },
                      { value: "gemini", label: "Google Gemini" },
                      { value: "ollama", label: "Ollama (Local)" },
                      { value: "vllm", label: "vLLM (Self-hosted)" },
                    ]}
                  />
                </Field>

                {llmForm.provider !== "ollama" && (
                  <Field label="API Key" wide>
                    <SecretField
                      shown={showLlmKey}
                      onToggle={() => setShowLlmKey(!showLlmKey)}
                      value={llmForm.api_key}
                      onChange={(v) => {
                        setLlmForm((prev) => ({ ...prev, api_key: v }));
                        resetLlmProbeState();
                      }}
                      placeholder="Enter API key"
                    />
                  </Field>
                )}

                <Field
                  label={`API Base URL ${providerNeedsBaseUrl(llmForm.provider) ? "" : "(optional — defaults to vendor API)"}`}
                  wide
                >
                  <input
                    type="text"
                    value={llmForm.api_base_url}
                    onChange={(e) => {
                      setLlmForm((prev) => ({ ...prev, api_base_url: e.target.value }));
                      resetLlmProbeState();
                    }}
                    className={monoInputCls}
                    placeholder={
                      llmForm.provider === "ollama"
                        ? "http://localhost:11434/v1"
                        : llmForm.provider === "vllm"
                          ? "http://localhost:8000/v1"
                          : llmForm.provider === "anthropic"
                            ? "https://api.anthropic.com"
                            : llmForm.provider === "gemini"
                              ? "https://generativelanguage.googleapis.com/v1beta"
                              : "https://api.openai.com/v1"
                    }
                  />
                </Field>

                {providerSupportsProbe(llmForm.provider) && (
                  <ProbeBar
                    probing={llmProbing}
                    onProbe={() => void probeLlmConnection()}
                    label="Test connection & discover models"
                    ok={llmConnectionTested && llmProbeLatencyMs != null}
                    okText={`Connection OK · ${llmProbeLatencyMs}ms${
                      llmDiscoveredModelIds.length > 0 ? ` · ${llmDiscoveredModelIds.length} models` : " · enter model manually"
                    }`}
                  />
                )}

                <ModelField
                  label="Model (auto-discovered)"
                  manualLabel="Model name (manual)"
                  tested={llmConnectionTested}
                  manual={llmManualModelEntry}
                  ids={llmDiscoveredModelIds}
                  value={llmForm.model_name}
                  onChange={(modelId) => {
                    if (!llmManualModelEntry) {
                      applyLlmModelSelection(modelId, llmProbeResult);
                      return;
                    }
                    setLlmForm((prev) => ({
                      ...prev,
                      model_name: modelId,
                      display_name: modelId ? formatModelDisplayName(modelId) : prev.display_name,
                      slug: modelId
                        ? slugFromModelId(modelId, llmForm.provider === "vllm" ? "local" : "default")
                        : prev.slug,
                    }));
                  }}
                  hintBefore="Test the endpoint to discover available models. The model will be selected automatically from the list."
                  manualPlaceholder="Enter the exact model id served by your endpoint"
                  hint={
                    llmManualModelEntry ? (
                      <span className="text-warning">No models were returned by GET /v1/models — enter the model id manually.</span>
                    ) : hintForModel(llmProbeResult, llmForm.model_name) ? (
                      <span className="font-mono">
                        Context window:{" "}
                        {hintForModel(llmProbeResult, llmForm.model_name)?.context_window.toLocaleString()} tokens
                      </span>
                    ) : undefined
                  }
                />

                {llmConnectionTested && llmForm.model_name && (
                  <>
                    <Field label="Display Name">
                      <input
                        type="text"
                        value={llmForm.display_name}
                        onChange={(e) => setLlmForm((prev) => ({ ...prev, display_name: e.target.value }))}
                        className={inputCls}
                      />
                    </Field>

                    <Field label="Slug (Unique ID)">
                      <input
                        type="text"
                        value={llmForm.slug}
                        onChange={(e) => setLlmForm((prev) => ({ ...prev, slug: e.target.value }))}
                        className={monoInputCls}
                      />
                    </Field>

                    <Field label="Max Chat Tokens (AION_CHAT_MAX_TOKENS)">
                      <input
                        type="number"
                        value={llmForm.max_chat_tokens}
                        onChange={(e) => setLlmForm((prev) => ({ ...prev, max_chat_tokens: parseInt(e.target.value) || 0 }))}
                        className={monoInputCls}
                        placeholder="e.g. 8192"
                      />
                    </Field>

                    <Field label="Thinking Token Budget (AION_THINKING_TOKEN_BUDGET)">
                      <input
                        type="number"
                        min={0}
                        value={llmForm.thinking_token_budget ?? ""}
                        onChange={(e) => {
                          const val = e.target.value;
                          if (val === "") {
                            setLlmForm((prev) => ({ ...prev, thinking_token_budget: "" as any }));
                            return;
                          }
                          const parsed = parseInt(val, 10);
                          if (!isNaN(parsed)) {
                            setLlmForm((prev) => ({ ...prev, thinking_token_budget: Math.max(0, parsed) }));
                          }
                        }}
                        className={monoInputCls}
                        placeholder="e.g. 12000 (0 to disable)"
                      />
                    </Field>
                  </>
                )}
              </div>
            </div>
          )}

          {/* Step 2: Embeddings */}
          {currentStep === "embeddings" && (
            <div className="flex flex-col gap-6">
              <StepHeader
                icon={<Zap className="h-5 w-5" aria-hidden />}
                title="2. Autonomous Memory (Embeddings)"
                description="Enter the embedding service URL and credentials, test the connection, then pick a model from the discovered list."
              />

              <div className={fieldGridCls}>
                <Field label="Embedding Provider" wide>
                  <Select
                    value={embForm.provider}
                    onChange={handleEmbProviderChange}
                    options={[
                      { value: "openai", label: "OpenAI-Compatible" },
                      { value: "vllm", label: "vLLM (Self-hosted)" },
                      { value: "ollama", label: "Ollama" },
                      { value: "google", label: "Google (Gemini)" },
                    ]}
                  />
                </Field>

                <Field
                  label="Embedding Service URL"
                  wide
                  hint={
                    <>
                      Base URL or full <Mono>/v1/embeddings</Mono> path — used for POST; probe uses GET /v1/models on the base.
                    </>
                  }
                >
                  <input
                    type="text"
                    value={embForm.url}
                    onChange={(e) => {
                      setEmbForm((prev) => ({ ...prev, url: e.target.value }));
                      resetEmbProbeState();
                    }}
                    className={monoInputCls}
                    placeholder={
                      embForm.provider === "google"
                        ? "https://generativelanguage.googleapis.com/v1beta/models"
                        : embForm.provider === "ollama"
                          ? "http://host.docker.internal:11434/v1/embeddings or http://localhost:11434/v1/embeddings"
                          : embForm.provider === "vllm"
                            ? "http://host.docker.internal:8000/v1/embeddings or http://localhost:8000/v1/embeddings"
                            : "http://host.docker.internal:8000/v1/embeddings or https://api.openai.com/v1/embeddings"
                    }
                  />
                </Field>

                {embForm.provider !== "google" && (
                  <Field label="Embedding API Key" wide>
                    <SecretField
                      shown={showEmbKey}
                      onToggle={() => setShowEmbKey(!showEmbKey)}
                      value={embForm.api_key}
                      onChange={(v) => {
                        setEmbForm((prev) => ({ ...prev, api_key: v }));
                        resetEmbProbeState();
                      }}
                      placeholder={
                        ["vllm", "ollama"].includes(embForm.provider) ? "Optional for local / vLLM / Ollama" : "Enter API key"
                      }
                    />
                  </Field>
                )}

                <ProbeBar
                  probing={embProbing}
                  onProbe={() => void probeEmbConnection()}
                  label="Test connection & discover models"
                  ok={embConnectionTested && embProbeLatencyMs != null}
                  okText={`Connection OK · ${embProbeLatencyMs}ms${
                    embDiscoveredModelIds.length > 0
                      ? ` · ${embDiscoveredModelIds.length} embedding models`
                      : " · enter model manually"
                  }`}
                />

                <ModelField
                  label="Embedding model (auto-discovered)"
                  manualLabel="Embedding model (manual)"
                  tested={embConnectionTested}
                  manual={embManualModelEntry}
                  ids={embDiscoveredModelIds}
                  value={embForm.model}
                  onChange={(v) => setEmbForm((prev) => ({ ...prev, model: v }))}
                  hintBefore="Test the embedding endpoint to discover available models. Embedding models are preferred when detected in the list."
                  manualPlaceholder="e.g. text-embedding-3-small, qwen3-embedding"
                  hint={
                    embManualModelEntry ? (
                      <span className="text-warning">
                        No models were returned by GET /v1/models — enter the embedding model id manually.
                      </span>
                    ) : undefined
                  }
                />
              </div>
            </div>
          )}

          {/* Step 3: OCR */}
          {currentStep === "ocr" && (
            <div className="flex flex-col gap-6">
              <StepHeader
                icon={<Eye className="h-5 w-5" aria-hidden />}
                title="3. OCR Document Processing"
                description="OCR is always available via the MCP tool. Choose how text is extracted from images and scanned PDFs."
              />

              <Group>
                <ChoiceList<OcrMode>
                  value={ocrMode}
                  onChange={handleOcrModeChange}
                  label="3. OCR Document Processing"
                  options={[
                    {
                      value: "remote",
                      title: "Remote vision OCR (recommended)",
                      description:
                        "OpenAI-compatible vLLM vision server (e.g. GLM-OCR). Highest accuracy on images and scanned PDF pages.",
                    },
                    {
                      value: "local",
                      title: "Local Python OCR (basic)",
                      description: (
                        <>
                          PDF via <Mono>pymupdf4llm</Mono>, images via <Mono>pytesseract</Mono>. No remote server — lower
                          accuracy, requires Tesseract on the host.
                        </>
                      ),
                    },
                  ]}
                />
              </Group>

              {ocrMode === "remote" ? (
                <div className={fieldGridCls}>
                  <Field
                    label="OCR Service Base URL (OpenAI-compatible)"
                    wide
                    hint={
                      <>
                        Base URL for <Mono>POST /v1/chat/completions</Mono> — probe uses <Mono>GET /v1/models</Mono>.
                      </>
                    }
                  >
                    <input
                      type="text"
                      value={ocrForm.base_url}
                      onChange={(e) => {
                        setOcrForm((prev) => ({ ...prev, base_url: e.target.value }));
                        resetOcrProbeState();
                      }}
                      className={monoInputCls}
                      placeholder="e.g. http://localhost:8002/v1"
                    />
                  </Field>

                  <Field label="OCR API Token" wide>
                    <SecretField
                      shown={showOcrKey}
                      onToggle={() => setShowOcrKey(!showOcrKey)}
                      value={ocrForm.api_key}
                      onChange={(v) => {
                        setOcrForm((prev) => ({ ...prev, api_key: v }));
                        resetOcrProbeState();
                      }}
                      placeholder="Bearer token (any non-empty value if auth is disabled)"
                    />
                  </Field>

                  <ProbeBar
                    probing={ocrProbing}
                    onProbe={() => void probeOcrConnection()}
                    label="Test connection & discover models"
                    ok={ocrConnectionTested && ocrProbeLatencyMs != null}
                    okText={`Connection OK · ${ocrProbeLatencyMs}ms${
                      ocrDiscoveredModelIds.length > 0
                        ? ` · ${ocrDiscoveredModelIds.length} vision/OCR models`
                        : " · enter model manually"
                    }`}
                  />

                  <ModelField
                    label="OCR model (auto-discovered)"
                    manualLabel="OCR model (manual)"
                    tested={ocrConnectionTested}
                    manual={ocrManualModelEntry}
                    ids={ocrDiscoveredModelIds}
                    value={ocrForm.model}
                    onChange={(v) => setOcrForm((prev) => ({ ...prev, model: v }))}
                    hintBefore="Test the vision OCR endpoint to discover models. Vision/OCR models are preferred when detected."
                    manualPlaceholder="e.g. zai-org/GLM-OCR"
                    hint={
                      ocrManualModelEntry ? (
                        <span className="text-warning">
                          No models were returned by GET /v1/models — enter the vision model id manually.
                        </span>
                      ) : undefined
                    }
                  />

                  {ocrConnectionTested && ocrForm.model && (
                    <>
                      <Field label="OCR Max Tokens">
                        <input
                          type="number"
                          value={ocrForm.max_tokens}
                          onChange={(e) => setOcrForm((prev) => ({ ...prev, max_tokens: parseInt(e.target.value) || 0 }))}
                          className={monoInputCls}
                        />
                      </Field>

                      <Field label="OCR Timeout (seconds)">
                        <input
                          type="number"
                          value={ocrForm.timeout}
                          onChange={(e) => setOcrForm((prev) => ({ ...prev, timeout: parseInt(e.target.value) || 0 }))}
                          className={monoInputCls}
                        />
                      </Field>

                      <Field label="OCR Max Image Bytes" wide>
                        <input
                          type="number"
                          value={ocrForm.max_image_bytes}
                          onChange={(e) =>
                            setOcrForm((prev) => ({ ...prev, max_image_bytes: parseInt(e.target.value) || 0 }))
                          }
                          className={monoInputCls}
                        />
                      </Field>
                    </>
                  )}
                </div>
              ) : (
                <Note>
                  <div className="space-y-2">
                    <p>The OCR MCP tool stays active. Without a remote vision server it falls back to local extractors:</p>
                    <ul className="list-inside list-disc space-y-1 text-xs">
                      <li>
                        PDF → <Mono>pymupdf4llm</Mono> (text layer / markdown)
                      </li>
                      <li>
                        Images → <Mono>pytesseract</Mono> (requires Tesseract binary on the host)
                      </li>
                    </ul>
                    <p className="text-xs text-warning">
                      No <span className="font-mono">AION_OCR_*</span> variables will be written — switch to remote mode
                      anytime in Admin Settings.
                    </p>
                  </div>
                </Note>
              )}
            </div>
          )}

          {/* Step 4: Web Search */}
          {currentStep === "search" && (
            <div className="flex flex-col gap-6">
              <StepHeader
                icon={<Search className="h-5 w-5" aria-hidden />}
                title="4. Web Integration & Search"
                description="Configure search engines and page fetching protocols for web operations."
              />

              <Group>
                <ul className="divide-y divide-border/40">
                  <EngineRow
                    name="Tavily Search"
                    description="Fast AI search engine optimized for LLM agents."
                    checked={searchForm.tavily_enabled}
                    onChange={(v) => setSearchForm((prev) => ({ ...prev, tavily_enabled: v }))}
                  >
                    <Field label="Tavily API Key">
                      <SecretField
                        shown={showTavilyKey}
                        onToggle={() => setShowTavilyKey(!showTavilyKey)}
                        value={searchForm.tavily_key}
                        onChange={(v) => setSearchForm((prev) => ({ ...prev, tavily_key: v }))}
                        placeholder="tvly-..."
                      />
                    </Field>
                  </EngineRow>

                  <EngineRow
                    name="Brave Search"
                    description="Global, private search engine with rich results."
                    checked={searchForm.brave_enabled}
                    onChange={(v) => setSearchForm((prev) => ({ ...prev, brave_enabled: v }))}
                  >
                    <Field label="Brave API Key">
                      <SecretField
                        shown={showBraveKey}
                        onToggle={() => setShowBraveKey(!showBraveKey)}
                        value={searchForm.brave_key}
                        onChange={(v) => setSearchForm((prev) => ({ ...prev, brave_key: v }))}
                        placeholder="BS..."
                      />
                    </Field>
                  </EngineRow>

                  <EngineRow
                    name="SearXNG"
                    description="Self-hosted metasearch engine (no API key required)."
                    checked={searchForm.searxng_enabled}
                    onChange={(v) => setSearchForm((prev) => ({ ...prev, searxng_enabled: v }))}
                  >
                    <Field label="SearXNG Base URL">
                      <input
                        type="text"
                        value={searchForm.searxng_url}
                        onChange={(e) => setSearchForm((prev) => ({ ...prev, searxng_url: e.target.value }))}
                        className={monoInputCls}
                        placeholder="e.g. https://searxng.mydomain.org"
                      />
                    </Field>
                  </EngineRow>
                </ul>
              </Group>

              <div className={fieldGridCls}>
                <Field label="Default Search Provider">
                  <Select
                    value={searchForm.default_provider}
                    onChange={(v) => setSearchForm((prev) => ({ ...prev, default_provider: v }))}
                    options={[
                      { value: "tavily", label: "Tavily" },
                      { value: "brave", label: "Brave" },
                      { value: "searxng", label: "SearXNG" },
                    ]}
                  />
                </Field>

                <Field label="Search Fallback Order (CSV)">
                  <input
                    type="text"
                    value={searchForm.fallback_order}
                    onChange={(e) => setSearchForm((prev) => ({ ...prev, fallback_order: e.target.value }))}
                    className={monoInputCls}
                  />
                </Field>
              </div>
            </div>
          )}

          {/* Step 5: Filesystem Policy */}
          {currentStep === "policy" && (
            <div className="flex flex-col gap-6">
              <StepHeader
                icon={<ShieldAlert className="h-5 w-5" aria-hidden />}
                title="5. Sandbox Security & Exec Policy"
                description="Restrict or allow terminal commands and filesystem access within the workspace."
                action={
                  <Switch checked={policyEnabled} onChange={setPolicyEnabled} label="5. Sandbox Security & Exec Policy" />
                }
              />

              {policyEnabled ? (
                <div className="flex flex-col gap-5">
                  <Group>
                    <ChoiceList<"dev" | "example">
                      value={policyTemplate}
                      onChange={handleTemplateChange}
                      label="Policy Blueprint (YAML)"
                      options={[
                        {
                          value: "dev",
                          title: "Development Policy",
                          description: (
                            <>
                              Enables a minimal allowlist of commands (<Mono>grep</Mono>, <Mono>wc</Mono>, <Mono>sort</Mono>,{" "}
                              <Mono>python3</Mono>) for local agent operations.
                            </>
                          ),
                        },
                        {
                          value: "example",
                          title: "Production Policy",
                          description:
                            "Advanced template with detailed descriptions, strict path boundaries, and hardened execute constraints.",
                        },
                      ]}
                    />
                  </Group>

                  <label className="flex flex-col gap-1.5">
                    <span className="flex items-center justify-between gap-3">
                      <span className="text-sm font-medium">Policy Blueprint (YAML)</span>
                      <span className="font-mono text-[11.5px] text-muted-foreground">config/fs_policy.yaml</span>
                    </span>
                    <textarea
                      value={policyYaml}
                      onChange={(e) => setPolicyYaml(e.target.value)}
                      rows={20}
                      readOnly
                      spellCheck={false}
                      className="focus-ring w-full resize-y rounded-xl border border-border bg-secondary/40 p-4 font-mono text-xs leading-relaxed text-foreground/85"
                    />
                  </label>
                </div>
              ) : (
                <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed border-border bg-secondary/30 p-5 text-center text-sm text-muted-foreground">
                  <ShieldAlert className="h-6 w-6 text-muted-foreground/70" aria-hidden />
                  <p>
                    Filesystem security policy is disabled. The agent will run with in-code default settings (
                    <Mono>exec.enabled=false</Mono>).
                  </p>
                </div>
              )}
            </div>
          )}

          {/* Step 6: SSO Configuration */}
          {currentStep === "sso" && (
            <div className="flex flex-col gap-6">
              <StepHeader
                icon={<ShieldAlert className="h-5 w-5" aria-hidden />}
                title="6. Single Sign-On (SSO)"
                description="Opzionale: configura l'accesso tramite Google Workspace o Microsoft Entra ID."
              />

              <div role="radiogroup" aria-label="6. Single Sign-On (SSO)" className="grid grid-cols-1 gap-2 sm:grid-cols-3">
                {([
                  ["none", "Nessuno (password)"],
                  ["microsoft", "Microsoft Entra ID"],
                  ["google", "Google Workspace"],
                ] as const).map(([value, label]) => {
                  const on = ssoProvider === value;
                  return (
                    <button
                      key={value}
                      type="button"
                      role="radio"
                      aria-checked={on}
                      onClick={() => {
                        setSsoProvider(value);
                        setSsoValidated(false);
                      }}
                      className={cn(
                        "focus-ring flex items-center gap-2.5 rounded-xl border px-3.5 py-3 text-left text-sm font-medium transition-colors duration-200",
                        on
                          ? "border-foreground/50 bg-secondary text-foreground"
                          : "border-border bg-background text-muted-foreground hover:border-foreground/25 hover:text-foreground",
                      )}
                    >
                      {value === "none" ? (
                        <KeyRound className="h-4 w-4 shrink-0" aria-hidden />
                      ) : (
                        <SsoProviderIcon provider={value} className="h-4 w-4" />
                      )}
                      {label}
                    </button>
                  );
                })}
              </div>

              {ssoProvider !== "none" && (
                <SsoConfigPanel
                  key={ssoProvider}
                  forcedProvider={ssoProvider}
                  isActive
                  onValidatedChange={setSsoValidated}
                />
              )}
            </div>
          )}

          {/* Step 7: Review */}
          {currentStep === "review" && (
            <div className="flex flex-col gap-6">
              <StepHeader
                icon={<Sparkles className="h-5 w-5" aria-hidden />}
                title="6. Review & Initialize"
                description="Review your configurations. Once confirmed, the system will apply them."
              />

              <div className="grid grid-cols-1 gap-3 text-sm md:grid-cols-2">
                <ReviewItem label="LLM Provider">
                  <span className="font-semibold">{llmForm.display_name}</span>
                  <span className="break-all font-mono text-xs text-muted-foreground">
                    {llmForm.provider} / {llmForm.model_name}
                  </span>
                  <span className="font-mono text-xs text-muted-foreground">
                    Max Chat Tokens: {llmForm.max_chat_tokens} | Thinking Budget: {llmForm.thinking_token_budget}
                  </span>
                </ReviewItem>

                <ReviewItem label="Memory & Embeddings">
                  <span className="font-semibold">Provider: {embForm.provider}</span>
                  <span className="break-all font-mono text-xs text-muted-foreground">Model: {embForm.model}</span>
                </ReviewItem>

                <ReviewItem label="OCR Processing">
                  <span className="font-semibold">{ocrMode === "remote" ? "Remote vision OCR" : "Local Python OCR"}</span>
                  <span className="break-all font-mono text-xs text-muted-foreground">
                    {ocrMode === "remote"
                      ? `${ocrForm.base_url || "—"} · model: ${ocrForm.model || "—"}`
                      : "pymupdf4llm + pytesseract (no AION_OCR_* env vars)"}
                  </span>
                </ReviewItem>

                <ReviewItem label="Web Integration">
                  <div className="flex flex-wrap gap-1.5">
                    {searchForm.tavily_enabled && <Chip>Tavily</Chip>}
                    {searchForm.brave_enabled && <Chip>Brave</Chip>}
                    {searchForm.searxng_enabled && <Chip>SearXNG</Chip>}
                    {!searchForm.tavily_enabled && !searchForm.brave_enabled && !searchForm.searxng_enabled && (
                      <span className="text-xs text-muted-foreground">No Web Search enabled</span>
                    )}
                  </div>
                </ReviewItem>

                <ReviewItem label="Sandbox Security">
                  <span className="font-semibold">
                    {policyEnabled ? `Enabled (${policyTemplate} template)` : "Disabled"}
                  </span>
                  <span className="font-mono text-xs text-muted-foreground">config/fs_policy.yaml</span>
                </ReviewItem>

                <ReviewItem label="Single Sign-On">
                  <span className="font-semibold">
                    {ssoStatus.enabled
                      ? ssoStatus.validated
                        ? "Enabled & Validated"
                        : "Enabled (Error: Not Validated)"
                      : "Disabled"}
                  </span>
                </ReviewItem>
              </div>

              <Note>
                Clicking the initialization button will save these variables to your <Mono>.env</Mono> file and write the
                sandbox policy YAML. If you are running in Docker, the container will restart automatically. If you are in
                local dev, you will need to restart the Python process manually.
              </Note>
            </div>
          )}
        </section>

        {/* Footer Controls */}
        <div className="flex items-center justify-between gap-3">
          {currentStep !== "llm" ? (
            <button
              type="button"
              onClick={() => {
                setError(null);
                const idx = stepsOrder.indexOf(currentStep);
                setCurrentStep(stepsOrder[idx - 1]);
              }}
              className={cn(outlineBtn, "h-10 px-4")}
            >
              <ChevronLeft className="h-4 w-4" aria-hidden /> Back
            </button>
          ) : (
            <div />
          )}

          {currentStep !== "review" ? (
            <button type="button" onClick={handleNext} className={cn(solidBtn, "h-10 px-5")}>
              Next <ChevronRight className="h-4 w-4" aria-hidden />
            </button>
          ) : (
            <button type="button" onClick={handleSave} disabled={loading} className={cn(solidBtn, "h-10 px-5")}>
              {loading ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <Check className="h-4 w-4" aria-hidden />}
              Initialize AION Kernel
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

/** Icon, numbered title and one-line description at the top of each wizard step. */
function StepHeader({
  icon,
  title,
  description,
  action,
}: {
  icon: ReactNode;
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex items-start gap-3.5">
      <div className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">{icon}</div>
      <div className="min-w-0 flex-1">
        <h2 className="text-lg font-semibold tracking-tight text-balance">{title}</h2>
        <p className="mt-1 text-sm leading-relaxed text-pretty text-muted-foreground">{description}</p>
      </div>
      {action ? <div className="shrink-0 pt-2">{action}</div> : null}
    </div>
  );
}

/** Masked key input with a show/hide toggle; visibility state lives in the page. */
function SecretField({
  shown,
  onToggle,
  value,
  onChange,
  placeholder,
}: {
  shown: boolean;
  onToggle: () => void;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
}) {
  return (
    <span className="relative block">
      <input
        type={shown ? "text" : "password"}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={cn(monoInputCls, "pr-11")}
        placeholder={placeholder}
        autoComplete="new-password"
        spellCheck={false}
      />
      <button
        type="button"
        onClick={onToggle}
        aria-label={shown ? "Hide" : "Show"}
        aria-pressed={shown}
        className="focus-ring absolute right-1.5 top-1/2 inline-flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
      >
        {shown ? <EyeOff className="h-4 w-4" aria-hidden /> : <Eye className="h-4 w-4" aria-hidden />}
      </button>
    </span>
  );
}

/** One search engine: name, description and switch, with its credential field when enabled. */
function EngineRow({
  name,
  description,
  checked,
  onChange,
  children,
}: {
  name: string;
  description: string;
  checked: boolean;
  onChange: (v: boolean) => void;
  children: ReactNode;
}) {
  return (
    <li className="flex flex-col gap-3.5 px-5 py-4">
      <div className="flex items-center gap-4">
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium">{name}</p>
          <p className="mt-0.5 text-xs text-muted-foreground">{description}</p>
        </div>
        <Switch checked={checked} onChange={onChange} label={name} />
      </div>
      {checked && children}
    </li>
  );
}

function ReviewItem({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-1.5 rounded-xl border border-border/70 bg-secondary/30 p-4">
      <span className="aion-section-label">{label}</span>
      {children}
    </div>
  );
}

function Chip({ children }: { children: ReactNode }) {
  return (
    <span className="rounded-md border border-border bg-secondary px-2 py-0.5 text-xs font-medium text-foreground">
      {children}
    </span>
  );
}
