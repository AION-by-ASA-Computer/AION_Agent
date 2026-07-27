import { describe, expect, it, vi, beforeEach } from "vitest";

vi.mock("@earendil-works/pi-coding-agent", () => {
  class DefaultResourceLoader {
    reload = vi.fn().mockResolvedValue(undefined);
    constructor(_opts: unknown) {}
  }

  const mockSession = {
    setModel: vi.fn().mockResolvedValue(undefined),
    supportsThinking: vi.fn().mockReturnValue(true),
    setThinkingLevel: vi.fn(),
    dispose: vi.fn(),
    subscribe: vi.fn(),
    prompt: vi.fn(),
    messages: [],
    modelRuntime: {
      getModel: vi.fn().mockReturnValue({ id: "test-model", provider: "aion" }),
    },
  };

  return {
    createAgentSession: vi.fn().mockResolvedValue({ session: mockSession }),
    DefaultResourceLoader,
    SessionManager: {
      create: vi.fn().mockReturnValue({}),
    },
  };
});

import { createAgentSession } from "@earendil-works/pi-coding-agent";
import { ensurePiSession } from "../src/session-factory.js";

describe("ensurePiSession", () => {
  beforeEach(() => {
    vi.mocked(createAgentSession).mockClear();
  });

  it("does not pass tools:[] allowlist (blocks bridged tools)", async () => {
    const session = {
      setModel: vi.fn().mockResolvedValue(undefined),
      supportsThinking: vi.fn().mockReturnValue(false),
      setThinkingLevel: vi.fn(),
      dispose: vi.fn(),
      getAllTools: vi.fn().mockReturnValue([{ name: "skill_view" }, { name: "web_search" }]),
      modelRuntime: {
        getModel: vi.fn().mockReturnValue({ id: "AIONQ35-35-Q8B", provider: "aion" }),
      },
    };
    vi.mocked(createAgentSession).mockResolvedValueOnce({ session } as never);

    await ensurePiSession({
      session_id: "sess-tools-test",
      workspace_dir: "/tmp/ws",
      agent_dir: "/tmp/agent",
      model_id: "AIONQ35-35-Q8B",
    });

    const call = vi.mocked(createAgentSession).mock.calls[0]?.[0];
    expect(call).toBeDefined();
    expect(call?.noTools).toBe("builtin");
    expect(call).not.toHaveProperty("tools");
  });

  it("reuses an existing in-memory session on second ensure", async () => {
    const session = {
      setModel: vi.fn().mockResolvedValue(undefined),
      supportsThinking: vi.fn().mockReturnValue(false),
      setThinkingLevel: vi.fn(),
      dispose: vi.fn(),
      getAllTools: vi.fn().mockReturnValue([]),
      modelRuntime: {
        getModel: vi.fn().mockReturnValue({ id: "AIONQ35-35-Q8B", provider: "aion" }),
      },
    };
    vi.mocked(createAgentSession).mockResolvedValue({ session } as never);

    const payload = {
      session_id: "sess-reuse-test",
      workspace_dir: "/tmp/ws",
      agent_dir: "/tmp/agent",
      model_id: "AIONQ35-35-Q8B",
    };
    const first = await ensurePiSession(payload);
    const second = await ensurePiSession(payload);

    expect(first.created).toBe(true);
    expect(second.created).toBe(false);
    expect(createAgentSession).toHaveBeenCalledTimes(1);
    expect(session.dispose).not.toHaveBeenCalled();
  });
});
