"use client";

import { useEffect, useRef, useState } from "react";
import {
  ChevronDown,
  Wrench,
} from "lucide-react";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";
import type { SkillStatus } from "@/components/chat/ChatWorkspace";

export type UsedTool = {
  name: string;
  callCount: number;
  hasError: boolean;
};



export function CapabilitiesChip({
  usedTools,
  skillStatuses,
}: {
  usedTools: UsedTool[];
  skillStatuses: SkillStatus[];
}) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  const totalTools = usedTools.length;
  const hasAny = totalTools > 0 || skillStatuses.length > 0;



  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("mousedown", onDoc);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("mousedown", onDoc);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (!hasAny) return null;

  const hasToolErrors = usedTools.some((t) => t.hasError);
  const hasSkillErrors = skillStatuses.some((s) => s.loadState === "failed");
  const hasErrors = hasToolErrors || hasSkillErrors;

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        id="capabilities-chip-trigger"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-haspopup="true"
        className={cn(
          "focus-ring inline-flex h-8 items-center gap-1.5 rounded-full border px-3 text-[0.786em] font-semibold transition-all duration-200 hover:scale-[1.01] active:scale-[0.99]",
          open
            ? "border-primary/40 bg-primary/10 text-primary"
            : hasErrors
              ? "border-rose-500/40 bg-rose-500/10 text-rose-500 hover:bg-rose-500/15"
              : "border-border/80 bg-muted/20 text-muted-foreground hover:bg-muted/40 hover:text-foreground",
        )}
        title={t("chat.capabilities.label")}
      >
        <Wrench size={12} className="shrink-0" aria-hidden />
        {totalTools > 0 && (
          <span className="tabular-nums">{totalTools}</span>
        )}
        <ChevronDown
          size={10}
          className={cn(
            "shrink-0 opacity-70 transition-transform duration-150",
            open && "rotate-180",
          )}
          aria-hidden
        />
      </button>

    </div>
  );
}
