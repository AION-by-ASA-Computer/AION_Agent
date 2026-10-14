"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  anchorFromRange,
  closestAssistantMessage,
  isInsideProse,
  type SelectionAnchor,
} from "@/lib/side-thread/anchor";

export type TextSelectionState = SelectionAnchor & {
  /** Viewport rect of the selection (for popover placement). */
  rect: { top: number; bottom: number; left: number; right: number };
  /** Last selection came from a touch pointer: place the popover below the native menu. */
  touch: boolean;
};

/**
 * Tracks a text selection that sits entirely inside the prose of one assistant message
 * within `container`. Selections spanning messages, touching user bubbles or code blocks
 * resolve to null.
 */
export function useTextSelectionAnchor(container: HTMLElement | null, enabled: boolean) {
  const [selection, setSelection] = useState<TextSelectionState | null>(null);
  const touchRef = useRef(false);
  const timerRef = useRef<number | null>(null);

  const clear = useCallback(() => setSelection(null), []);

  const dismiss = useCallback(() => {
    setSelection(null);
    try {
      window.getSelection()?.removeAllRanges();
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    if (!container || !enabled) return;

    const evaluate = () => {
      const sel = window.getSelection();
      if (!sel || sel.isCollapsed || sel.rangeCount === 0) {
        setSelection(null);
        return;
      }
      const range = sel.getRangeAt(0);
      if (!container.contains(range.commonAncestorContainer)) {
        setSelection(null);
        return;
      }
      const startMsg = closestAssistantMessage(range.startContainer);
      const endMsg = closestAssistantMessage(range.endContainer);
      if (!startMsg || startMsg !== endMsg) {
        setSelection(null);
        return;
      }
      if (!isInsideProse(range.startContainer) || !isInsideProse(range.endContainer)) {
        setSelection(null);
        return;
      }
      const anchored = anchorFromRange(range, startMsg);
      if (!anchored) {
        setSelection(null);
        return;
      }
      const rects = Array.from(range.getClientRects()).filter((r) => r.width > 0 && r.height > 0);
      const box = range.getBoundingClientRect();
      // Selection scrolled out of the feed viewport: no popover pointing at nothing.
      const view = container.getBoundingClientRect();
      if (box.bottom < view.top || box.top > view.bottom) {
        setSelection(null);
        return;
      }
      const first = rects[0] ?? box;
      const last = rects[rects.length - 1] ?? box;
      setSelection({
        ...anchored,
        touch: touchRef.current,
        rect: {
          top: first.top,
          bottom: last.bottom,
          left: touchRef.current ? last.left : first.left,
          right: touchRef.current ? last.right : first.right,
        },
      });
    };

    const schedule = (delay: number) => {
      if (timerRef.current !== null) window.clearTimeout(timerRef.current);
      timerRef.current = window.setTimeout(evaluate, delay);
    };

    const onSelectionChange = () => {
      const sel = window.getSelection();
      // Hide promptly while the user is still dragging; show once the selection settles.
      if (!sel || sel.isCollapsed) setSelection(null);
      schedule(220);
    };
    const onPointerDown = (e: PointerEvent) => {
      touchRef.current = e.pointerType === "touch" || e.pointerType === "pen";
    };
    const onPointerUp = () => schedule(10);
    // Hide while scrolling, then re-anchor to the (still selected) passage once it settles.
    const onScroll = () => {
      setSelection(null);
      schedule(180);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setSelection(null);
      else if (e.shiftKey) schedule(220);
    };

    document.addEventListener("selectionchange", onSelectionChange);
    container.addEventListener("pointerdown", onPointerDown);
    container.addEventListener("pointerup", onPointerUp);
    container.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    document.addEventListener("keyup", onKey);
    return () => {
      if (timerRef.current !== null) window.clearTimeout(timerRef.current);
      document.removeEventListener("selectionchange", onSelectionChange);
      container.removeEventListener("pointerdown", onPointerDown);
      container.removeEventListener("pointerup", onPointerUp);
      container.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
      document.removeEventListener("keyup", onKey);
    };
  }, [container, enabled]);

  return { selection: container && enabled ? selection : null, clear, dismiss };
}
