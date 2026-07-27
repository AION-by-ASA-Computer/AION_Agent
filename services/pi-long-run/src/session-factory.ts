import { join } from "node:path";
import {
  createAgentSession,
  DefaultResourceLoader,
  SessionManager,
  type AgentSession,
} from "@earendil-works/pi-coding-agent";
import { createAionBridgeExtension } from "../extensions/aion-bridge.js";

export type SessionCreatePayload = {
  session_id: string;
  workspace_dir: string;
  agent_dir: string;
  model_id?: string;
  provider_id?: string;
  thinking_level?: string;
  tool_manifest_path?: string;
  invoke_url?: string;
  invoke_secret?: string;
  profile?: string;
  user_id?: string;
};

type ManagedSession = {
  session: AgentSession;
  dispose: () => void;
};

const sessions = new Map<string, ManagedSession>();

export async function ensurePiSession(
  payload: SessionCreatePayload,
): Promise<{ created: boolean }> {
  const existing = sessions.get(payload.session_id);
  if (existing) {
    // Reuse in-memory Pi session so multi-turn chats keep tool/results context.
    return { created: false };
  }

  const cwd = payload.workspace_dir;
  const agentDir = payload.agent_dir;
  const manifestPath =
    payload.tool_manifest_path || join(agentDir, "tool_manifest.json");

  const bridge = createAionBridgeExtension(
    {
      invokeUrl: payload.invoke_url || "http://127.0.0.1:8001/internal/pi/tools/invoke",
      invokeSecret: payload.invoke_secret || "",
      sessionId: payload.session_id,
      profile: payload.profile || "generic_assistant",
      userId: payload.user_id || "default",
    },
    manifestPath,
  );

  const resourceLoader = new DefaultResourceLoader({
    cwd,
    agentDir,
    extensionFactories: [bridge],
  });
  await resourceLoader.reload();

  const sessionDir = join(agentDir, "sessions");
  const { session } = await createAgentSession({
    cwd,
    agentDir,
    resourceLoader,
    sessionManager: SessionManager.create(sessionDir, cwd),
    // Disable Pi built-ins (read/bash/edit/write); keep AION bridge tools from extension.
    // Do NOT pass `tools: []` — that sets an empty allowlist and blocks every bridged tool.
    noTools: "builtin",
  });

  const bridgedTools = session.getAllTools?.() ?? [];
  console.log(
    `[pi-long-run] session=${payload.session_id.slice(0, 8)} bridged_tools=${bridgedTools.length}`,
  );
  if (bridgedTools.length === 0) {
    console.warn(
      `[pi-long-run] no bridged tools loaded (manifest=${manifestPath}); LLM may emit raw <tool_call> text`,
    );
  }

  const provider = payload.provider_id || "aion";
  const modelId = payload.model_id;
  if (modelId) {
    const model = session.modelRuntime.getModel(provider, modelId);
    if (!model) {
      throw new Error(`Pi model not found: ${provider}/${modelId}`);
    }
    try {
      await session.setModel(model);
      const thinkingLevel = payload.thinking_level;
      if (thinkingLevel && session.supportsThinking()) {
        session.setThinkingLevel(
          thinkingLevel as "off" | "low" | "medium" | "high",
        );
      }
    } catch (err) {
      console.error(
        `[pi-long-run] setModel failed provider=${provider} model=${modelId}:`,
        err,
      );
      throw err;
    }
  }

  sessions.set(payload.session_id, {
    session,
    dispose: () => session.dispose(),
  });
  return { created: true };
}

export function getPiSession(sessionId: string): AgentSession | undefined {
  return sessions.get(sessionId)?.session;
}

export async function abortPiSession(sessionId: string): Promise<void> {
  const managed = sessions.get(sessionId);
  if (!managed) return;
  try {
    await managed.session.abort();
  } catch {
    /* ignore */
  }
  managed.dispose();
  sessions.delete(sessionId);
}
