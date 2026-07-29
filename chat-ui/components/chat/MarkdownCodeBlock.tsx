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
        "not-prose group/code my-3 overflow-hidden rounded-xl border border-border/80 bg-[#0d1117] shadow-sm ring-1 ring-black/5 dark:ring-white/10",
        className
      )}
      style={{ fontSize: "var(--aion-chat-code-font-size, 10.5px)" }}
    >
      <div className="flex items-center justify-between gap-2 border-b border-white/10 bg-[#161b22] px-3.5 py-2">
        <span className="font-mono text-[0.86em] font-medium uppercase tracking-wide text-[#8b949e]">
          {lang}
        </span>
        <button
          type="button"
          className="focus-ring inline-flex items-center gap-1.5 rounded-md border border-white/10 bg-white/5 px-2.5 py-[0.35em] text-[0.86em] font-medium text-[#c9d1d9] opacity-100 transition-opacity hover:bg-white/10 sm:opacity-0 sm:group-hover/code:opacity-100 sm:focus-visible:opacity-100"
          onClick={() => void copy()}
          aria-label={t("chat.actions.copy")}
        >
          {copied ? <Check size={13} aria-hidden /> : <Copy size={13} aria-hidden />}
          {copied ? t("chat.actions.copied") : t("chat.actions.copy")}
        </button>
      </div>
      <div className="max-h-[min(32rem,55vh)] overflow-auto">
        {html ? (
          <div
            className="[&_pre]:!m-0 [&_pre]:!bg-transparent [&_pre]:!p-4 [&_pre]:!text-[1em] [&_pre]:!leading-[1.65] [&_code]:font-mono"
            dangerouslySetInnerHTML={{ __html: html }}
          />
        ) : (
          <pre className="m-0 whitespace-pre-wrap break-words p-4 font-mono text-[1em] leading-[1.65] text-[#e6edf3]">
            <code>{code}</code>
          </pre>
        )}
      </div>
    </div>
  );
}
