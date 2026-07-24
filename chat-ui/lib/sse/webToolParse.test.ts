import { describe, expect, it } from "vitest";

import {
  parseWebFetchOutput,
  parseWebSearchOutput,
  webSearchQueryFromInput,
} from "./webToolParse";

describe("webToolParse", () => {
  it("parses web_search JSON output", () => {
    const raw = JSON.stringify({
      query: "mondiali 2026",
      provider_used: "tavily",
      results: [{ title: "FIFA", url: "https://fifa.com" }],
    });
    const parsed = parseWebSearchOutput(raw);
    expect(parsed?.query).toBe("mondiali 2026");
    expect(parsed?.results).toHaveLength(1);
  });

  it("extracts JSON object from truncated wrapper text", () => {
    const inner = JSON.stringify({ url: "https://a.org", text: "hello" });
    const wrapped = `garbage prefix ${inner} [AION: truncated]`;
    const parsed = parseWebFetchOutput(wrapped);
    expect(parsed?.url).toBe("https://a.org");
    expect(parsed?.textLen).toBe(5);
  });

  it("reads query from tool input object", () => {
    expect(webSearchQueryFromInput({ query: "test query" })).toBe("test query");
  });
});
