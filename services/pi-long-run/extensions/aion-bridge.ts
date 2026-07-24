import { readFileSync } from "node:fs";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

type ManifestTool = {
  name: string;
  description: string;
  parameters: Record<string, unknown>;
};

type BridgeConfig = {
  invokeUrl: string;
  invokeSecret: string;
  sessionId: string;
  profile: string;
  userId: string;
};

function loadManifest(path: string): ManifestTool[] {
  try {
    const raw = readFileSync(path, "utf8");
    const parsed = JSON.parse(raw) as ManifestTool[];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export function createAionBridgeExtension(config: BridgeConfig, manifestPath: string) {
  return (pi: ExtensionAPI) => {
    const tools = loadManifest(manifestPath);
    for (const tool of tools) {
      const schema =
        tool.parameters && typeof tool.parameters === "object"
          ? (tool.parameters as Parameters<typeof Type.Unsafe>[0])
          : { type: "object", properties: {} };

      pi.registerTool({
        name: tool.name,
        label: tool.name,
        description: tool.description || tool.name,
        parameters: Type.Unsafe(schema),
        async execute(_toolCallId, params) {
          const res = await fetch(config.invokeUrl, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              ...(config.invokeSecret
                ? { "X-Aion-Pi-Secret": config.invokeSecret }
                : {}),
            },
            body: JSON.stringify({
              session_id: config.sessionId,
              profile: config.profile,
              user_id: config.userId,
              tool_name: tool.name,
              arguments: params ?? {},
            }),
          });
          if (!res.ok) {
            const text = await res.text();
            throw new Error(`AION tool bridge HTTP ${res.status}: ${text}`);
          }
          const body = (await res.json()) as {
            content?: string;
            is_error?: boolean;
          };
          if (body.is_error) {
            return {
              content: [{ type: "text", text: body.content || "Tool error" }],
              isError: true,
            };
          }
          return {
            content: [{ type: "text", text: body.content || "" }],
            isError: false,
          };
        },
      });
    }
  };
}
