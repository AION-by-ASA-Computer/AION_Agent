"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState, type RefObject } from "react";

type Options = {
  minHeight?: number;
  maxHeight?: number;
  onMultiLineChange?: (isMulti: boolean) => void;
};

/**
 * Auto-resizing textarea with hysteresis-protected multiline state detection.
 * Prevents layout-measuring oscillations and ensures smooth bidirectional scaling.
 */
export function useAutoResizeTextarea(
  ref: RefObject<HTMLTextAreaElement | null>,
  value: string,
  { minHeight = 28, maxHeight = 220, onMultiLineChange }: Options = {}
) {
  const isMultiRef = useRef(false);
  // Mirrors isMultiRef as state so a mode flip re-runs the layout effect: the
  // parent swaps classes (e.g. drops whitespace-nowrap, widens the textarea),
  // and the height measured under the old layout is stale.
  const [isMulti, setIsMulti] = useState(false);

  const sync = useCallback(() => {
    const el = ref.current;
    if (!el) return;

    const trimmed = value.trim();
    const hasNewline = value.includes("\n");

    // Reset height to measure actual content scrollHeight
    el.style.height = "auto";
    const scrollH = el.scrollHeight;
    const scrollW = el.scrollWidth;
    const clientW = el.clientWidth;

    let nextIsMulti: boolean;

    if (!trimmed) {
      nextIsMulti = false;
    } else if (hasNewline) {
      nextIsMulti = true;
    } else if (!isMultiRef.current) {
      // In single-line mode: expand if text overflows horizontally or vertically or exceeds character threshold
      const isOverflowing = scrollH > 34 || scrollW > clientW + 4 || value.length > 40;
      nextIsMulti = isOverflowing;
    } else {
      // In multi-line mode: only collapse back if text is short enough to safely fit in single-line mode
      const isShortEnough = value.length <= 30 && scrollH <= 34;
      nextIsMulti = !isShortEnough;
    }

    if (nextIsMulti !== isMultiRef.current) {
      isMultiRef.current = nextIsMulti;
      setIsMulti(nextIsMulti);
      onMultiLineChange?.(nextIsMulti);
    }

    const baseMin = nextIsMulti ? minHeight : 24;
    const nextH = Math.min(maxHeight, Math.max(baseMin, scrollH));
    el.style.height = `${nextH}px`;
    // Inline cap so a user-enlarged maxHeight isn't clipped by a CSS max-h class;
    // single-line mode keeps the caller's class-based cap.
    el.style.maxHeight = nextIsMulti ? `${maxHeight}px` : "";
    el.style.overflowY = scrollH > maxHeight ? "auto" : "hidden";
  }, [ref, value, minHeight, maxHeight, onMultiLineChange]);

  useLayoutEffect(() => {
    sync();
  }, [value, sync, isMulti]);

  // Re-measure when the textarea width changes (window resize, sidebar toggle):
  // line wrapping, and therefore scrollHeight, depends on it.
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    let lastWidth = el.clientWidth;
    const ro = new ResizeObserver(() => {
      const w = el.clientWidth;
      if (w === lastWidth) return;
      lastWidth = w;
      sync();
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [ref, sync]);

  return sync;
}
