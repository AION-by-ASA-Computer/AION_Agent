"use client";

import { useMemo, useState } from "react";
import { Check, Code, Columns2, Copy, Download, Eye, FileText } from "lucide-react";
import { cn } from "@/lib/cn";
import { getLocale } from "@/lib/i18n/i18n-store";
import { outlineBtn, solidBtn } from "@/components/ui/classes";
import { Markdown } from "./Markdown";
import { saveMarkdown } from "./files";
import type { T } from "./types";

type Mode = "preview" | "source" | "split";
const k = "admin_diagnostics.report";
const MODES: { id: Mode; icon: typeof Eye; split?: boolean }[] = [
  { id: "preview", icon: Eye },
  { id: "source", icon: Code },
  { id: "split", icon: Columns2, split: true },
];

export function ReportReader({ content, name, t }: { content: string; name: string; t: T }) {
  const locale = getLocale();
  const [mode, setMode] = useState<Mode>("preview");
  const [copied, setCopied] = useState(false);

  const stats = useMemo(() => {
    const words = content.trim() ? content.trim().split(/\s+/).length : 0;
    return { words, lines: content ? content.split("\n").length : 0, minutes: Math.max(1, Math.ceil(words / 200)) };
  }, [content]);

  if (!content) {
    return (
      <div className="flex flex-col items-center rounded-3xl border border-dashed border-border px-6 py-20 text-center">
        <FileText className="mb-4 h-8 w-8 text-muted-foreground" strokeWidth={1.5} aria-hidden />
        <h2 className="text-lg font-semibold tracking-[-0.015em]">{t(`${k}.empty_title`)}</h2>
        <p className="mt-1.5 max-w-[46ch] text-sm text-muted-foreground">{t(`${k}.empty_body`)}</p>
      </div>
    );
  }

  const num = new Intl.NumberFormat(locale);
  const source = (
    <pre className="whitespace-pre-wrap break-words p-5 font-mono text-xs leading-relaxed text-muted-foreground">{content}</pre>
  );

  return (
    <div className="overflow-hidden rounded-3xl border border-border/60 bg-card/40">
      <div className="flex flex-col gap-3 border-b border-border/50 px-5 py-3.5 sm:flex-row sm:items-center">
        <div className="min-w-0 flex-1">
          <h3 className="truncate text-sm font-semibold">{name || t(`${k}.title_fallback`)}</h3>
          <p className="text-xs tabular-nums text-muted-foreground">
            {t(`${k}.stats`, { words: num.format(stats.words), lines: num.format(stats.lines), minutes: stats.minutes })}
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <div role="group" aria-label={t(`${k}.mode_aria`)} className="inline-flex h-9 items-center gap-0.5 rounded-xl border border-border bg-card p-0.5">
            {MODES.map(({ id, icon: Icon, split }) => (
              <button
                key={id}
                type="button"
                aria-pressed={mode === id}
                onClick={() => setMode(id)}
                className={cn(
                  "focus-ring inline-flex h-8 items-center gap-1.5 rounded-[0.6rem] px-2.5 text-xs font-medium transition-colors",
                  split && "hidden lg:inline-flex",
                  mode === id ? "bg-secondary text-foreground" : "text-muted-foreground hover:text-foreground",
                )}
              >
                <Icon className="h-3.5 w-3.5" aria-hidden />
                {t(`${k}.mode_${id}`)}
              </button>
            ))}
          </div>
          <button
            type="button"
            className={outlineBtn}
            onClick={async () => {
              await navigator.clipboard.writeText(content);
              setCopied(true);
              window.setTimeout(() => setCopied(false), 1600);
            }}
          >
            {copied ? <Check className="h-3.5 w-3.5 text-success" aria-hidden /> : <Copy className="h-3.5 w-3.5" aria-hidden />}
            {copied ? t(`${k}.copied`) : t(`${k}.copy`)}
          </button>
          <button type="button" className={solidBtn} onClick={() => saveMarkdown(content, name || "smoke_test_report.md")}>
            <Download className="h-3.5 w-3.5" aria-hidden />
            {t(`${k}.download`)}
          </button>
        </div>
      </div>

      {mode === "preview" && (
        <div className="p-5 sm:p-8">
          <Markdown className="mx-auto max-w-[75ch]">{content}</Markdown>
        </div>
      )}
      {mode === "source" && source}
      {mode === "split" && (
        <div className="grid h-[40rem] max-h-[70dvh] grid-cols-2 divide-x divide-border/50">
          <div className="overflow-y-auto">{source}</div>
          <div className="overflow-y-auto p-6"><Markdown>{content}</Markdown></div>
        </div>
      )}
    </div>
  );
}
