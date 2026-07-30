"use client";

import { Check, Copy } from "lucide-react";
import { useState } from "react";

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
    <div className={`rounded-xl border border-white/10 bg-black/30 p-3 space-y-2 ${className ?? ""}`}>
      <div className="flex items-center justify-between gap-2">
        <p className="text-[10px] font-bold uppercase tracking-wider text-gray-500">{title}</p>
        <button
          type="button"
          onClick={() => void copy()}
          className="flex items-center gap-1 text-[10px] font-bold text-indigo-300 hover:text-indigo-200"
        >
          {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
          {copied ? "Copiato" : "Copia"}
        </button>
      </div>
      <pre className="text-[11px] text-emerald-200/90 font-mono whitespace-pre-wrap break-all leading-relaxed bg-black/40 rounded-lg p-3 border border-white/5">
        {yaml}
      </pre>
      <p className="text-[10px] text-gray-500">
        Incolla nel blocco <span className="font-mono">env:</span> del registry o usa «Applica env suggerito».
      </p>
    </div>
  );
}
