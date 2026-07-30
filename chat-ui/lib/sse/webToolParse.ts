/** Parse web_search / web_fetch_page tool payloads (JSON or TOON) for chat-ui cards. */

export type ParsedWebSearch = {
  query: string;
  provider?: string;
  error?: string;
  results: Array<{ title: string; url: string; provider?: string; snippet?: string }>;
};

export type ParsedWebFetch = {
  url: string;
  error?: string;
  mode?: string;
  textLen?: number;
};

function unwrapToonFence(raw: string): string {
  const t = String(raw || "").trim();
  if (!t.startsWith("```toon")) return t;
  return t.replace(/^```toon\s*\n?/, "").replace(/\n?```\s*$/, "").trim();
}

function parseToonScalar(value: string): string {
  const v = value.trim();
  if (v.startsWith('"') && v.endsWith('"')) {
    try {
      return JSON.parse(v) as string;
    } catch {
      return v.slice(1, -1);
    }
  }
  return v;
}

/** Parse one CSV row from buffer; quoted fields may span newlines. */
function consumeCsvRow(
  buf: string,
  fieldCount: number,
): { cells: string[]; end: number } | null {
  const cells: string[] = [];
  let cur = "";
  let inQuotes = false;
  let i = 0;
  const n = buf.length;

  while (i < n) {
    const ch = buf[i];
    if (ch === '"') {
      if (inQuotes && buf[i + 1] === '"') {
        cur += '"';
        i += 2;
        continue;
      }
      inQuotes = !inQuotes;
      i += 1;
      continue;
    }
    if (ch === "," && !inQuotes) {
      cells.push(parseToonScalar(cur));
      cur = "";
      i += 1;
      if (cells.length === fieldCount - 1) {
        let last = "";
        let inQ = false;
        while (i < n) {
          const c = buf[i];
          if (c === '"') {
            if (inQ && buf[i + 1] === '"') {
              last += '"';
              i += 2;
              continue;
            }
            inQ = !inQ;
            i += 1;
            continue;
          }
          if ((c === "\n" || c === "\r") && !inQ) break;
          last += c;
          i += 1;
        }
        cells.push(parseToonScalar(last));
        while (i < n && (buf[i] === "\r" || buf[i] === "\n")) i += 1;
        return { cells, end: i };
      }
      continue;
    }
    cur += ch;
    i += 1;
  }

  if (cells.length === fieldCount - 1 && !inQuotes) {
    cells.push(parseToonScalar(cur));
    return { cells, end: n };
  }
  return null;
}

function parseTabularRows(blob: string, fieldCount: number): string[][] {
  const rows: string[][] = [];
  let pos = 0;
  const text = blob.trim();
  while (pos < text.length) {
    while (pos < text.length && /\s/.test(text[pos]!)) pos += 1;
    if (pos >= text.length) break;
    const hit = consumeCsvRow(text.slice(pos), fieldCount);
    if (!hit) break;
    rows.push(hit.cells);
    pos += hit.end;
  }
  return rows;
}

