export type LlmModelHint = {
  context_window: number;
  suggested_max_chat_tokens: number;
};

export type LlmProbeModel = {
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

export function modelIdsFromProbe(result: LlmProbeResponse): string[] {
  return (result.models?.data ?? []).map((m) => m.id).filter(Boolean);
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
  return ["openai", "anthropic", "gemini", "ollama", "vllm"].includes(provider);
}
