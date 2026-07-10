export type LlmModelHint = {
  context_window: number;
  suggested_max_chat_tokens: number;
};

type LlmProbeModel = {
  id: string;
};

export type LlmProbeResponse = {
  healthy: boolean;
  latency_ms: number;
  litellm_provider: string;
  base_url: string;
  models_source: "live" | "catalog";
  catalog_count?: number;
  warning?: string | null;
  models: {
    data: LlmProbeModel[];
    hints?: Record<string, LlmModelHint>;
  };
};

export type ModelProbeKind = "chat" | "embedding" | "ocr";

const EMBEDDING_MODEL_RE = /embed/i;
const OCR_MODEL_RE = /ocr|glm-ocr|vision|pixtral|qwen.*vl|llava/i;

export function modelIdsFromProbe(result: LlmProbeResponse): string[] {
  return (result.models?.data ?? []).map((m) => m.id).filter(Boolean);
}

export function filterModelsForKind(ids: string[], kind: ModelProbeKind): string[] {
  if (kind === "embedding") {
    const embedding = ids.filter((id) => EMBEDDING_MODEL_RE.test(id));
    return embedding.length ? embedding : ids;
  }
  if (kind === "ocr") {
    const ocr = ids.filter((id) => OCR_MODEL_RE.test(id));
    return ocr.length ? ocr : ids;
  }
  const chat = ids.filter((id) => !EMBEDDING_MODEL_RE.test(id));
  return chat.length ? chat : ids;
}

export function hintForModel(
  result: LlmProbeResponse | null,
  modelId: string,
): LlmModelHint | null {
  if (!result?.models?.hints || !modelId) return null;
  return result.models.hints[modelId] ?? null;
}

export function validateMaxChatTokens(
  maxChatTokens: number,
  thinkingBudget: number,
  hint: LlmModelHint | null,
): string | null {
  if (!Number.isFinite(maxChatTokens) || maxChatTokens <= 0) {
    return "Max Chat Tokens must be a positive integer.";
  }
  if (!hint) return null;
  const ctx = hint.context_window;
  const total = maxChatTokens + Math.max(0, thinkingBudget || 0);
  if (maxChatTokens >= ctx) {
    return (
      `Max Chat Tokens (${maxChatTokens}) must be below the model context window (${ctx}). ` +
      "Use a lower value to leave room for the conversation prompt."
    );
  }
  if (total >= ctx) {
    return (
      `Max Chat Tokens + thinking budget (${total}) exceed the model context window (${ctx}). ` +
      "Reduce one or both values."
    );
  }
  return null;
}

export function providerNeedsBaseUrl(provider: string): boolean {
  return ["ollama", "vllm"].includes(provider);
}

export function providerSupportsProbe(provider: string): boolean {
  return ["openai", "anthropic", "gemini", "ollama", "vllm", "google"].includes(provider);
}

const LOOPBACK_HOSTS = new Set(["localhost", "127.0.0.1", "::1"]);

function isPrivateOrLocalHost(hostname: string): boolean {
  const h = (hostname || "").trim().toLowerCase();
  if (!h || LOOPBACK_HOSTS.has(h)) return true;
  if (/^(10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)/.test(h)) return true;
  if (/^169\.254\./.test(h)) return true;
  return false;
}

/** Map UI provider + URL to backend probe provider (SSRF-safe self-hosted detection). */
function resolveProbeProvider(provider: string, apiBaseUrl?: string | null): string {
  const p = (provider || "openai").trim().toLowerCase();
  if (p === "ollama" || p === "vllm") return p;

  const raw = (apiBaseUrl || "").trim();
  if (!raw) return p;

  try {
    const url = new URL(raw.startsWith("http") ? raw : `http://${raw}`);
    const host = url.hostname.toLowerCase();
    if (LOOPBACK_HOSTS.has(host)) {
      return url.port === "11434" || url.host.includes("11434") ? "ollama" : "vllm";
    }
    if (isPrivateOrLocalHost(host)) return "vllm";
  } catch {
    /* keep original provider */
  }
  return p;
}

export function embeddingProviderToProbeProvider(provider: string): string {
  return provider === "google" ? "gemini" : "openai";
}

export function pickDefaultModel(ids: string[], kind: ModelProbeKind): string {
  const pool = filterModelsForKind(ids, kind);
  return pool[0] ?? "";
}

export function formatModelDisplayName(modelId: string): string {
  const tail = modelId.split(/[/:]/).pop() || modelId;
  return tail.replace(/[-_]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function slugFromModelId(modelId: string, prefix = "default"): string {
  const base = modelId
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 40);
  return base ? `${prefix}-${base}` : prefix;
}

/** Strip /embeddings suffix to probe GET /v1/models on the service base. */
export function probeBaseUrlFromServiceUrl(serviceUrl: string): string {
  const trimmed = (serviceUrl || "").trim().replace(/\/$/, "");
  if (!trimmed) return "";
  return trimmed.replace(/\/embeddings$/i, "");
}

/** Strip /chat/completions suffix for OCR OpenAI-compatible bases. */
export function probeBaseUrlFromOcrServiceUrl(serviceUrl: string): string {
  const trimmed = (serviceUrl || "").trim().replace(/\/$/, "");
  if (!trimmed) return "";
  return trimmed.replace(/\/chat\/completions$/i, "");
}

/** Normalize stored AION_EMBEDDING_URL (POST target). */
export function embeddingServiceUrlFromProbeBase(baseUrl: string): string {
  const base = (baseUrl || "").trim().replace(/\/$/, "");
  if (!base) return "";
  if (/\/embeddings$/i.test(base)) return base;
  return `${base}/embeddings`;
}


export async function runModelProbe(
  apiFetchFn: (input: string, init?: RequestInit) => Promise<Response>,
  apiBaseUrl: string,
  body: { provider: string; api_base_url?: string | null; api_key?: string | null },
): Promise<LlmProbeResponse> {
  const probeProvider = resolveProbeProvider(body.provider, body.api_base_url);
  const res = await apiFetchFn(`${apiBaseUrl}/admin/llm-providers/probe`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...body, provider: probeProvider }),
  });
  if (!res.ok) {
    const errData = await res.json().catch(() => ({}));
    throw new Error(
      typeof errData.detail === "string" ? errData.detail : "Connection test failed.",
    );
  }
  return (await res.json()) as LlmProbeResponse;
}
