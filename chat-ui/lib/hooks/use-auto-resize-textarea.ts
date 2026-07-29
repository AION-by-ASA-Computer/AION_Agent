"use client";

import { useCallback, useLayoutEffect, type RefObject } from "react";

type Options = {
  minHeight?: number;
  maxHeight?: number;
};

/** Grow textarea with content (ChatGPT/Claude style) up to maxHeight, then scroll. */
export function useAutoResizeTextarea(
  ref: RefObject<HTMLTextAreaElement | null>,
  value: string,
  { minHeight = 48, maxHeight = 200 }: Options = {}
) {
  const sync = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "0px";
    const scroll = el.scrollHeight;
    const next = Math.min(maxHeight, Math.max(minHeight, scroll));
    el.style.height = `${next}px`;
    el.style.overflowY = scroll > maxHeight ? "auto" : "hidden";
  }, [ref, minHeight, maxHeight]);

  useLayoutEffect(() => {
    sync();
  }, [value, sync, maxHeight]);

  return sync;
}
