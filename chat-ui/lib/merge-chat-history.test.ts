import { describe, expect, it } from "vitest";
import {
  mergeChatHistory,
  preferRicherMessage,
  type MergeableChatMessage,
} from "./merge-chat-history";

const msg = (
  id: string,
  content: string,
  extra?: Partial<MergeableChatMessage>,
): MergeableChatMessage => ({
  id,
  content,
  ...extra,
});

describe("mergeChatHistory", () => {
  it("replace mode returns server only", () => {
    const local = [msg("local-1", "stale from other conv")];
    const server = [msg("s-1", "server"), msg("s-2", "only")];
    expect(mergeChatHistory(local, server, "conv-a")).toEqual(server);
  });

  it("merge does not append foreign local ids when conversation changed", () => {
    const local = [msg("foreign-1", "from conv A")];
    const server = [msg("b-1", "conv B")];
    const merged = mergeChatHistory(local, server, "conv-b");
    expect(merged).toHaveLength(1);
    expect(merged[0].id).toBe("b-1");
  });

  it("preferRicherMessage does not prefer empty local over server", () => {
    const local = msg("x", "", { steps: [{ name: "t" }] });
    const server = msg("x", "full answer from server");
    const picked = preferRicherMessage(local, server);
    expect(picked.content).toBe("full answer from server");
  });
});
