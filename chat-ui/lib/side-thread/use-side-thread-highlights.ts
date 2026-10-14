"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { SideThreadSummary } from "@/lib/api/aion";
import { findAnchorRange } from "@/lib/side-thread/anchor";

const HL_BASE = "side-thread";
const HL_ACTIVE = "side-thread-active";
const HL_FLASH = "side-thread-flash";
const HL_HOVER = "side-thread-hover";

type HighlightCtor = new (...ranges: Range[]) => { add(r: Range): void };
type HighlightRegistryLike = {
  set(name: string, h: unknown): void;
  delete(name: string): boolean;
};

// Kept out of globals.css: Turbopack's Lightning CSS does not parse ::highlight() and
// drops the rest of the stylesheet. The browser parses it fine at runtime.
// Base reads as a marker pass (wash + solid underline) so anchored passages are visible
// at a glance; hover and active step up; flash is the reveal pulse. Dark mode needs a
// denser wash because the brand red loses luminance contrast on dark surfaces.
const HIGHLIGHT_CSS = `
::highlight(${HL_BASE}) {
  background-color: hsl(var(--primary) / 0.11);
  text-decoration-line: underline;
  text-decoration-style: solid;
  text-decoration-thickness: 2px;
  text-decoration-color: hsl(var(--primary) / 0.6);
}
::highlight(${HL_HOVER}) {
  background-color: hsl(var(--primary) / 0.1);
  text-decoration-line: underline;
  text-decoration-style: solid;
  text-decoration-thickness: 2px;
  text-decoration-color: hsl(var(--primary));
}
::highlight(${HL_ACTIVE}) {
  background-color: hsl(var(--primary) / 0.2);
  text-decoration-line: underline;
  text-decoration-style: solid;
  text-decoration-thickness: 2px;
  text-decoration-color: hsl(var(--primary));
}
::highlight(${HL_FLASH}) {
  background-color: hsl(var(--primary) / 0.32);
}
html[data-theme="dark"] ::highlight(${HL_BASE}) {
  background-color: hsl(var(--primary) / 0.17);
  text-decoration-color: hsl(var(--primary) / 0.8);
}
html[data-theme="dark"] ::highlight(${HL_ACTIVE}) {
  background-color: hsl(var(--primary) / 0.28);
}
html[data-theme="dark"] ::highlight(${HL_FLASH}) {
  background-color: hsl(var(--primary) / 0.4);
}`;

function ensureHighlightStyles() {
  const id = "side-thread-highlight-styles";
  let el = document.getElementById(id);
  if (!el) {
    el = document.createElement("style");
    el.id = id;
    document.head.appendChild(el);
  }
  if (el.textContent !== HIGHLIGHT_CSS) el.textContent = HIGHLIGHT_CSS;
}

function registry(): { reg: HighlightRegistryLike; Ctor: HighlightCtor } | null {
  if (typeof window === "undefined") return null;
  const reg = (CSS as unknown as { highlights?: HighlightRegistryLike }).highlights;
  const Ctor = (window as unknown as { Highlight?: HighlightCtor }).Highlight;
  if (!reg || !Ctor) return null;
  ensureHighlightStyles();
  return { reg, Ctor };
}

function caretAt(x: number, y: number): { node: Node; offset: number } | null {
  const doc = document as Document & {
    caretPositionFromPoint?: (x: number, y: number) => { offsetNode: Node; offset: number } | null;
    caretRangeFromPoint?: (x: number, y: number) => Range | null;
  };
  if (doc.caretPositionFromPoint) {
    const p = doc.caretPositionFromPoint(x, y);
    return p ? { node: p.offsetNode, offset: p.offset } : null;
  }
  if (doc.caretRangeFromPoint) {
    const r = doc.caretRangeFromPoint(x, y);
    return r ? { node: r.startContainer, offset: r.startOffset } : null;
  }
  return null;
}

/** True when the caret point lies on the rendered glyphs of the range (not past a line end). */
function hitRange(range: Range, x: number, y: number, caret: { node: Node; offset: number }): boolean {
  try {
    if (!range.isPointInRange(caret.node, caret.offset)) return false;
  } catch {
    return false;
  }
  for (const r of Array.from(range.getClientRects())) {
    if (x >= r.left - 1 && x <= r.right + 1 && y >= r.top - 1 && y <= r.bottom + 1) return true;
  }
  return false;
}

/**
 * Paints side-thread anchors in the parent feed with the CSS Custom Highlight API
 * (no DOM mutation of the rendered markdown) and turns clicks on them into `onOpen`.
 *
 * Ranges are recomputed whenever the feed DOM changes, so markdown re-renders and
 * history reloads keep the underline in place. Threads whose quote cannot be found
 * are reported through `missing` so the UI can fall back to the message chip.
 */
