export type ChatEvent = Record<string, unknown>;

export class AionClient {
  constructor(
    readonly baseUrl: string,
    readonly apiKey: string
  ) {}

  private headers(): HeadersInit {
    return { "X-Api-Key": this.apiKey };
  }

  async createConversation(profile: string, userId: string, body: Record<string, unknown> = {}) {
    const r = await fetch(`${this.baseUrl}/v1/conversations`, {
      method: "POST",
      headers: { ...this.headers(), "Content-Type": "application/json" },
      body: JSON.stringify({ profile, user_id: userId, ...body }),
    });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return r.json();
  }

  async *chatStream(conversationId: string, message: string, profile = "aion_std"): AsyncGenerator<ChatEvent> {
    const r = await fetch(`${this.baseUrl}/v1/chat/stream`, {
      method: "POST",
      headers: { ...this.headers(), "Content-Type": "application/json" },
      body: JSON.stringify({ conversation_id: conversationId, message, profile }),
    });
    if (!r.ok || !r.body) throw new Error(`HTTP ${r.status}`);
    const reader = r.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      const parts = buf.split("\n\n");
      buf = parts.pop() ?? "";
      for (const block of parts) {
        for (const line of block.split("\n")) {
          if (line.startsWith("data:")) {
            yield JSON.parse(line.slice(5).trim()) as ChatEvent;
          }
        }
      }
    }
  }
}
