"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { X } from "lucide-react";
import { cn } from "@/lib/cn";

/** Modal on the native <dialog>: focus trap, Escape and inert background come from the browser. */
export function Dialog({
  title,
  closeLabel,
  onClose,
  children,
  className,
}: {
  title: string;
  closeLabel: string;
  onClose: () => void;
  children: ReactNode;
  className?: string;
}) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (el && !el.open) el.showModal();
  }, []);

  return (
    <dialog
      ref={ref}
      onClose={onClose}
      onClick={(e) => {
        if (e.target === ref.current) onClose();
      }}
      className={cn(
        "m-auto w-[calc(100%-2rem)] max-w-lg rounded-3xl border border-border bg-card p-0 text-foreground shadow-[0_24px_60px_-20px_rgba(0,0,0,0.45)] backdrop:bg-black/55",
        className,
      )}
    >
      <div className="flex items-start gap-4 px-6 pb-2 pt-6">
        <h2 className="flex-1 text-balance text-lg font-semibold tracking-[-0.015em]">{title}</h2>
        <button
          type="button"
          onClick={onClose}
          aria-label={closeLabel}
          className="focus-ring -mr-2 -mt-1 inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-xl text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
        >
          <X className="h-4 w-4" aria-hidden />
        </button>
      </div>
      <div className="px-6 pb-6">{children}</div>
    </dialog>
  );
}
