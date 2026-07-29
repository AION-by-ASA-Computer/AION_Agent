import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

export type LedgerExtensionConfig = {
  apiBaseUrl: string;
  invokeSecret: string;
  sessionId: string;
  enabled: boolean;
};

export function createAionLedgerExtension(config: LedgerExtensionConfig) {
  return (pi: ExtensionAPI) => {
    if (!config.enabled) {
      return;
    }
    const ledgerUrl = `${config.apiBaseUrl.replace(/\/$/, "")}/internal/pi/ledger?session_id=${encodeURIComponent(config.sessionId)}`;

    pi.on("context", async (event) => {
      try {
        const res = await fetch(ledgerUrl, {
          headers: config.invokeSecret
            ? { "X-Aion-Pi-Secret": config.invokeSecret }
            : {},
        });
        if (!res.ok) {
          return undefined;
        }
        const body = (await res.json()) as { table?: string };
        const table = (body.table || "").trim();
        if (!table) {
          return undefined;
        }
        const messages = [...event.messages];
        const injection = {
          role: "user" as const,
          content: [{ type: "text" as const, text: table }],
          timestamp: Date.now(),
        };
        messages.unshift(injection);
        return { messages };
      } catch {
        return undefined;
      }
    });
  };
}
