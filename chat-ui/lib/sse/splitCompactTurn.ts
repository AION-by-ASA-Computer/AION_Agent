import type { TurnSegment } from "./types";

/**
 * Compact-mode mapping: the process trail is whatever already happened
 * in the turn timeline (reasoning, tools, and any text/artifacts that
 * still sit before later tool work). No filename or intent classifiers.
 * Trailing answer content stays visible; mirrored process code fences are
 * removed from it only when other answer text remains.
 */

type FenceBlock = { kind: "fence"; lang: string; code: string };
type TextBlock = { kind: "text"; content: string };
export type MarkdownBlock = FenceBlock | TextBlock;

function hasLaterToolWork(segments: TurnSegment[], index: number): boolean {
  for (let i = index + 1; i < segments.length; i += 1) {
    const kind = segments[i].kind;
    if (kind === "tool" || kind === "generating") return true;
  }
  return false;
}

export function isProcessWorkSegment(seg: TurnSegment): boolean {
  return (
    seg.kind === "reasoning" ||
    seg.kind === "tool" ||
    seg.kind === "status" ||
    seg.kind === "generating"
  );
}

export function partitionCompactSegments(segments: TurnSegment[]): {
  process: TurnSegment[];
  output: TurnSegment[];
} {
  const process: TurnSegment[] = [];
  const output: TurnSegment[] = [];

  for (let i = 0; i < segments.length; i += 1) {
    const seg = segments[i];
    if (isProcessWorkSegment(seg)) {
      process.push(seg);
      continue;
    }
    if (seg.kind === "text" || seg.kind === "artifact") {
      if (hasLaterToolWork(segments, i)) {
        process.push(seg);
      } else {
        output.push(seg);
      }
      continue;
    }
    output.push(seg);
  }

  return { process, output };
}

export function splitMarkdownFences(src: string): MarkdownBlock[] {
  const lines = src.replace(/\r\n/g, "\n").split("\n");
  const blocks: MarkdownBlock[] = [];
  const textBuf: string[] = [];
  let i = 0;

  const flushText = () => {
    if (!textBuf.length) return;
    blocks.push({ kind: "text", content: textBuf.join("\n") });
    textBuf.length = 0;
  };

  while (i < lines.length) {
    const line = lines[i];
    const open = /^( {0,3})(`{3,}|~{3,})(.*)$/.exec(line);
    if (!open) {
      textBuf.push(line);
      i += 1;
      continue;
    }

    const marker = open[2];
    const markerChar = marker[0];
    const markerLen = marker.length;
    const lang = open[3].trim().split(/\s+/)[0] || "";
    const body: string[] = [];
    i += 1;
    let closed = false;
    while (i < lines.length) {
      const close = /^( {0,3})(`{3,}|~{3,})\s*$/.exec(lines[i]);
      if (close && close[2][0] === markerChar && close[2].length >= markerLen) {
        closed = true;
        i += 1;
        break;
      }
      body.push(lines[i]);
      i += 1;
    }

    if (!closed) {
      textBuf.push(line, ...body);
      break;
    }

    flushText();
    blocks.push({ kind: "fence", lang, code: body.join("\n") });
  }

  flushText();
  return blocks;
}

export function normalizeCodeBody(s: string): string {
  return s.replace(/\r\n/g, "\n").replace(/[ \t]+$/gm, "").trim();
}

function codeBodiesMatch(a: string, b: string): boolean {
  const na = normalizeCodeBody(a);
  const nb = normalizeCodeBody(b);
  if (!na || !nb) return false;
  if (na === nb) return true;
  if (Math.min(na.length, nb.length) < 80) return false;
  return na.includes(nb) || nb.includes(na);
}

function collectStringLeaves(value: unknown, out: string[]): void {
  if (typeof value === "string") {
    if (value.includes("\n") && value.trim().length >= 40) out.push(value);
    return;
  }
  if (Array.isArray(value)) {
    for (const item of value) collectStringLeaves(item, out);
    return;
  }
  if (value && typeof value === "object") {
    for (const nested of Object.values(value as Record<string, unknown>)) {
      collectStringLeaves(nested, out);
    }
  }
}

export function collectProcessCodeBodies(segments: TurnSegment[]): string[] {
  const bodies: string[] = [];
  for (const seg of segments) {
    if (seg.kind === "reasoning" || seg.kind === "text") {
      for (const block of splitMarkdownFences(seg.content || "")) {
        if (block.kind === "fence" && block.code.trim()) bodies.push(block.code);
      }
    } else if (seg.kind === "artifact" && seg.buffer.trim()) {
      bodies.push(seg.buffer);
    } else if (seg.kind === "tool") {
      collectStringLeaves(seg.input, bodies);
    }
  }
  return bodies;
}

export function stripMirroredProcessCode(text: string, process: TurnSegment[]): string {
  const bodies = collectProcessCodeBodies(process);
  if (!bodies.length) return text;

  const blocks = splitMarkdownFences(text);
  const kept: MarkdownBlock[] = [];
  let dropped = 0;
  for (const block of blocks) {
    if (block.kind === "fence" && bodies.some((body) => codeBodiesMatch(body, block.code))) {
      dropped += 1;
      continue;
    }
    kept.push(block);
  }
  if (!dropped) return text;

  const rebuilt = kept
    .map((block) =>
      block.kind === "text" ? block.content : `\`\`\`${block.lang}\n${block.code}\n\`\`\``,
    )
    .join("\n")
    .trim();

  // If the whole answer was the same code already in the process trail, keep it:
  // that is the user-facing deliverable (e.g. "write me a script").
  if (!rebuilt) return text;
  return rebuilt;
}

export function splitCompactTurn(
  segments: TurnSegment[],
  opts: { streaming?: boolean } = {},
): { process: TurnSegment[]; output: TurnSegment[] } {
  const { process, output } = partitionCompactSegments(segments);
  const mapped = output
    .map((seg, idx) => {
      if (seg.kind !== "text") return seg;
      const isLiveTail = Boolean(opts.streaming) && idx === output.length - 1;
      if (isLiveTail) return seg;
      return { ...seg, content: stripMirroredProcessCode(seg.content, process) };
    })
    .filter((seg) => seg.kind !== "text" || Boolean(seg.content.trim()));

  return { process, output: mapped };
}
