import { describe, expect, it } from "vitest";

import { coalesceTurnSegments } from "./coalesceTurnSegments";
import type { TurnSegment } from "./types";

describe("coalesceTurnSegments", () => {
  it("merges word split across short reasoning", () => {
    const segments: TurnSegment[] = [
      { kind: "text", id: "t0", content: "C" },
      { kind: "reasoning", id: "r0", content: "." },
      { kind: "text", id: "t1", content: "iao! Ottima idea." },
    ];
    const out = coalesceTurnSegments(segments);
    expect(out).toHaveLength(1);
    expect(out[0]).toMatchObject({ kind: "text", content: "Ciao! Ottima idea." });
  });

  it("merges consecutive text segments", () => {
    const segments: TurnSegment[] = [
      { kind: "text", id: "t0", content: "Hello " },
      { kind: "text", id: "t1", content: "world" },
    ];
    const out = coalesceTurnSegments(segments);
    expect(out).toHaveLength(1);
    expect(out[0]).toMatchObject({ kind: "text", content: "Hello world" });
  });

  it("leaves reasoning blocks intact when merge not needed", () => {
    const segments: TurnSegment[] = [
      { kind: "text", id: "t0", content: "Done." },
      { kind: "reasoning", id: "r0", content: "Long reasoning block here." },
      { kind: "text", id: "t1", content: "Next paragraph." },
    ];
    const out = coalesceTurnSegments(segments);
    expect(out).toHaveLength(3);
  });
});
