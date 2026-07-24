import { describe, expect, it } from "vitest";
import { StreamSanitizer } from "../src/stream-sanitize.js";
import { createAionStreamMapper } from "../src/event-mapper.js";

describe("StreamSanitizer", () => {
  it("removes complete tool_code blocks", () => {
    const s = new StreamSanitizer();
    expect(s.filter("hello <tool_code>x</tool_code> world")).toBe("hello  world");
  });

  it("buffers partial tags across chunks", () => {
    const s = new StreamSanitizer();
    expect(s.filter("a <tool_co")).toBe("a ");
    expect(s.filter("de>junk")).toBe("junk");
  });

  it("strips lone tool_call tags", () => {
    const s = new StreamSanitizer();
    expect(s.filter('<tool_call>skill_view</tool_call>')).toBe("");
    expect(s.filter("<tool_code> <tool_code> </tool_code> </tool_code>")).toBe("");
  });
});

describe("createAionStreamMapper", () => {
  it("sanitizes token chunks from text_delta", () => {
    const mapper = createAionStreamMapper();
    const chunks = mapper.map({
      type: "message_update",
      assistantMessageEvent: {
        type: "text_delta",
        delta: "ok <tool_code></tool_code>",
      },
    } as never);
    expect(chunks).toEqual([{ type: "token", content: "ok " }]);
  });
});
