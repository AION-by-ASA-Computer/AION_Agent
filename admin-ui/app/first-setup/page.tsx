"use client";

import { useEffect, useState } from "react";
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
  AlertTriangle,
  Info,
  Lock,
} from "lucide-react";
import { apiBase } from "@/lib/api";
import { apiFetch } from "@/lib/api/headers";
import { fetchAuthStatus } from "@/lib/auth/status";

type Step = "llm" | "embeddings" | "ocr" | "search" | "policy" | "review";

export default function FirstSetupPage() {
  const router = useRouter();
  const [currentStep, setCurrentStep] = useState<Step>("llm");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const [restarting, setRestarting] = useState(false);

  // --- Step 1: LLM Provider State ---
  const [llmForm, setLlmForm] = useState({
    slug: "default-openai",
    display_name: "OpenAI GPT-4o",
    provider: "openai",
    model_name: "gpt-4o",
    api_base_url: "",
    api_key: "",
    timeout: 120,
    max_chat_tokens: 8192,
    thinking_token_budget: 12000,
  });
  const [showLlmKey, setShowLlmKey] = useState(false);

  // --- Step 2: Embeddings State ---
  const [embForm, setEmbForm] = useState({
    provider: "openai",
    model: "text-embedding-3-small",
    url: "",
    api_key: "",
  });
  const [showEmbKey, setShowEmbKey] = useState(false);

  // --- Step 3: OCR State ---
  const [ocrForm, setOcrForm] = useState({
    base_url: "",
    model: "",
    api_key: "",
    max_tokens: 8192,
    timeout: 120,
    max_image_bytes: 20971520,
  });
  const [showOcrKey, setShowOcrKey] = useState(false);
  const [ocrEnabled, setOcrEnabled] = useState(false);

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

  const handleLlmProviderChange = (provider: string) => {
    let defaults = {
      slug: "default-openai",
      display_name: "OpenAI GPT-4o",
      model_name: "gpt-4o",
      max_chat_tokens: 8192,
      thinking_token_budget: 12000,
    };
    if (provider === "anthropic") {
      defaults = {
        slug: "default-anthropic",
        display_name: "Anthropic Claude 3.5 Sonnet",
        model_name: "claude-3-5-sonnet-20241022",
        max_chat_tokens: 16384,
        thinking_token_budget: 8192,
      };
    } else if (provider === "gemini") {
      defaults = {
        slug: "default-gemini",
        display_name: "Google Gemini 1.5 Pro",
        model_name: "gemini-1.5-pro",
        max_chat_tokens: 8192,
        thinking_token_budget: 0,
      };
    } else if (provider === "ollama") {
      defaults = {
        slug: "local-ollama",
        display_name: "Ollama Llama 3",
        model_name: "llama3",
        max_chat_tokens: 4096,
        thinking_token_budget: 0,
      };
    } else if (provider === "vllm") {
      defaults = {
        slug: "local-vllm",
        display_name: "vLLM Model",
        model_name: "meta-llama/Meta-Llama-3-8B-Instruct",
        max_chat_tokens: 16384,
        thinking_token_budget: 8192,
      };
    }
    setLlmForm((prev) => ({
      ...prev,
      provider,
      ...defaults,
    }));
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
          // OCR
          AION_OCR_BASE_URL: ocrEnabled ? ocrForm.base_url : "",
          AION_OCR_MODEL: ocrEnabled ? ocrForm.model : "",
          AION_OCR_API_KEY: ocrEnabled ? ocrForm.api_key : "",
          AION_OCR_MAX_TOKENS: ocrEnabled ? String(ocrForm.max_tokens) : "",
          AION_OCR_TIMEOUT: ocrEnabled ? String(ocrForm.timeout) : "",
          AION_OCR_MAX_IMAGE_BYTES: ocrEnabled ? String(ocrForm.max_image_bytes) : "",
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
        },
      };

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

  const stepsOrder: Step[] = ["llm", "embeddings", "ocr", "search", "policy", "review"];

  const handleNext = () => {
    setError(null);
    if (currentStep === "ocr" && ocrEnabled) {
      if (!ocrForm.base_url.trim()) {
        setError("OCR Base URL is required when OCR is enabled.");
        return;
      }
      if (!ocrForm.base_url.trim().startsWith("http://") && !ocrForm.base_url.trim().startsWith("https://")) {
        setError("OCR Base URL must start with http:// or https://");
        return;
      }
      if (!ocrForm.model.trim()) {
        setError("OCR Model is required when OCR is enabled.");
        return;
      }
      if (!ocrForm.api_key.trim()) {
        setError("OCR API Key is required when OCR is enabled.");
        return;
      }

      // Max tokens validation
      if (ocrForm.max_tokens <= 0) {
        setError("OCR Max Tokens must be a positive integer.");
        return;
      }

      // Timeout validation
      if (ocrForm.timeout <= 0) {
        setError("OCR Timeout must be a positive integer.");
        return;
      }

      // Max image bytes validation
      if (ocrForm.max_image_bytes <= 0) {
        setError("OCR Max Image Bytes must be a positive integer.");
        return;
      }
    }

    const idx = stepsOrder.indexOf(currentStep);
    setCurrentStep(stepsOrder[idx + 1]);
  };

  // --- Render Steps ---
  return (
    <div className="min-h-screen w-full flex items-center justify-center bg-[#060606] text-white px-4 py-12">
      {/* Background radial glow */}
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_center,rgba(59,130,246,0.05)_0%,transparent_70%)] pointer-events-none" />

      {restarting ? (
        <div className="w-full max-w-lg glass-card p-10 flex flex-col items-center justify-center text-center gap-6 border-blue-500/30 shadow-[0_0_50px_rgba(59,130,246,0.1)]">
          <div className="w-16 h-16 rounded-full border-4 border-blue-500/20 border-t-blue-500 animate-spin flex items-center justify-center" />
          <h2 className="text-2xl font-black tracking-tight">Restarting AION Kernel</h2>
          <p className="text-sm text-gray-400 max-w-sm">
            Applying your environment configurations and booting up the agent ecosystem. This will take a few seconds...
          </p>
        </div>
      ) : (
        <div className="w-full max-w-4xl flex flex-col gap-8 relative z-10">
          {/* Header */}
          <div className="flex flex-col items-center text-center gap-2">
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-blue-500/10 border border-blue-500/30 text-blue-400 text-xs font-bold uppercase tracking-wider">
              <Sparkles className="w-3.5 h-3.5" /> First Setup Wizard
            </div>
            <h1 className="text-4xl font-black tracking-tight bg-gradient-to-r from-white via-gray-200 to-gray-400 bg-clip-text text-transparent">
              Configure AION System
            </h1>
            <p className="text-sm text-gray-400 max-w-md">
              Initialize your local environment parameters to activate your autonomous coding agent.
            </p>
          </div>

          {/* Stepper Progress */}
          <div className="flex justify-between items-center max-w-lg mx-auto w-full px-4">
            {stepsOrder.map((step, idx) => {
              const currIdx = stepsOrder.indexOf(currentStep);
              const isActive = step === currentStep;
              const isCompleted = idx < currIdx;

              return (
                <div key={step} className="flex items-center flex-1 last:flex-none">
                  <button
                    disabled
                    className={`w-8 h-8 rounded-full flex items-center justify-center border text-xs font-bold transition-all ${isActive
                      ? "border-blue-500 bg-blue-500/20 text-blue-400 shadow-[0_0_15px_rgba(59,130,246,0.3)]"
                      : isCompleted
                        ? "border-emerald-500 bg-emerald-500/20 text-emerald-400"
                        : "border-neutral-800 bg-neutral-900 text-neutral-500"
                      }`}
                  >
                    {isCompleted ? <Check className="w-4 h-4" /> : idx + 1}
                  </button>
                  {idx < stepsOrder.length - 1 && (
                    <div
                      className={`h-0.5 flex-1 mx-2 transition-all ${idx < currIdx ? "bg-emerald-500/50" : "bg-neutral-800"
                        }`}
                    />
                  )}
                </div>
              );
            })}
          </div>

          {/* Error Message */}
          {error && (
            <div className="p-4 rounded-xl bg-red-500/10 border border-red-500/20 text-red-400 flex items-start gap-3 text-sm">
              <AlertTriangle className="w-5 h-5 shrink-0 mt-0.5" />
              <div>{error}</div>
            </div>
          )}

          {/* Success Message */}
          {successMsg && (
            <div className="p-4 rounded-xl bg-green-500/10 border border-green-500/20 text-green-400 flex items-start gap-3 text-sm">
              <Check className="w-5 h-5 shrink-0 mt-0.5" />
              <div>{successMsg}</div>
            </div>
          )}

          {/* Main Card */}
          <div className="glass-card p-8 border-[#1f1f1f] bg-[#0d0d0d]/80 shadow-2xl">
            {/* Step 1: LLM Provider */}
            {currentStep === "llm" && (
              <div className="space-y-6 animate-in fade-in duration-300">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-xl bg-blue-500/10 flex items-center justify-center border border-blue-500/20">
                    <Server className="w-5 h-5 text-blue-500" />
                  </div>
                  <div>
                    <h2 className="text-xl font-bold">1. Default LLM Provider</h2>
                    <p className="text-xs text-gray-400">Specify the model and credentials for the main LLM orchestration.</p>
                  </div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
                  <div className="space-y-2">
                    <label className="text-[10px] font-bold uppercase text-gray-400 tracking-wider">LLM Provider</label>
                    <select
                      value={llmForm.provider}
                      onChange={(e) => handleLlmProviderChange(e.target.value)}
                      className="w-full bg-[#070707] border border-[#222] rounded-xl px-4 py-3 text-sm text-gray-200 focus:border-blue-500/50 outline-none transition-all cursor-pointer"
                    >
                      <option value="openai">OpenAI</option>
                      <option value="anthropic">Anthropic (Claude)</option>
                      <option value="gemini">Google Gemini</option>
                      <option value="ollama">Ollama (Local)</option>
                      <option value="vllm">vLLM (Self-hosted)</option>
                    </select>
                  </div>

                  <div className="space-y-2">
                    <label className="text-[10px] font-bold uppercase text-gray-400 tracking-wider">Model Name</label>
                    <input
                      type="text"
                      value={llmForm.model_name}
                      onChange={(e) => setLlmForm((prev) => ({ ...prev, model_name: e.target.value }))}
                      className="w-full bg-[#070707] border border-[#222] rounded-xl px-4 py-3 text-sm text-gray-200 focus:border-blue-500/50 outline-none transition-all font-mono"
                      placeholder="e.g. gpt-4o, claude-3-5-sonnet-20241022"
                    />
                  </div>

                  <div className="space-y-2">
                    <label className="text-[10px] font-bold uppercase text-gray-400 tracking-wider">Display Name</label>
                    <input
                      type="text"
                      value={llmForm.display_name}
                      onChange={(e) => setLlmForm((prev) => ({ ...prev, display_name: e.target.value }))}
                      className="w-full bg-[#070707] border border-[#222] rounded-xl px-4 py-3 text-sm text-gray-200 focus:border-blue-500/50 outline-none transition-all"
                    />
                  </div>

                  <div className="space-y-2">
                    <label className="text-[10px] font-bold uppercase text-gray-400 tracking-wider">Slug (Unique ID)</label>
                    <input
                      type="text"
                      value={llmForm.slug}
                      onChange={(e) => setLlmForm((prev) => ({ ...prev, slug: e.target.value }))}
                      className="w-full bg-[#070707] border border-[#222] rounded-xl px-4 py-3 text-sm text-gray-200 focus:border-blue-500/50 outline-none transition-all font-mono"
                    />
                  </div>

                  {llmForm.provider !== "ollama" && (
                    <div className="space-y-2 md:col-span-2">
                      <label className="text-[10px] font-bold uppercase text-gray-400 tracking-wider">API Key</label>
                      <div className="relative">
                        <input
                          type={showLlmKey ? "text" : "password"}
                          value={llmForm.api_key}
                          onChange={(e) => setLlmForm((prev) => ({ ...prev, api_key: e.target.value }))}
                          className="w-full bg-[#070707] border border-[#222] rounded-xl pl-4 pr-12 py-3 text-sm text-gray-200 focus:border-blue-500/50 outline-none transition-all font-mono"
                          placeholder="Enter API key"
                          autoComplete="new-password"
                        />
                        <button
                          type="button"
                          onClick={() => setShowLlmKey(!showLlmKey)}
                          className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-500 hover:text-white"
                        >
                          {showLlmKey ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                        </button>
                      </div>
                    </div>
                  )}

                  {(llmForm.provider === "ollama" || llmForm.provider === "vllm" || llmForm.provider === "openai") && (
                    <div className="space-y-2 md:col-span-2">
                      <label className="text-[10px] font-bold uppercase text-gray-400 tracking-wider">
                        API Base URL {llmForm.provider !== "ollama" && llmForm.provider !== "vllm" && "(Optional)"}
                      </label>
                      <input
                        type="text"
                        value={llmForm.api_base_url}
                        onChange={(e) => setLlmForm((prev) => ({ ...prev, api_base_url: e.target.value }))}
                        className="w-full bg-[#070707] border border-[#222] rounded-xl px-4 py-3 text-sm text-gray-200 focus:border-blue-500/50 outline-none transition-all font-mono"
                        placeholder={
                          llmForm.provider === "ollama"
                            ? "http://localhost:11434/v1"
                            : llmForm.provider === "vllm"
                              ? "http://localhost:8000/v1"
                              : "https://api.openai.com/v1"
                        }
                      />
                    </div>
                  )}

                  <div className="space-y-2">
                    <label className="text-[10px] font-bold uppercase text-gray-400 tracking-wider">Max Chat Tokens (AION_CHAT_MAX_TOKENS)</label>
                    <input
                      type="number"
                      value={llmForm.max_chat_tokens}
                      onChange={(e) => setLlmForm((prev) => ({ ...prev, max_chat_tokens: parseInt(e.target.value) || 0 }))}
                      className="w-full bg-[#070707] border border-[#222] rounded-xl px-4 py-3 text-sm text-gray-200 focus:border-blue-500/50 outline-none transition-all font-mono"
                      placeholder="e.g. 8192"
                    />
                  </div>

                  <div className="space-y-2">
                    <label className="text-[10px] font-bold uppercase text-gray-400 tracking-wider">Thinking Token Budget (AION_THINKING_TOKEN_BUDGET)</label>
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
                      className="w-full bg-[#070707] border border-[#222] rounded-xl px-4 py-3 text-sm text-gray-200 focus:border-blue-500/50 outline-none transition-all font-mono"
                      placeholder="e.g. 12000 (0 to disable)"
                    />
                  </div>
                </div>
              </div>
            )}

            {/* Step 2: Embeddings */}
            {currentStep === "embeddings" && (
              <div className="space-y-6 animate-in fade-in duration-300">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-xl bg-purple-500/10 flex items-center justify-center border border-purple-500/20">
                    <Zap className="w-5 h-5 text-purple-500" />
                  </div>
                  <div>
                    <h2 className="text-xl font-bold">2. Autonomous Memory (Embeddings)</h2>
                    <p className="text-xs text-gray-400">Configure the model used to create vector embeddings for Long-Term Memory (LTM).</p>
                  </div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
                  <div className="space-y-2">
                    <label className="text-[10px] font-bold uppercase text-gray-400 tracking-wider">Embedding Provider</label>
                    <select
                      value={embForm.provider}
                      onChange={(e) =>
                        setEmbForm((prev) => ({
                          ...prev,
                          provider: e.target.value,
                          model: e.target.value === "google" ? "models/text-embedding-004" : "text-embedding-3-small",
                        }))
                      }
                      className="w-full bg-[#070707] border border-[#222] rounded-xl px-4 py-3 text-sm text-gray-200 focus:border-blue-500/50 outline-none transition-all cursor-pointer"
                    >
                      <option value="openai">OpenAI-Compatible</option>
                      <option value="google">Google (Gemini)</option>
                    </select>
                  </div>

                  <div className="space-y-2">
                    <label className="text-[10px] font-bold uppercase text-gray-400 tracking-wider">Embedding Model</label>
                    <input
                      type="text"
                      value={embForm.model}
                      onChange={(e) => setEmbForm((prev) => ({ ...prev, model: e.target.value }))}
                      className="w-full bg-[#070707] border border-[#222] rounded-xl px-4 py-3 text-sm text-gray-200 focus:border-blue-500/50 outline-none transition-all font-mono"
                      placeholder="e.g. text-embedding-3-small"
                    />
                  </div>

                  <div className="space-y-2 md:col-span-2">
                    <label className="text-[10px] font-bold uppercase text-gray-400 tracking-wider">Embedding API Key</label>
                    <div className="relative">
                      <input
                        type={showEmbKey ? "text" : "password"}
                        value={embForm.api_key}
                        onChange={(e) => setEmbForm((prev) => ({ ...prev, api_key: e.target.value }))}
                        className="w-full bg-[#070707] border border-[#222] rounded-xl pl-4 pr-12 py-3 text-sm text-gray-200 focus:border-blue-500/50 outline-none transition-all font-mono"
                        placeholder="Enter API key"
                        autoComplete="new-password"
                      />
                      <button
                        type="button"
                        onClick={() => setShowEmbKey(!showEmbKey)}
                        className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-500 hover:text-white"
                      >
                        {showEmbKey ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                      </button>
                    </div>
                  </div>

                  <div className="space-y-2 md:col-span-2">
                    <label className="text-[10px] font-bold uppercase text-gray-400 tracking-wider">Embedding Service URL (Optional)</label>
                    <input
                      type="text"
                      value={embForm.url}
                      onChange={(e) => setEmbForm((prev) => ({ ...prev, url: e.target.value }))}
                      className="w-full bg-[#070707] border border-[#222] rounded-xl px-4 py-3 text-sm text-gray-200 focus:border-blue-500/50 outline-none transition-all font-mono"
                      placeholder="e.g. https://api.openai.com/v1"
                    />
                  </div>
                </div>
              </div>
            )}

            {/* Step 3: OCR */}
            {currentStep === "ocr" && (
              <div className="space-y-6">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-xl bg-amber-500/10 flex items-center justify-center border border-amber-500/20">
                      <Eye className="w-5 h-5 text-amber-500" />
                    </div>
                    <div>
                      <h2 className="text-xl font-bold">3. OCR Document Processing</h2>
                      <p className="text-xs text-gray-400">Configure the vision-based OCR service for extracting text from images and scanned PDFs.</p>
                    </div>
                  </div>

                  <button
                    type="button"
                    onClick={() => setOcrEnabled(!ocrEnabled)}
                    className={`w-12 h-6 rounded-full transition-all flex items-center px-1 cursor-pointer ${ocrEnabled ? "bg-amber-500" : "bg-neutral-800"
                      }`}
                  >
                    <div
                      className={`w-4 h-4 rounded-full bg-white transition-all ${ocrEnabled ? "translate-x-6" : "translate-x-0"
                        }`}
                    />
                  </button>
                </div>

                {ocrEnabled ? (
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
                    <div className="space-y-2 md:col-span-2">
                      <label className="text-[10px] font-bold uppercase text-gray-400 tracking-wider">OCR Service Base URL</label>
                      <input
                        type="text"
                        value={ocrForm.base_url}
                        onChange={(e) => setOcrForm((prev) => ({ ...prev, base_url: e.target.value }))}
                        className="w-full bg-[#070707] border border-[#222] rounded-xl px-4 py-3 text-sm text-gray-200 focus:border-blue-500/50 outline-none transition-all font-mono"
                        placeholder="e.g. http://localhost:8002/v1"
                      />
                    </div>

                    <div className="space-y-2">
                      <label className="text-[10px] font-bold uppercase text-gray-400 tracking-wider">OCR Model</label>
                      <input
                        type="text"
                        value={ocrForm.model}
                        onChange={(e) => setOcrForm((prev) => ({ ...prev, model: e.target.value }))}
                        className="w-full bg-[#070707] border border-[#222] rounded-xl px-4 py-3 text-sm text-gray-200 focus:border-blue-500/50 outline-none transition-all font-mono"
                        placeholder=""
                      />
                    </div>

                    <div className="space-y-2">
                      <label className="text-[10px] font-bold uppercase text-gray-400 tracking-wider">OCR API Key</label>
                      <div className="relative">
                        <input
                          type={showOcrKey ? "text" : "password"}
                          value={ocrForm.api_key}
                          onChange={(e) => setOcrForm((prev) => ({ ...prev, api_key: e.target.value }))}
                          className="w-full bg-[#070707] border border-[#222] rounded-xl pl-4 pr-12 py-3 text-sm text-gray-200 focus:border-blue-500/50 outline-none transition-all font-mono"
                          placeholder="Enter API key"
                          autoComplete="new-password"
                        />
                        <button
                          type="button"
                          onClick={() => setShowOcrKey(!showOcrKey)}
                          className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-500 hover:text-white"
                        >
                          {showOcrKey ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                        </button>
                      </div>
                    </div>

                    <div className="space-y-2">
                      <label className="text-[10px] font-bold uppercase text-gray-400 tracking-wider">OCR Max Tokens</label>
                      <input
                        type="number"
                        value={ocrForm.max_tokens}
                        onChange={(e) => setOcrForm((prev) => ({ ...prev, max_tokens: parseInt(e.target.value) || 0 }))}
                        className="w-full bg-[#070707] border border-[#222] rounded-xl px-4 py-3 text-sm text-gray-200 focus:border-blue-500/50 outline-none transition-all font-mono"
                      />
                    </div>

                    <div className="space-y-2">
                      <label className="text-[10px] font-bold uppercase text-gray-400 tracking-wider">OCR Timeout (seconds)</label>
                      <input
                        type="number"
                        value={ocrForm.timeout}
                        onChange={(e) => setOcrForm((prev) => ({ ...prev, timeout: parseInt(e.target.value) || 0 }))}
                        className="w-full bg-[#070707] border border-[#222] rounded-xl px-4 py-3 text-sm text-gray-200 focus:border-blue-500/50 outline-none transition-all font-mono"
                      />
                    </div>

                    <div className="space-y-2 md:col-span-2">
                      <label className="text-[10px] font-bold uppercase text-gray-400 tracking-wider">OCR Max Image Bytes</label>
                      <input
                        type="number"
                        value={ocrForm.max_image_bytes}
                        onChange={(e) => setOcrForm((prev) => ({ ...prev, max_image_bytes: parseInt(e.target.value) || 0 }))}
                        className="w-full bg-[#070707] border border-[#222] rounded-xl px-4 py-3 text-sm text-gray-200 focus:border-blue-500/50 outline-none transition-all font-mono"
                      />
                    </div>
                  </div>
                ) :
                  <>
                    <div className="p-5 rounded-2xl border border-dashed border-[#262626] bg-[#0d0d0d]/30 text-center text-gray-500 text-sm">
                      <Info className="w-8 h-8 mx-auto mb-2 text-gray-600" />
                      OCR document processing is disabled. <br />
                      The agent will run OCR MCP without vision-based text extraction but with basic extraction scripts.
                    </div>
                  </>}
              </div>
            )}

            {/* Step 4: Web Search */}
            {currentStep === "search" && (
              <div className="space-y-6 animate-in fade-in duration-300">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-xl bg-cyan-500/10 flex items-center justify-center border border-cyan-500/20">
                    <Search className="w-5 h-5 text-cyan-500" />
                  </div>
                  <div>
                    <h2 className="text-xl font-bold">4. Web Integration & Search</h2>
                    <p className="text-xs text-gray-400">Configure search engines and page fetching protocols for web operations.</p>
                  </div>
                </div>

                <div className="space-y-5">
                  {/* Tavily */}
                  <div className="p-4 rounded-xl border border-[#222] bg-[#070707]/50 space-y-3">
                    <div className="flex items-center justify-between">
                      <div className="flex flex-col">
                        <span className="text-sm font-bold">Tavily Search</span>
                        <span className="text-xs text-gray-500">Fast AI search engine optimized for LLM agents.</span>
                      </div>
                      <button
                        type="button"
                        onClick={() => setSearchForm((prev) => ({ ...prev, tavily_enabled: !prev.tavily_enabled }))}
                        className={`w-10 h-6 rounded-full transition-all flex items-center px-1 cursor-pointer ${searchForm.tavily_enabled ? "bg-cyan-500" : "bg-neutral-800"
                          }`}
                      >
                        <div
                          className={`w-4 h-4 rounded-full bg-white transition-all ${searchForm.tavily_enabled ? "translate-x-4" : "translate-x-0"
                            }`}
                        />
                      </button>
                    </div>

                    {searchForm.tavily_enabled && (
                      <div className="space-y-1.5 pt-2">
                        <label className="text-[10px] font-bold uppercase text-gray-400 tracking-wider">Tavily API Key</label>
                        <div className="relative">
                          <input
                            type={showTavilyKey ? "text" : "password"}
                            value={searchForm.tavily_key}
                            onChange={(e) => setSearchForm((prev) => ({ ...prev, tavily_key: e.target.value }))}
                            className="w-full bg-[#070707] border border-[#222] rounded-xl pl-4 pr-12 py-2.5 text-sm text-gray-200 focus:border-cyan-500/50 outline-none transition-all font-mono"
                            placeholder="tvly-..."
                            autoComplete="new-password"
                          />
                          <button
                            type="button"
                            onClick={() => setShowTavilyKey(!showTavilyKey)}
                            className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-500 hover:text-white"
                          >
                            {showTavilyKey ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                          </button>
                        </div>
                      </div>
                    )}
                  </div>

                  {/* Brave Search */}
                  <div className="p-4 rounded-xl border border-[#222] bg-[#070707]/50 space-y-3">
                    <div className="flex items-center justify-between">
                      <div className="flex flex-col">
                        <span className="text-sm font-bold">Brave Search</span>
                        <span className="text-xs text-gray-500">Global, private search engine with rich results.</span>
                      </div>
                      <button
                        type="button"
                        onClick={() => setSearchForm((prev) => ({ ...prev, brave_enabled: !prev.brave_enabled }))}
                        className={`w-10 h-6 rounded-full transition-all flex items-center px-1 cursor-pointer ${searchForm.brave_enabled ? "bg-cyan-500" : "bg-neutral-800"
                          }`}
                      >
                        <div
                          className={`w-4 h-4 rounded-full bg-white transition-all ${searchForm.brave_enabled ? "translate-x-4" : "translate-x-0"
                            }`}
                        />
                      </button>
                    </div>

                    {searchForm.brave_enabled && (
                      <div className="space-y-1.5 pt-2">
                        <label className="text-[10px] font-bold uppercase text-gray-400 tracking-wider">Brave API Key</label>
                        <div className="relative">
                          <input
                            type={showBraveKey ? "text" : "password"}
                            value={searchForm.brave_key}
                            onChange={(e) => setSearchForm((prev) => ({ ...prev, brave_key: e.target.value }))}
                            className="w-full bg-[#070707] border border-[#222] rounded-xl pl-4 pr-12 py-2.5 text-sm text-gray-200 focus:border-cyan-500/50 outline-none transition-all font-mono"
                            placeholder="BS..."
                            autoComplete="new-password"
                          />
                          <button
                            type="button"
                            onClick={() => setShowBraveKey(!showBraveKey)}
                            className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-500 hover:text-white"
                          >
                            {showBraveKey ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                          </button>
                        </div>
                      </div>
                    )}
                  </div>

                  {/* SearXNG */}
                  <div className="p-4 rounded-xl border border-[#222] bg-[#070707]/50 space-y-3">
                    <div className="flex items-center justify-between">
                      <div className="flex flex-col">
                        <span className="text-sm font-bold">SearXNG</span>
                        <span className="text-xs text-gray-500">Self-hosted metasearch engine (no API key required).</span>
                      </div>
                      <button
                        type="button"
                        onClick={() => setSearchForm((prev) => ({ ...prev, searxng_enabled: !prev.searxng_enabled }))}
                        className={`w-10 h-6 rounded-full transition-all flex items-center px-1 cursor-pointer ${searchForm.searxng_enabled ? "bg-cyan-500" : "bg-neutral-800"
                          }`}
                      >
                        <div
                          className={`w-4 h-4 rounded-full bg-white transition-all ${searchForm.searxng_enabled ? "translate-x-4" : "translate-x-0"
                            }`}
                        />
                      </button>
                    </div>

                    {searchForm.searxng_enabled && (
                      <div className="space-y-1.5 pt-2">
                        <label className="text-[10px] font-bold uppercase text-gray-400 tracking-wider">SearXNG Base URL</label>
                        <input
                          type="text"
                          value={searchForm.searxng_url}
                          onChange={(e) => setSearchForm((prev) => ({ ...prev, searxng_url: e.target.value }))}
                          className="w-full bg-[#070707] border border-[#222] rounded-xl px-4 py-2.5 text-sm text-gray-200 focus:border-cyan-500/50 outline-none transition-all font-mono"
                          placeholder="e.g. https://searxng.mydomain.org"
                        />
                      </div>
                    )}
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-5 pt-3">
                    <div className="space-y-2">
                      <label className="text-[10px] font-bold uppercase text-gray-400 tracking-wider">Default Search Provider</label>
                      <select
                        value={searchForm.default_provider}
                        onChange={(e) => setSearchForm((prev) => ({ ...prev, default_provider: e.target.value }))}
                        className="w-full bg-[#070707] border border-[#222] rounded-xl px-4 py-3 text-sm text-gray-200 focus:border-cyan-500/50 outline-none transition-all cursor-pointer"
                      >
                        <option value="tavily">Tavily</option>
                        <option value="brave">Brave</option>
                        <option value="searxng">SearXNG</option>
                      </select>
                    </div>

                    <div className="space-y-2">
                      <label className="text-[10px] font-bold uppercase text-gray-400 tracking-wider">Search Fallback Order (CSV)</label>
                      <input
                        type="text"
                        value={searchForm.fallback_order}
                        onChange={(e) => setSearchForm((prev) => ({ ...prev, fallback_order: e.target.value }))}
                        className="w-full bg-[#070707] border border-[#222] rounded-xl px-4 py-3 text-sm text-gray-200 focus:border-cyan-500/50 outline-none transition-all font-mono"
                      />
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* Step 5: Filesystem Policy */}
            {currentStep === "policy" && (
              <div className="space-y-6 animate-in fade-in duration-300">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-xl bg-amber-500/10 flex items-center justify-center border border-amber-500/20">
                      <ShieldAlert className="w-5 h-5 text-amber-500" />
                    </div>
                    <div>
                      <h2 className="text-xl font-bold">5. Sandbox Security & Exec Policy</h2>
                      <p className="text-xs text-gray-400">Restrict or allow terminal commands and filesystem access within the workspace.</p>
                    </div>
                  </div>

                  <button
                    type="button"
                    onClick={() => setPolicyEnabled(!policyEnabled)}
                    className={`w-12 h-6 rounded-full transition-all flex items-center px-1 cursor-pointer ${policyEnabled ? "bg-amber-500" : "bg-neutral-800"
                      }`}
                  >
                    <div
                      className={`w-4 h-4 rounded-full bg-white transition-all ${policyEnabled ? "translate-x-6" : "translate-x-0"
                        }`}
                    />
                  </button>
                </div>

                {policyEnabled ? (
                  <div className="space-y-5 pt-2">
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      {/* Dev Template Card */}
                      <button
                        type="button"
                        onClick={() => handleTemplateChange("dev")}
                        className={`p-4 rounded-xl border text-left flex flex-col gap-1.5 transition-all ${policyTemplate === "dev"
                          ? "bg-amber-500/5 border-amber-500/30 text-amber-300"
                          : "bg-[#070707] border-[#222] text-gray-400 hover:text-white"
                          }`}
                      >
                        <div className="flex items-center gap-2 font-bold text-sm">
                          <Sparkles className="w-4 h-4" /> Development Policy
                        </div>
                        <span className="text-xs opacity-85">
                          Enables a minimal allowlist of commands (`grep`, `wc`, `sort`, `python3`) for local agent operations.
                        </span>
                      </button>

                      {/* Example Template Card */}
                      <button
                        type="button"
                        onClick={() => handleTemplateChange("example")}
                        className={`p-4 rounded-xl border text-left flex flex-col gap-1.5 transition-all ${policyTemplate === "example"
                          ? "bg-amber-500/5 border-amber-500/30 text-amber-300"
                          : "bg-[#070707] border-[#222] text-gray-400 hover:text-white"
                          }`}
                      >
                        <div className="flex items-center gap-2 font-bold text-sm">
                          <Lock className="w-4 h-4" /> Production Policy
                        </div>
                        <span className="text-xs opacity-85">
                          Advanced template with detailed descriptions, strict path boundaries, and hardened execute constraints.
                        </span>
                      </button>
                    </div>

                    <div className="space-y-2">
                      <div className="flex justify-between items-center">
                        <label className="text-[10px] font-bold uppercase text-gray-400 tracking-wider">
                          Policy Blueprint (YAML)
                        </label>
                        <span className="text-[10px] text-gray-500 font-mono">config/fs_policy.yaml</span>
                      </div>
                      <textarea
                        value={policyYaml}
                        onChange={(e) => setPolicyYaml(e.target.value)}
                        rows={20}
                        readOnly
                        className="w-full bg-[#030303] border border-[#222] rounded-xl p-4 text-xs font-mono text-amber-400/90 focus:border-amber-500/40 outline-none transition-all leading-relaxed"
                      />
                    </div>
                  </div>
                ) : (
                  <div className="p-5 rounded-xl border border-dashed border-[#222] bg-[#070707]/30 text-center text-gray-500 text-sm">
                    <Info className="w-8 h-8 mx-auto mb-2 text-gray-600" />
                    Filesystem security policy is disabled. The agent will run with in-code default settings (`exec.enabled=false`).
                  </div>
                )}
              </div>
            )}

            {/* Step 6: Review */}
            {currentStep === "review" && (
              <div className="space-y-6 animate-in fade-in duration-300">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-xl bg-emerald-500/10 flex items-center justify-center border border-emerald-500/20">
                    <Sparkles className="w-5 h-5 text-emerald-500" />
                  </div>
                  <div>
                    <h2 className="text-xl font-bold">6. Review & Initialize</h2>
                    <p className="text-xs text-gray-400">Review your configurations. Once confirmed, the system will apply them.</p>
                  </div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
                  {/* LLM Card */}
                  <div className="p-4 rounded-xl border border-[#222] bg-[#070707] space-y-2">
                    <span className="text-xs text-gray-500 font-bold uppercase tracking-wider">LLM Provider</span>
                    <div className="flex flex-col">
                      <span className="font-bold text-white">{llmForm.display_name}</span>
                      <span className="text-xs text-gray-400 font-mono">
                        {llmForm.provider} / {llmForm.model_name}
                      </span>
                      <span className="text-xs text-gray-500 font-mono mt-1">
                        Max Chat Tokens: {llmForm.max_chat_tokens} | Thinking Budget: {llmForm.thinking_token_budget}
                      </span>
                    </div>
                  </div>

                  {/* Embeddings Card */}
                  <div className="p-4 rounded-xl border border-[#222] bg-[#070707] space-y-2">
                    <span className="text-xs text-gray-500 font-bold uppercase tracking-wider">Memory & Embeddings</span>
                    <div className="flex flex-col">
                      <span className="font-bold text-white">Provider: {embForm.provider}</span>
                      <span className="text-xs text-gray-400 font-mono">Model: {embForm.model}</span>
                    </div>
                  </div>

                  {/* OCR Card */}
                  <div className="p-4 rounded-xl border border-[#222] bg-[#070707] space-y-2">
                    <span className="text-xs text-gray-500 font-bold uppercase tracking-wider">OCR Processing</span>
                    <div className="flex flex-col">
                      <span className="font-bold text-white">
                        {ocrEnabled && ocrForm.base_url ? ocrForm.base_url : "Disabled"}
                      </span>
                      <span className="text-xs text-gray-400 font-mono">
                        {ocrEnabled ? `Model: ${ocrForm.model} | Key: ${ocrForm.api_key ? "••••••••" : "None"}` : "OCR capabilities will be inactive."}
                      </span>
                    </div>
                  </div>

                  {/* Web Search Card */}
                  <div className="p-4 rounded-xl border border-[#222] bg-[#070707] space-y-2">
                    <span className="text-xs text-gray-500 font-bold uppercase tracking-wider">Web Integration</span>
                    <div className="flex flex-wrap gap-1.5 pt-1">
                      {searchForm.tavily_enabled && (
                        <span className="px-2 py-0.5 rounded bg-cyan-500/10 border border-cyan-500/20 text-cyan-400 text-xs font-bold">
                          Tavily
                        </span>
                      )}
                      {searchForm.brave_enabled && (
                        <span className="px-2 py-0.5 rounded bg-cyan-500/10 border border-cyan-500/20 text-cyan-400 text-xs font-bold">
                          Brave
                        </span>
                      )}
                      {searchForm.searxng_enabled && (
                        <span className="px-2 py-0.5 rounded bg-cyan-500/10 border border-cyan-500/20 text-cyan-400 text-xs font-bold">
                          SearXNG
                        </span>
                      )}
                      {!searchForm.tavily_enabled && !searchForm.brave_enabled && !searchForm.searxng_enabled && (
                        <span className="text-xs text-gray-500">No Web Search enabled</span>
                      )}
                    </div>
                  </div>

                  {/* Policy Card */}
                  <div className="p-4 rounded-xl border border-[#222] bg-[#070707] space-y-2">
                    <span className="text-xs text-gray-500 font-bold uppercase tracking-wider">Sandbox Security</span>
                    <div className="flex flex-col">
                      <span className="font-bold text-white">
                        {policyEnabled ? `Enabled (${policyTemplate} template)` : "Disabled"}
                      </span>
                      <span className="text-xs text-gray-400 font-mono">config/fs_policy.yaml</span>
                    </div>
                  </div>
                </div>

                <div className="p-4 rounded-xl bg-blue-500/10 border border-blue-500/20 text-blue-300 flex items-start gap-3 text-xs leading-relaxed">
                  <Info className="w-5 h-5 shrink-0 mt-0.5" />
                  <div>
                    Clicking the initialization button will save these variables to your `.env` file and write the sandbox policy YAML.
                    If you are running in Docker, the container will restart automatically. If you are in local dev, you will need to restart the Python process manually.
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Footer Controls */}
          <div className="flex justify-between items-center">
            {currentStep !== "llm" ? (
              <button
                type="button"
                onClick={() => {
                  setError(null);
                  const idx = stepsOrder.indexOf(currentStep);
                  setCurrentStep(stepsOrder[idx - 1]);
                }}
                className="flex items-center gap-2 px-5 py-2.5 rounded-xl border border-[#222] bg-[#0d0d0d] text-gray-400 hover:text-white transition-all active:scale-95 cursor-pointer"
              >
                <ChevronLeft className="w-4 h-4" /> Back
              </button>
            ) : (
              <div />
            )}

            {currentStep !== "review" ? (
              <button
                type="button"
                onClick={handleNext}
                className="flex items-center gap-2 px-6 py-2.5 rounded-xl bg-blue-600 hover:bg-blue-500 text-white font-bold transition-all shadow-lg shadow-blue-500/20 active:scale-95 cursor-pointer"
              >
                Next <ChevronRight className="w-4 h-4" />
              </button>
            ) : (
              <button
                type="button"
                onClick={handleSave}
                disabled={loading}
                className="flex items-center gap-2 px-8 py-3 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white font-bold transition-all shadow-lg shadow-emerald-500/20 active:scale-95 disabled:opacity-50 cursor-pointer"
              >
                {loading ? <Loader2 className="animate-spin w-4 h-4" /> : <Check className="w-4 h-4" />}
                Initialize AION Kernel
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
