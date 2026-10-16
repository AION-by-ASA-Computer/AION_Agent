"use client";

import { useCallback, useLayoutEffect, useRef, type RefObject } from "react";

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
      onMultiLineChange?.(nextIsMulti);
    }

    const baseMin = nextIsMulti ? minHeight : 24;
    const nextH = Math.min(maxHeight, Math.max(baseMin, scrollH));
    el.style.height = `${nextH}px`;
    el.style.overflowY = scrollH > maxHeight ? "auto" : "hidden";
  }, [ref, value, minHeight, maxHeight, onMultiLineChange]);

  useLayoutEffect(() => {
    sync();
  }, [value, sync]);

  return sync;
}



