"use client";

import { Check, Copy } from "lucide-react";
import { useState } from "react";
import { cn } from "@/lib/cn";

type Props = {
  yaml: string;
  title?: string;
  className?: string;
};

export function McpEnvYamlPanel({ yaml, title = "Snippet env per registry (YAML)", className }: Props) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(yaml);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      /* ignore */
    }
  }

  if (!yaml || yaml === "env: {}") {
    return null;
  }

  return (
    <div className={cn("space-y-2 rounded-2xl border border-border/70 bg-muted/20 p-3", className)}>
      <div className="flex items-center justify-between gap-2">
        <p className="aion-section-label">{title}</p>
        <button
          type="button"
          onClick={() => void copy()}
          className="focus-ring inline-flex items-center gap-1 rounded-lg px-2 py-1 text-[0.714em] font-semibold text-foreground transition hover:bg-muted"
        >
          {copied ? <Check className="h-3.5 w-3.5" aria-hidden /> : <Copy className="h-3.5 w-3.5" aria-hidden />}
          {copied ? "Copiato" : "Copia"}
        </button>
      </div>
      <pre className="overflow-x-auto whitespace-pre-wrap break-all rounded-xl border border-border/60 bg-background/60 p-3 font-mono text-[0.786em] leading-relaxed text-foreground">
        {yaml}
      </pre>
      <p className="text-[0.714em] text-muted-foreground">
        Incolla nel blocco <span className="font-mono">env:</span> del registry o usa «Applica env suggerito».
      </p>
    </div>
  );
}
