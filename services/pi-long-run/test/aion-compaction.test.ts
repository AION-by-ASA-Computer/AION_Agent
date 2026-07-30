import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { createAionCompactionExtension } from "../extensions/aion-compaction.js";

describe("createAionCompactionExtension", () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    global.fetch = vi.fn();
  });

  afterEach(() => {
    global.fetch = originalFetch;
    vi.clearAllMocks();
  });

  it("returns undefined when backend fails", async () => {
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: false,
      status: 500,
    });

    let handler:
      | ((event: unknown, ctx: { signal?: AbortSignal }) => Promise<unknown>)
      | undefined;
    const pi = {
      on: (event: string, fn: typeof handler) => {
        if (event === "session_before_compact") {
          handler = fn;
        }
      },
    };

    const ext = createAionCompactionExtension({
      apiBaseUrl: "http://127.0.0.1:8001",
      invokeSecret: "",
      sessionId: "sess-12345678",
      enabled: true,
    });
    ext(pi as never);

    const result = await handler!(
      {
        preparation: {
          messagesToSummarize: [{ role: "user", content: "hi" }],
          firstKeptEntryId: "e1",
          tokensBefore: 1000,
          fileOps: {},
          previousSummary: "",
        },
        customInstructions: "",
      },
      { signal: undefined },
    );
    expect(result).toBeUndefined();
  });

  it("returns compaction payload when backend succeeds", async () => {
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      json: async () => ({
        summary: "## Goal\nContinue",
        details: { toolLedger: ["1 web_fetch_page"] },
      }),
    });

    let handler:
      | ((event: unknown, ctx: { signal?: AbortSignal }) => Promise<unknown>)
      | undefined;
    const pi = {
      on: (event: string, fn: typeof handler) => {
        if (event === "session_before_compact") {
          handler = fn;
        }
      },
    };

    const ext = createAionCompactionExtension({
      apiBaseUrl: "http://127.0.0.1:8001",
      invokeSecret: "",
      sessionId: "sess-12345678",
      enabled: true,
    });
    ext(pi as never);

    const result = (await handler!(
      {
        preparation: {
          messagesToSummarize: [{ role: "user", content: "hello" }],
          firstKeptEntryId: "entry-2",
          tokensBefore: 5000,
          fileOps: { readFiles: ["a.txt"] },
          previousSummary: "",
        },
        customInstructions: "focus",
      },
      { signal: undefined },
    )) as { compaction?: { summary?: string; details?: Record<string, unknown> } };

    expect(result?.compaction?.summary).toContain("Goal");
    expect(result?.compaction?.firstKeptEntryId).toBe("entry-2");
    expect(result?.compaction?.details?.toolLedger).toEqual(["1 web_fetch_page"]);
  });
});
