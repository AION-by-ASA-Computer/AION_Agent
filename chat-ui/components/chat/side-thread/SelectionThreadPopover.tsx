"use client";

import { useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { MessageSquareQuote } from "lucide-react";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";
import type { TextSelectionState } from "@/lib/side-thread/use-text-selection-anchor";

const GAP = 8;
const EDGE = 8;

type Props = {
  selection: TextSelectionState;
  onOpen: (selection: TextSelectionState) => void;
};

/**
 * Floating action above (desktop) or below (touch) a prose selection in an assistant
 * message. `pointerdown` is prevented so clicking it does not collapse the selection.
 */
export function SelectionThreadPopover({ selection, onOpen }: Props) {
  const t = useT();
  const ref = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const { width, height } = el.getBoundingClientRect();
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const { rect, touch } = selection;
    const centerX = (rect.left + rect.right) / 2;
    const left = Math.min(Math.max(EDGE, centerX - width / 2), vw - width - EDGE);
    const above = rect.top - GAP - height;
    const below = rect.bottom + (touch ? GAP * 2 : GAP);
    let top = touch ? below : above;
    if (!touch && above < EDGE) top = below;
    if (touch && below + height > vh - EDGE) top = Math.max(EDGE, above);
    setPos({ top, left });
  }, [selection]);

  return createPortal(
    <div
      ref={ref}
      role="toolbar"
      aria-label={t("sideThread.popover.toolbar")}
      className={cn(
        "fixed z-[60] flex flex-col items-stretch rounded-xl bg-popover p-1 text-popover-foreground",
        "shadow-[0_6px_20px_-6px_rgb(0_0_0/0.28)] dark:shadow-none dark:ring-1 dark:ring-white/12",
        pos && "side-thread-pop",
        !pos && "invisible",
      )}
      style={pos ? { top: pos.top, left: pos.left } : { top: 0, left: 0 }}
      onPointerDown={(e) => e.preventDefault()}
    >
      <button
        type="button"
        onClick={() => onOpen(selection)}
        className={cn(
          "focus-ring flex items-center gap-2 whitespace-nowrap rounded-lg px-2.5 py-1.5 text-[13px] font-medium",
          "text-foreground transition-colors hover:bg-primary/10 hover:text-primary",
        )}
      >
        <MessageSquareQuote className="size-4 shrink-0" aria-hidden />
        {t("sideThread.popover.action")}
      </button>
      {selection.truncated ? (
        <p className="max-w-[16rem] px-2.5 pb-1 text-[11px] leading-snug text-muted-foreground">
          {t("sideThread.popover.truncated", { max: 2000 })}
        </p>
      ) : null}
    </div>,
    document.body,
  );
}
