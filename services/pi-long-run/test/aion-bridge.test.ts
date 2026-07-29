import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";

vi.mock("node:fs", () => ({
  readFileSync: vi.fn(() =>
    JSON.stringify([
      {
        name: "web_fetch_page",
        description: "fetch",
        parameters: { type: "object", properties: { url: { type: "string" } } },
      },
    ]),
  ),
}));

import { createAionBridgeExtension } from "../extensions/aion-bridge.js";

describe("createAionBridgeExtension", () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    global.fetch = vi.fn();
  });

  afterEach(() => {
    global.fetch = originalFetch;
    vi.clearAllMocks();
  });

  it("sends call_id and forwards details from backend", async () => {
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      json: async () => ({
        content: "[AION offload] preview",
        is_error: false,
        details: { offload_path: "derived/tool_results/0001_x.txt" },
      }),
    });

    let registeredTool:
      | {
          execute: (
            id: string,
            params: Record<string, unknown>,
          ) => Promise<{ details?: Record<string, unknown> }>;
        }
      | undefined;

    const pi = {
      registerTool: (tool: {
        execute: (
          id: string,
          params: Record<string, unknown>,
        ) => Promise<{ details?: Record<string, unknown> }>;
      }) => {
        registeredTool = tool;
      },
    };

    const ext = createAionBridgeExtension(
      {
        invokeUrl: "http://127.0.0.1:8001/internal/pi/tools/invoke",
        invokeSecret: "secret",
        sessionId: "sess-12345678",
        profile: "aion_std",
        userId: "u1",
      },
      "/tmp/manifest.json",
    );
    ext(pi as never);

    expect(registeredTool).toBeDefined();
    const out = await registeredTool!.execute("call-xyz", {
      url: "https://example.com",
    });

    expect(global.fetch).toHaveBeenCalledWith(
      "http://127.0.0.1:8001/internal/pi/tools/invoke",
      expect.objectContaining({
        method: "POST",
        body: expect.stringContaining('"call_id":"call-xyz"'),
      }),
    );
    expect(out.details?.offload_path).toBe("derived/tool_results/0001_x.txt");
  });
});
