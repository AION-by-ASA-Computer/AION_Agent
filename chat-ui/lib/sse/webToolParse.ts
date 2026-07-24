/** Parse web_search / web_fetch_page tool payloads for chat-ui cards. */

export type ParsedWebSearch = {
  query: string;
  provider?: string;
  error?: string;
  results: Array<{ title: string; url: string; provider?: string }>;
};

export type ParsedWebFetch = {
  url: string;
  error?: string;
  mode?: string;
  textLen?: number;
};

function tryParseJsonObject(raw: string): Record<string, unknown> | null {
  const t = String(raw || "").trim();
  if (!t) return null;
  try {
    const j = JSON.parse(t) as unknown;
    return j && typeof j === "object" && !Array.isArray(j)
      ? (j as Record<string, unknown>)
      : null;
  } catch {
    const start = t.indexOf("{");
    const end = t.lastIndexOf("}");
    if (start < 0 || end <= start) return null;
    try {
      const j = JSON.parse(t.slice(start, end + 1)) as unknown;
      return j && typeof j === "object" && !Array.isArray(j)
        ? (j as Record<string, unknown>)
        : null;
    } catch {
      return null;
    }
  }
}

export function parseWebSearchOutput(raw: string | undefined | null): ParsedWebSearch | null {
  const j = tryParseJsonObject(String(raw ?? ""));
  if (!j) return null;
  const q = typeof j.query === "string" ? j.query : "";
  const err = typeof j.error === "string" ? j.error : undefined;
  const prov =
    typeof j.provider_used === "string"
      ? j.provider_used
      : typeof j.provider === "string"
        ? j.provider
        : undefined;
  const rows = Array.isArray(j.results) ? j.results : [];
  const results = rows.map((r) => {
    const o = r as Record<string, unknown>;
    return {
      title: String(o.title || o.url || "Fonte"),
      url: String(o.url || "").trim(),
      provider: o.provider != null ? String(o.provider) : undefined,
    };
  });
  return { query: q, provider: prov, error: err, results };
}

export function parseWebFetchOutput(raw: string | undefined | null): ParsedWebFetch | null {
  const j = tryParseJsonObject(String(raw ?? ""));
  if (!j) return null;
  return {
    url: String(j.url || ""),
    error: typeof j.error === "string" ? j.error : undefined,
    mode: typeof j.mode === "string" ? j.mode : undefined,
    textLen: typeof j.text === "string" ? j.text.length : undefined,
  };
}

export function webSearchQueryFromInput(input: unknown): string {
  if (input == null) return "";
  if (typeof input === "string") {
    const trimmed = input.trim();
    if (!trimmed.startsWith("{")) return trimmed;
    try {
      const j = JSON.parse(trimmed) as Record<string, unknown>;
      return typeof j.query === "string" ? j.query : "";
    } catch {
      return "";
    }
  }
  if (typeof input === "object" && "query" in (input as object)) {
    return String((input as { query?: unknown }).query ?? "");
  }
  return "";
}

export function webFetchUrlFromInput(input: unknown): string {
  if (input == null) return "";
  if (typeof input === "string") {
    const trimmed = input.trim();
    if (!trimmed.startsWith("{")) return trimmed;
    try {
      const j = JSON.parse(trimmed) as Record<string, unknown>;
      return typeof j.url === "string" ? j.url : "";
    } catch {
      return "";
    }
  }
  if (typeof input === "object" && "url" in (input as object)) {
    return String((input as { url?: unknown }).url ?? "");
  }
  return "";
}
