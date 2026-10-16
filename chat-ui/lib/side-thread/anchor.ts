/**
 * Text anchoring for side threads (TextQuoteSelector-style).
 *
 * The quote and its surrounding context are measured over the *rendered* text of an
 * assistant message, so the same walker must be used to create an anchor and to find
 * it again. Code blocks and UI chrome (buttons, hidden nodes) are skipped on purpose:
 * they are not part of the prose a user can open a thread on.
 */
import type { SideThreadAnchor } from "@/lib/api/aion";

export const SIDE_THREAD_QUOTE_MAX = 2000;
const AFFIX_LEN = 32;

/** Elements whose text never participates in anchoring. */
const SKIP_SELECTOR = "pre, button, [aria-hidden='true'], [data-no-thread], .sr-only, script, style";

type TextIndex = {
  nodes: Text[];
  starts: number[];
  text: string;
};

/** Assistant message wrapper (`data-message-id` + `data-message-role="assistant"`). */
export function closestAssistantMessage(node: Node | null): HTMLElement | null {
  const el = node instanceof Element ? node : node?.parentElement ?? null;
  const msg = el?.closest<HTMLElement>("[data-message-id]") ?? null;
  if (!msg || msg.dataset.messageRole !== "assistant") return null;
  return msg;
}

export function isInsideProse(node: Node | null): boolean {
  const el = node instanceof Element ? node : node?.parentElement ?? null;
  if (!el) return false;
  if (el.closest(SKIP_SELECTOR)) return false;
  return Boolean(el.closest(".prose-chat"));
}

function indexText(root: HTMLElement): TextIndex {
  const nodes: Text[] = [];
  const starts: number[] = [];
  let text = "";
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode(n) {
      const parent = n.parentElement;
      if (!parent || !parent.closest(".prose-chat")) return NodeFilter.FILTER_REJECT;
      if (parent.closest(SKIP_SELECTOR)) return NodeFilter.FILTER_REJECT;
      return NodeFilter.FILTER_ACCEPT;
    },
  });
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const t = n as Text;
    nodes.push(t);
    starts.push(text.length);
    text += t.data;
  }
  return { nodes, starts, text };
}

/** Maps a DOM boundary point to an offset in the indexed text. */
function pointToOffset(idx: TextIndex, container: Node, offset: number): number {
  if (container.nodeType === Node.TEXT_NODE) {
    const i = idx.nodes.indexOf(container as Text);
    if (i >= 0) return idx.starts[i] + Math.min(offset, (container as Text).length);
  }
  const point = document.createRange();
  point.setStart(container, offset);
  point.collapse(true);
  for (let i = 0; i < idx.nodes.length; i += 1) {
    // First indexed node that sits at/after the point.
    if (point.comparePoint(idx.nodes[i], 0) >= 0) return idx.starts[i];
  }
  return idx.text.length;
}

function offsetToPoint(idx: TextIndex, offset: number, preferEnd: boolean): [Text, number] | null {
  if (!idx.nodes.length) return null;
  for (let i = 0; i < idx.nodes.length; i += 1) {
    const start = idx.starts[i];
    const end = start + idx.nodes[i].length;
    if (offset < end || (preferEnd && offset === end)) {
      return [idx.nodes[i], Math.max(0, offset - start)];
    }
  }
  const last = idx.nodes[idx.nodes.length - 1];
  return [last, last.length];
}

export type SelectionAnchor = {
  messageId: string;
  anchor: SideThreadAnchor;
  /** True when the selection was longer than {@link SIDE_THREAD_QUOTE_MAX}. */
  truncated: boolean;
};

/** Builds an anchor from a live selection range inside one assistant message. */
export function anchorFromRange(range: Range, messageEl: HTMLElement): SelectionAnchor | null {
  const messageId = messageEl.dataset.messageId;
  if (!messageId) return null;
  const idx = indexText(messageEl);
  let start = pointToOffset(idx, range.startContainer, range.startOffset);
  let end = pointToOffset(idx, range.endContainer, range.endOffset);
  if (end < start) [start, end] = [end, start];
  // Trim surrounding whitespace so double-click selections anchor cleanly.
  while (start < end && /\s/.test(idx.text[start])) start += 1;
  while (end > start && /\s/.test(idx.text[end - 1])) end -= 1;
  if (end <= start) return null;
  let truncated = false;
  if (end - start > SIDE_THREAD_QUOTE_MAX) {
    end = start + SIDE_THREAD_QUOTE_MAX;
    truncated = true;
  }
  return {
    messageId,
    truncated,
    anchor: {
      quote: idx.text.slice(start, end),
      prefix: idx.text.slice(Math.max(0, start - AFFIX_LEN), start),
      suffix: idx.text.slice(end, end + AFFIX_LEN),
    },
  };
}

function commonSuffixLen(a: string, b: string): number {
  let n = 0;
  while (n < a.length && n < b.length && a[a.length - 1 - n] === b[b.length - 1 - n]) n += 1;
  return n;
}

function commonPrefixLen(a: string, b: string): number {
  let n = 0;
  while (n < a.length && n < b.length && a[n] === b[n]) n += 1;
  return n;
}

/**
 * Finds the anchored passage again. Every occurrence of the quote is scored by how much
 * of the stored prefix/suffix it matches; the best one wins. Returns null when the quote
 * is no longer in the message (regenerated or edited).
 */
export function findAnchorRange(messageEl: HTMLElement, anchor: SideThreadAnchor): Range | null {
  const quote = anchor.quote || "";
  if (!quote) return null;
  const idx = indexText(messageEl);
  let best = -1;
  let bestScore = -1;
  for (let at = idx.text.indexOf(quote); at >= 0; at = idx.text.indexOf(quote, at + 1)) {
    const before = idx.text.slice(Math.max(0, at - AFFIX_LEN * 2), at);
    const after = idx.text.slice(at + quote.length, at + quote.length + AFFIX_LEN * 2);
    const score =
      commonSuffixLen(before, anchor.prefix || "") + commonPrefixLen(after, anchor.suffix || "");
    if (score > bestScore) {
      best = at;
      bestScore = score;
    }
  }
  if (best < 0) return null;
  const startPt = offsetToPoint(idx, best, false);
  const endPt = offsetToPoint(idx, best + quote.length, true);
  if (!startPt || !endPt) return null;
  const range = document.createRange();
  range.setStart(startPt[0], startPt[1]);
  range.setEnd(endPt[0], endPt[1]);
  return range;
}