export function useSideThreadHighlights(opts: {
  container: HTMLElement | null;
  threads: SideThreadSummary[];
  activeThreadId: string | null;
  onOpen: (threadId: string) => void;
}) {
  const { container, threads, activeThreadId, onOpen } = opts;
  const rangesRef = useRef<Map<string, Range>>(new Map());
  const [missing, setMissing] = useState<Set<string>>(() => new Set());
  const onOpenRef = useRef(onOpen);
  useEffect(() => {
    onOpenRef.current = onOpen;
  }, [onOpen]);

  const paint = useCallback(() => {
    const api = registry();
    const next = new Map<string, Range>();
    const lost = new Set<string>();
    if (container) {
      for (const th of threads) {
        const msg = container.querySelector<HTMLElement>(
          `[data-message-id="${CSS.escape(th.parent_message_id)}"]`,
        );
        if (!msg) {
          lost.add(th.id);
          continue;
        }
        const range = findAnchorRange(msg, th.anchor);
        if (range) next.set(th.id, range);
        else lost.add(th.id);
      }
    }
    rangesRef.current = next;
    setMissing((prev) => {
      if (prev.size === lost.size && [...lost].every((id) => prev.has(id))) return prev;
      return lost;
    });
    if (!api) return;
    const base = new api.Ctor();
    const active = new api.Ctor();
    for (const [id, r] of next) {
      if (id === activeThreadId) active.add(r);
      else base.add(r);
    }
    api.reg.set(HL_BASE, base);
    api.reg.set(HL_ACTIVE, active);
  }, [container, threads, activeThreadId]);

  // Repaint on data changes and on any DOM mutation of the feed (debounced).
  useEffect(() => {
    // Paint after layout: markdown may still be committing when data changes.
    let raf = requestAnimationFrame(paint);
    if (!container) return () => cancelAnimationFrame(raf);
    let timer: number | null = null;
    const obs = new MutationObserver(() => {
      if (timer !== null) window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        cancelAnimationFrame(raf);
        raf = requestAnimationFrame(paint);
      }, 120);
    });
    obs.observe(container, { childList: true, subtree: true, characterData: true });
    return () => {
      obs.disconnect();
      if (timer !== null) window.clearTimeout(timer);
      cancelAnimationFrame(raf);
    };
  }, [container, paint]);

  useEffect(
    () => () => {
      const api = registry();
      api?.reg.delete(HL_BASE);
      api?.reg.delete(HL_ACTIVE);
      api?.reg.delete(HL_FLASH);
      api?.reg.delete(HL_HOVER);
    },
    [],
  );

  // Click to open + pointer cursor on hover.
  useEffect(() => {
    if (!container) return;
    const hitTest = (e: MouseEvent): string | null => {
      if (!rangesRef.current.size) return null;
      const caret = caretAt(e.clientX, e.clientY);
      if (!caret) return null;
      for (const [id, r] of rangesRef.current) {
        if (hitRange(r, e.clientX, e.clientY, caret)) return id;
      }
      return null;
    };
    const onClick = (e: MouseEvent) => {
      if (e.defaultPrevented || e.button !== 0) return;
      const sel = window.getSelection();
      if (sel && !sel.isCollapsed) return;
      const target = e.target as Element | null;
      if (target?.closest("a, button, input, textarea, [role='button']")) return;
      const id = hitTest(e);
      if (id) onOpenRef.current(id);
    };
    let raf = 0;
    let lastEvent: MouseEvent | null = null;
    let hovered: string | null = null;
    const setHover = (id: string | null) => {
      if (id === hovered) return;
      hovered = id;
      const api = registry();
      const range = id ? rangesRef.current.get(id) : undefined;
      if (range) {
        container.dataset.threadHover = "1";
        api?.reg.set(HL_HOVER, new api.Ctor(range));
      } else {
        delete container.dataset.threadHover;
        api?.reg.delete(HL_HOVER);
      }
    };
    const onMove = (e: MouseEvent) => {
      lastEvent = e;
      if (raf) return;
      raf = requestAnimationFrame(() => {
        raf = 0;
        if (!lastEvent) return;
        setHover(hitTest(lastEvent));
      });
    };
    const onLeave = () => {
      lastEvent = null;
      setHover(null);
    };
    container.addEventListener("click", onClick);
    container.addEventListener("mousemove", onMove);
    container.addEventListener("mouseleave", onLeave);
    return () => {
      container.removeEventListener("click", onClick);
      container.removeEventListener("mousemove", onMove);
      container.removeEventListener("mouseleave", onLeave);
      cancelAnimationFrame(raf);
      setHover(null);
    };
  }, [container]);

  /** Scrolls the parent feed to the passage and flashes it. Returns false if not found. */
  const revealThread = useCallback((threadId: string): boolean => {
    const range = rangesRef.current.get(threadId);
    if (!range) return false;
    const el = range.startContainer.parentElement;
    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    el?.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "center" });
    const api = registry();
    if (api) {
      api.reg.set(HL_FLASH, new api.Ctor(range));
      window.setTimeout(() => api.reg.delete(HL_FLASH), 1400);
    }
    return true;
  }, []);

  return { missing, revealThread };
}
