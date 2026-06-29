"use client";

import { useEffect, useRef } from "react";
import { Loader2 } from "lucide-react";
import { useT } from "@/lib/i18n/use-t";

type Props = {
  title: string;
  content: string;
  streaming?: boolean;
  kind?: "plan" | "artifact";
};

export function StreamingContentPreview({
  title,
  content,
  streaming = false,
  kind = "artifact",
}: Props) {
  const t = useT();
  const scrollRef = useRef<HTMLPreElement>(null);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el || !streaming) return;
    el.scrollTop = el.scrollHeight;
  }, [content, streaming]);

  const header =
    kind === "plan"
      ? t("chat.generating.plan")
      : title.trim()
        ? t("chat.generating.document_named", { title })
        : t("chat.generating.document");

  return (
    <div className="flex h-full min-h-0 flex-col border-b border-border bg-card/40">
      <div className="flex shrink-0 items-center gap-2 border-b border-border/60 px-3 py-2 text-xs text-muted-foreground">
        {streaming ? <Loader2 className="size-3.5 animate-spin text-primary" aria-hidden /> : null}
        <span className="font-medium text-foreground">{header}</span>
      </div>
      <pre
        ref={scrollRef}
        className="min-h-0 flex-1 overflow-auto whitespace-pre-wrap break-words p-3 font-mono text-[11px] leading-relaxed text-foreground/90"
      >
        {content.trim() || t("artifacts.live_preview_empty")}
      </pre>
    </div>
  );
}
