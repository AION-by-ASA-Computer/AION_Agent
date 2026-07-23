"use client";

import { Check, Copy } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";

const MAX_HIGHLIGHT_CHARS = 48_000;

function normalizeLanguage(language: string): string {
  const raw = language.trim().toLowerCase();
  if (!raw || raw === "text") return "text";
  if (raw === "py") return "python";
  if (raw === "js") return "javascript";
  if (raw === "ts") return "typescript";
  if (raw === "md") return "markdown";
  if (raw === "yml") return "yaml";
  if (raw === "sh" || raw === "shell") return "bash";
  return raw;
}

export function MarkdownCodeBlock({
  code,
  language = "text",
  streaming = false,
  className,
}: {
  code: string;
  language?: string;
  streaming?: boolean;
  className?: string;
}) {
  const t = useT();
  const [copied, setCopied] = useState(false);
  const [highlight, setHighlight] = useState<{ key: string; html: string } | null>(null);
  const lang = useMemo(() => normalizeLanguage(language), [language]);
  const shouldHighlight =
    !streaming && code.trim().length > 0 && code.length <= MAX_HIGHLIGHT_CHARS;
  const highlightKey = `${lang}:${code}`;
  const html = highlight?.key === highlightKey ? highlight.html : "";

  useEffect(() => {
    let cancelled = false;
    if (!shouldHighlight) return;
    void (async () => {
      try {
        const { codeToHtml } = await import("shiki/bundle/web");
        const rendered = await codeToHtml(code, {
          lang,
          theme: "github-dark-default",
        });
        if (!cancelled) setHighlight({ key: highlightKey, html: rendered });
      } catch {
        if (!cancelled) setHighlight(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [code, highlightKey, lang, shouldHighlight]);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1400);
    } catch {
      setCopied(false);
    }
  };

  return (
    <div
      className={cn(
        "not-prose group/code my-3 overflow-hidden rounded-xl border border-border/80 bg-[#0d1117] text-xs shadow-sm ring-1 ring-black/5 dark:ring-white/10",
        className
      )}
    >
      <div className="flex items-center justify-between gap-2 border-b border-white/10 bg-[#161b22] px-3 py-1.5">
        <span className="font-mono text-[10px] font-medium uppercase tracking-wide text-[#8b949e]">
          {lang}
        </span>
        <button
          type="button"
          className="focus-ring inline-flex items-center gap-1 rounded-md border border-white/10 bg-white/5 px-2 py-0.5 text-[10px] font-medium text-[#c9d1d9] opacity-100 transition-opacity hover:bg-white/10 sm:opacity-0 sm:group-hover/code:opacity-100 sm:focus-visible:opacity-100"
          onClick={() => void copy()}
          aria-label={t("chat.actions.copy")}
        >
          {copied ? <Check size={11} aria-hidden /> : <Copy size={11} aria-hidden />}
          {copied ? t("chat.actions.copied") : t("chat.actions.copy")}
        </button>
      </div>
      <div className="max-h-[min(28rem,50vh)] overflow-auto">
        {html ? (
          <div
            className="[&_pre]:!m-0 [&_pre]:!bg-transparent [&_pre]:!p-3 [&_pre]:text-[12px] [&_pre]:leading-relaxed [&_code]:font-mono"
            dangerouslySetInnerHTML={{ __html: html }}
          />
        ) : (
          <pre className="m-0 whitespace-pre-wrap break-words p-3 font-mono text-[12px] leading-relaxed text-[#e6edf3]">
            <code>{code}</code>
          </pre>
        )}
      </div>
    </div>
  );
}
