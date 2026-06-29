"use client";

import { useState } from "react";
import { ChevronRight, Brain } from "lucide-react";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";
import { ShimmerText } from "@/components/chat/ShimmerText";

type Props = {
  content: string;
  streaming?: boolean;
};

export function ReasoningDisclosure({ content, streaming = false }: Props) {
  const t = useT();
  const [open, setOpen] = useState(true);
  const text = content.trim();
  if (!text && !streaming) return null;

  return (
    <div className="mb-2">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="focus-ring flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-muted-foreground transition-colors hover:bg-muted/40 hover:text-foreground"
        aria-expanded={open}
      >
        <Brain size={14} className="shrink-0 opacity-80" aria-hidden />
        {streaming && !text ? (
          <ShimmerText className="text-xs font-medium">{t("chat.reasoning.streaming")}</ShimmerText>
        ) : (
          <span className="text-xs font-medium">{t("chat.reasoning.label")}</span>
        )}
        <ChevronRight
          size={13}
          className={cn("ml-auto shrink-0 opacity-70 transition-transform duration-200", open && "rotate-90")}
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
            <div className="mt-1.5 rounded-lg bg-muted/35 px-3 py-2.5">
              <div className="whitespace-pre-wrap font-sans text-[13px] leading-relaxed text-muted-foreground">
                {text}
              </div>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
