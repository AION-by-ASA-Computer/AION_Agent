import { describe, expect, it } from "vitest";

import {
  parseWebFetchOutput,
  parseWebSearchOutput,
  webSearchQueryFromInput,
  webSearchSourceRows,
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

  it("parses web_search TOON output", () => {
    const raw = `\`\`\`toon
query: "mondiali 2026"
provider_used: tavily
results[1]{title,url,snippet,provider}:
  FIFA,https://fifa.com,World Cup,tavily
\`\`\``;
    const parsed = parseWebSearchOutput(raw);
    expect(parsed?.query).toBe("mondiali 2026");
    expect(parsed?.provider).toBe("tavily");
    expect(parsed?.results).toHaveLength(1);
    expect(parsed?.results[0]?.url).toBe("https://fifa.com");
  });

  it("parses web_fetch TOON output with multiline text", () => {
    const raw = `\`\`\`toon
url: "https://en.wikipedia.org/wiki/2026_FIFA_World_Cup_knockout_stage"
mode: wikipedia_section
chars: 1200
text: |
  Mexico 2 - 1 England
  Attendance: 87432
\`\`\``;
    const parsed = parseWebFetchOutput(raw);
    expect(parsed?.url).toContain("wikipedia.org");
    expect(parsed?.mode).toBe("wikipedia_section");
    expect(parsed?.textLen).toBeGreaterThan(10);
  });

  it("extracts JSON object from truncated wrapper text", () => {
    const inner = JSON.stringify({ url: "https://a.org", text: "hello" });
    const wrapped = `garbage prefix ${inner} [AION: truncated]`;
    const parsed = parseWebFetchOutput(wrapped);
    expect(parsed?.url).toBe("https://a.org");
    expect(parsed?.textLen).toBe(5);
  });

  it("parses web_search TOON with multiline quoted snippets", () => {
    const raw = `\`\`\`toon
query: group a results
provider_used: tavily
results[2]{title,url,snippet,provider}:
  "Czechia vs. Mexico, South Africa vs. South Korea","https://bleacherreport.com/live","| W | D | L |
 ---  --- |
| 1. Mexico | 3 | 0 | 0 |",tavily
  2026 FIFA World Cup Group A,"https://en.wikipedia.org/wiki/2026_FIFA_World_Cup_Group_A","| Team | Match 1 |
| Mexico | 1 |",tavily
\`\`\``;
    const parsed = parseWebSearchOutput(raw);
    expect(parsed?.results).toHaveLength(2);
    expect(parsed?.results[0]?.url).toContain("bleacherreport.com");
    expect(parsed?.results[1]?.url).toContain("wikipedia.org");
  });

  it("webSearchSourceRows works with TOON", () => {
    const raw = `\`\`\`toon
query: q
results[2]{title,url,snippet,provider}:
  A,https://a.org,,tavily
  B,https://b.org,,tavily
\`\`\``;
    const rows = webSearchSourceRows(raw);
    expect(rows).toHaveLength(2);
    expect(rows[1]?.url).toBe("https://b.org");
  });

  it("reads query from tool input object", () => {
    expect(webSearchQueryFromInput({ query: "test query" })).toBe("test query");
  });
});