function parseToonWebSearch(body: string): ParsedWebSearch | null {
  const lines = body.split("\n");
  let query = "";
  let provider: string | undefined;
  let error: string | undefined;
  const results: ParsedWebSearch["results"] = [];

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const tabular = line.match(/^results\[(\d+)\]\{([^}]+)\}:$/);
    if (tabular) {
      const fields = tabular[2].split(",").map((f) => f.trim());
      const expected = Number.parseInt(tabular[1], 10);
      i += 1;
      const section: string[] = [];
      while (i < lines.length) {
        const rowLine = lines[i]!;
        const trimmed = rowLine.trim();
        if (section.length > 0 && /^[a-zA-Z_][\w]*:\s/.test(trimmed) && !rowLine.startsWith("  ")) {
          break;
        }
        if (section.length === 0 && !rowLine.startsWith("  ")) break;
        section.push(rowLine.startsWith("  ") ? rowLine.slice(2) : rowLine);
        const parsed = parseTabularRows(section.join("\n"), fields.length);
        if (parsed.length >= expected) {
          i += 1;
          break;
        }
        i += 1;
      }
      for (const cells of parseTabularRows(section.join("\n"), fields.length)) {
        const row: Record<string, string> = {};
        fields.forEach((f, idx) => {
          row[f] = cells[idx] ?? "";
        });
        results.push({
          title: row.title || row.url || "Fonte",
          url: (row.url || "").trim(),
          provider: row.provider || undefined,
          snippet: row.snippet || undefined,
        });
      }
      i -= 1;
      continue;
    }

    const kv = line.match(/^([a-zA-Z_][\w]*):\s*(.*)$/);
    if (!kv) continue;
    const key = kv[1];
    const val = kv[2];
    if (key === "query") query = parseToonScalar(val);
    else if (key === "provider_used" || key === "provider") provider = parseToonScalar(val);
    else if (key === "error") error = parseToonScalar(val);
  }

  if (!query && !error && results.length === 0) return null;
  return { query, provider, error, results };
}

function parseToonWebFetch(body: string): ParsedWebFetch | null {
  const lines = body.split("\n");
  let url = "";
  let error: string | undefined;
  let mode: string | undefined;
  let textLen: number | undefined;
  let textBlock: string[] = [];
  let inText = false;

  for (const line of lines) {
    if (inText) {
      if (line.startsWith("  ")) {
        textBlock.push(line.slice(2));
      } else {
        inText = false;
      }
      continue;
    }
    if (line === "text: |") {
      inText = true;
      continue;
    }
    const kv = line.match(/^([a-zA-Z_][\w]*):\s*(.*)$/);
    if (!kv) continue;
    const key = kv[1];
    const val = kv[2];
    if (key === "url") url = parseToonScalar(val);
    else if (key === "error") error = parseToonScalar(val);
    else if (key === "mode") mode = parseToonScalar(val);
    else if (key === "chars") {
      const n = Number.parseInt(val, 10);
      if (!Number.isNaN(n)) textLen = n;
    } else if (key === "text" && val) {
      const t = parseToonScalar(val);
      textLen = t.length;
    }
  }

  if (textBlock.length) {
    textLen = textBlock.join("\n").length;
  }
  if (!url && !error) return null;
  return { url, error, mode, textLen };
}

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
  const text = String(raw ?? "").trim();
  if (!text) return null;

  if (text.startsWith("```toon")) {
    return parseToonWebSearch(unwrapToonFence(text));
  }

  const j = tryParseJsonObject(text);
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
      snippet:
        typeof o.snippet === "string"
          ? o.snippet
          : typeof o.content === "string"
            ? o.content
            : undefined,
    };
  });
  return { query: q, provider: prov, error: err, results };
}

export function parseWebFetchOutput(raw: string | undefined | null): ParsedWebFetch | null {
  const text = String(raw ?? "").trim();
  if (!text) return null;

  if (text.startsWith("```toon")) {
    return parseToonWebFetch(unwrapToonFence(text));
  }

  const j = tryParseJsonObject(text);
  if (!j) return null;
  return {
    url: String(j.url || ""),
    error: typeof j.error === "string" ? j.error : undefined,
    mode: typeof j.mode === "string" ? j.mode : undefined,
    textLen: typeof j.text === "string" ? j.text.length : undefined,
  };
}

/** Build web source cards from tool output (JSON or TOON). */
export function webSearchSourceRows(
  raw: string | undefined | null,
): Array<{ title: string; url: string; provider?: string }> {
  const parsed = parseWebSearchOutput(raw);
  if (!parsed?.results.length) return [];
  return parsed.results
    .filter((r) => r.url)
    .map((r) => ({
      title: r.title,
      url: r.url,
      provider: r.provider,
    }));
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
