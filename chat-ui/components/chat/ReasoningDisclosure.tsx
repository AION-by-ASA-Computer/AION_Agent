"use client";

import { useState } from "react";
import { ChevronRight, Brain } from "lucide-react";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";

type Props = {
  content: string;
  streaming?: boolean;
};

export function ReasoningDisclosure({ content, streaming = false }: Props) {
  const t = useT();
  const [open, setOpen] = useState(streaming);
  const text = content.trim();
  if (!text && !streaming) return null;

  return (
    <div className="my-2 select-text">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="focus-ring group inline-flex items-center gap-2 rounded-xl border border-purple-500/25 bg-purple-500/[0.05] dark:bg-purple-500/[0.08] px-3 py-1.5 text-left text-xs font-medium text-purple-700 dark:text-purple-300 transition-all hover:bg-purple-500/10 hover:border-purple-500/40 cursor-pointer"
        aria-expanded={open}
      >
        <Brain size={14} className="shrink-0 text-purple-600 dark:text-purple-400" aria-hidden />
        <span>{t("chat.reasoning.label")}</span>
        <ChevronRight
          size={13}
          className={cn("shrink-0 opacity-70 transition-transform duration-200", open && "rotate-90")}
          aria-hidden
        />
      </button>
      <div
        className={cn(
          "grid transition-[grid-template-rows,opacity] duration-200 ease-out",
          open ? "grid-rows-[1fr] opacity-100" : "grid-rows-[0fr] opacity-0",
        )}
      >
        <div className="min-h-0 overflow-hidden">
          {text ? (
            <div className="mt-2 rounded-xl border-l-2 border-purple-500/40 bg-purple-500/[0.03] dark:bg-purple-500/[0.05] pl-3.5 pr-3 py-2.5">
              <div className="whitespace-pre-wrap font-sans text-[13px] italic leading-relaxed text-muted-foreground/85">
                {text}
              </div>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
