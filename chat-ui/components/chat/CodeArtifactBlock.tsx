"use client";

import { Check, Copy, DownloadIcon, ExternalLink, Loader2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { cn } from "@/lib/cn";

const MAX_HIGHLIGHT_CHARS = 60_000;

function normalizeLanguage(language: string): string {
  const raw = language.trim().toLowerCase();
  if (!raw) return "text";
  if (raw === "py") return "python";
  if (raw === "js") return "javascript";
  if (raw === "ts") return "typescript";
  if (raw === "tsx" || raw === "jsx") return raw;
  if (raw === "md") return "markdown";
  if (raw === "yml") return "yaml";
  if (raw === "sh" || raw === "bash" || raw === "shell") return "bash";
  return raw;
}

export function CodeArtifactBlock({
  id,
  title,
  language,
  code,
  downloadUrl,
  savedPath,
  execution,
  defaultOpen = false,
  streaming = false,
  className,
}: {
  id?: string;
  title: string;
  language: string;
  code: string;
  downloadUrl?: string;
  savedPath?: string;
  execution?: string;
  defaultOpen?: boolean;
  /** Live stream in progress — skip expensive syntax highlighting. */
  streaming?: boolean;
  className?: string;
}) {
  const [displayedCode, setDisplayedCode] = useState(code);
  const [isOpen, setIsOpen] = useState(defaultOpen);
  const [isLoading, setIsLoading] = useState(false);
  const [fetchError, setFetchError] = useState<string | null>(null);

  // Sync displayedCode if code prop changes (essential during live stream)
  useEffect(() => {
    setDisplayedCode(code);
  }, [code]);

  // Sync isOpen if defaultOpen prop changes
  useEffect(() => {
    if (defaultOpen) {
      setIsOpen(true);
    }
  }, [defaultOpen]);

  const isPlaceholder = useMemo(() => {
    return displayedCode.startsWith("[File:") && displayedCode.endsWith("]");
  }, [displayedCode]);

  const needsFetch = useMemo(() => {
    if (!downloadUrl) return false;
    if (isPlaceholder) return true;
    return !displayedCode.trim() && Boolean(savedPath);
  }, [downloadUrl, displayedCode, isPlaceholder, savedPath]);

  // Fetch the actual file content when expanded and it's a placeholder
  useEffect(() => {
    if (isOpen && needsFetch && downloadUrl && !isLoading) {
      let cancelled = false;
      setIsLoading(true);
      setFetchError(null);

      fetch(downloadUrl)
        .then((res) => {
          if (!res.ok) {
            throw new Error(`HTTP error! status: ${res.status}`);
          }
          return res.text();
        })
        .then((text) => {
          if (!cancelled) {
            setDisplayedCode(text);
            setIsLoading(false);
          }
        })
        .catch((err) => {
          if (!cancelled) {
            console.error("Error fetching artifact content:", err);
            setFetchError("Impossibile caricare il contenuto del file.");
            setIsLoading(false);
          }
        });

      return () => {
        cancelled = true;
      };
    }
  }, [isOpen, needsFetch, downloadUrl, isLoading]);

  const [highlight, setHighlight] = useState<{ key: string; html: string } | null>(null);
  const [copied, setCopied] = useState(false);
  const lang = useMemo(() => normalizeLanguage(language), [language]);
  const shouldHighlight =
    !streaming &&
    displayedCode.trim().length > 0 &&
    displayedCode.length <= MAX_HIGHLIGHT_CHARS &&
    !isPlaceholder;
  const highlightKey = `${lang}:${displayedCode}`;
  const html = highlight?.key === highlightKey ? highlight.html : "";

  useEffect(() => {
    let cancelled = false;
    if (!shouldHighlight) return;
    void (async () => {
      try {
        const { codeToHtml } = await import("shiki/bundle/web");
        const rendered = await codeToHtml(displayedCode, {
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
  }, [displayedCode, highlightKey, lang, shouldHighlight]);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(displayedCode);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1400);
    } catch {
      setCopied(false);
    }
  };

  return (
    <details
      id={id}
      className={cn(
        "overflow-hidden rounded-xl border border-border bg-[#0d1117] text-xs shadow-sm ring-1 ring-white/5",
        className
      )}
      open={isOpen}
      onToggle={(e) => setIsOpen(e.currentTarget.open)}
    >
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 border-b border-white/10 bg-[#161b22] px-3.5 py-2 text-[#c9d1d9]">
        <div className="min-w-0">
          <div className="truncate text-[12px] font-semibold text-[#f0f6fc]">{title}</div>
          <div className="mt-0.5 truncate font-mono text-[10px] text-[#8b949e]">
            {savedPath || lang}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {downloadUrl ? (
            <a
              className="focus-ring inline-flex items-center gap-1 rounded-lg border border-white/10 bg-white/5 px-2.5 py-1 text-[11px] text-[#c9d1d9] hover:bg-white/10 transition-all duration-200 active:scale-[0.98]"
              href={downloadUrl}
              target="_blank"
              rel="noreferrer"
              onClick={(e) => e.stopPropagation()}
            >
              <DownloadIcon size={12} aria-hidden />
              Scarica
            </a>
          ) : null}
          {displayedCode && !isPlaceholder && !isLoading ? (
            <button
              type="button"
              className="focus-ring inline-flex items-center gap-1 rounded-lg border border-white/10 bg-white/5 px-2.5 py-1 text-[11px] text-[#c9d1d9] hover:bg-white/10 transition-all duration-200 active:scale-[0.98]"
              onClick={(e) => {
                e.preventDefault();
                e.stopPropagation();
                void copy();
              }}
            >
              {copied ? <Check size={12} aria-hidden /> : <Copy size={12} aria-hidden />}
              {copied ? "Copiato" : "Copia"}
            </button>
          ) : null}
        </div>
      </summary>

      <div className="max-h-[520px] overflow-auto">
        {isLoading ? (
          <div className="flex items-center gap-2 p-4 text-[#8b949e] font-mono text-[12px]">
            <Loader2 className="animate-spin text-primary shrink-0" size={14} />
            Caricamento contenuto file...
          </div>
        ) : fetchError ? (
          <div className="p-4 text-rose-400 font-mono text-[12px] flex flex-col gap-1">
            <span className="font-semibold text-rose-300">Errore di caricamento</span>
            <span>{fetchError}</span>
            {downloadUrl && (
              <a
                href={downloadUrl}
                target="_blank"
                rel="noreferrer"
                className="mt-2 text-primary hover:underline text-[11px] inline-flex items-center gap-1"
              >
                Tenta di scaricare direttamente
              </a>
            )}
          </div>
        ) : html ? (
          <div
            className="[&_pre]:!m-0 [&_pre]:!bg-transparent [&_pre]:!p-4 [&_pre]:text-[12px] [&_pre]:leading-relaxed [&_code]:font-mono"
            dangerouslySetInnerHTML={{ __html: html }}
          />
        ) : (
          <pre className="m-0 whitespace-pre-wrap break-words p-4 font-mono text-[12px] leading-relaxed text-[#c9d1d9]">
            {displayedCode || "Artifact in attesa di contenuto..."}
          </pre>
        )}
      </div>

      {execution ? (
        <div className="border-t border-white/10 bg-black/20">
          <div className="px-3 py-2 text-[11px] font-medium text-[#8b949e]">Risultato esecuzione</div>
          <pre className="m-0 max-h-56 overflow-auto whitespace-pre-wrap p-4 pt-0 font-mono text-[11px] leading-relaxed text-[#c9d1d9]">
            {execution}
          </pre>
        </div>
      ) : null}
    </details>
  );
}
