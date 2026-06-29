"use client";

import { useState } from "react";
import { Copy, Check } from "lucide-react";

export function CopyButton({ text, label = "Copia" }: { text: string; label?: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      type="button"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setDone(true);
          setTimeout(() => setDone(false), 2000);
        } catch {
          /* ignore */
        }
      }}
      className="inline-flex items-center gap-1.5 rounded-lg border border-[#333] bg-[#1a1a1a] px-2.5 py-1 text-[11px] font-semibold text-gray-400 transition hover:border-gray-500 hover:text-white"
    >
      {done ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Copy className="h-3.5 w-3.5" />}
      {done ? "Copiato" : label}
    </button>
  );
}
