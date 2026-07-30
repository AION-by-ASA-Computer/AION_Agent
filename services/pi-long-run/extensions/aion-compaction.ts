import {
  convertToLlm,
  serializeConversation,
  type ExtensionAPI,
} from "@earendil-works/pi-coding-agent";

export type CompactionExtensionConfig = {
  apiBaseUrl: string;
  invokeSecret: string;
  sessionId: string;
  enabled: boolean;
};

export function createAionCompactionExtension(config: CompactionExtensionConfig) {
  return (pi: ExtensionAPI) => {
    if (!config.enabled) {
      return;
    }
    const summarizeUrl = `${config.apiBaseUrl.replace(/\/$/, "")}/internal/pi/compaction/summarize`;

    pi.on("session_before_compact", async (event, ctx) => {
      const { preparation, customInstructions, signal } = event;
      const messages = preparation.messagesToSummarize ?? [];
      if (!messages.length) {
        return undefined;
      }
      const transcript = serializeConversation(convertToLlm(messages));
      const fileOps = preparation.fileOps ?? {};
      const previousSummary = preparation.previousSummary ?? "";

      try {
        const res = await fetch(summarizeUrl, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            ...(config.invokeSecret
              ? { "X-Aion-Pi-Secret": config.invokeSecret }
              : {}),
          },
          body: JSON.stringify({
            session_id: config.sessionId,
            transcript,
            previous_summary: previousSummary,
            file_ops: fileOps,
            custom_instructions: customInstructions ?? "",
            previous_details: {},
          }),
          signal: ctx.signal,
        });
        if (!res.ok) {
          return undefined;
        }
        const body = (await res.json()) as {
          summary?: string;
          details?: Record<string, unknown>;
        };
        if (!body.summary) {
          return undefined;
        }
        return {
          compaction: {
            summary: body.summary,
            firstKeptEntryId: preparation.firstKeptEntryId,
            tokensBefore: preparation.tokensBefore,
            details: body.details ?? {},
          },
        };
      } catch {
        return undefined;
      }
    });
  };
}
