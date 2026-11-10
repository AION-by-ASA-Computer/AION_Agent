"use client";

import { Check, Copy, DownloadIcon, Loader2 } from "lucide-react";
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
  const [isOpen, setIsOpen] = useState(defaultOpen);
  // Result of the on-demand download, keyed by URL so a different file never
  // reuses another file's content. `text` may legitimately be "" (empty file).
  const [fetched, setFetched] = useState<{ url: string; text?: string; error?: string } | null>(null);

  // Sync isOpen if defaultOpen prop changes
  useEffect(() => {
    if (defaultOpen) {
      setIsOpen(true);
    }
  }, [defaultOpen]);

  // History / reloaded artifacts carry no content (empty buffer or a
  // "[File: …]" placeholder): the file is downloaded from the session
  // workspace (`savedPath`, e.g. workspace/data.json) when the block is opened.
  // Live-streamed artifacts already have their content in `code`.
  const codeIsPlaceholder = code.startsWith("[File:") && code.endsWith("]");
  const needsFetch =
    Boolean(downloadUrl) && (codeIsPlaceholder || (!code.trim() && Boolean(savedPath)));
  const fetchResult = fetched && fetched.url === downloadUrl ? fetched : null;

  // Everything below is derived (no mirrored state): the previous version kept
  // `isLoading` in state and in the effect deps, so setting it re-ran the
  // effect whose cleanup cancelled the in-flight request → endless spinner.
  const displayedCode =
    needsFetch && fetchResult?.text !== undefined ? fetchResult.text : code;
  const fetchError = needsFetch && fetchResult?.error ? fetchResult.error : null;
  const isLoading = isOpen && needsFetch && !fetchResult;
  const isPlaceholder = displayedCode.startsWith("[File:") && displayedCode.endsWith("]");

  // Download the file content once per URL when the block is open. Closing the
  // block mid-download aborts it; reopening starts a fresh request. Errors are
  // not retried automatically (the "Riprova" button clears the result).
  useEffect(() => {
    if (!isOpen || !needsFetch || !downloadUrl || fetchResult) return;
    const ac = new AbortController();
    const url = downloadUrl;
    fetch(url, { signal: ac.signal, cache: "no-store" })
      .then((res) => {
        if (!res.ok) {
          throw new Error(`HTTP ${res.status}`);
        }
        return res.text();
      })
      .then((text) => setFetched({ url, text }))
      .catch((err) => {
        if (ac.signal.aborted) return;
        console.error("Error fetching artifact content:", err);
        setFetched({ url, error: "Impossibile caricare il contenuto del file." });
      });
    return () => ac.abort();
  }, [isOpen, needsFetch, downloadUrl, fetchResult]);

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
          // Dual theme: colors resolved in CSS per active theme (globals.css).
          themes: { light: "github-light-default", dark: "github-dark-default" },
          defaultColor: false,
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
        // Colors come from the --code-* theme tokens (light/dark), not fixed hex.
        "aion-code-surface overflow-hidden rounded-xl border border-[hsl(var(--code-border))] bg-[hsl(var(--code-bg))] text-xs shadow-sm",
        className
      )}
      open={isOpen}
      onToggle={(e) => setIsOpen(e.currentTarget.open)}
    >
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 border-b border-[hsl(var(--code-border))] bg-[hsl(var(--code-header-bg))] px-3.5 py-2 text-[hsl(var(--code-fg))]">
        <div className="min-w-0">
          <div className="truncate text-[0.857em] font-semibold text-[hsl(var(--code-title))]">{title}</div>
          <div className="mt-0.5 truncate font-mono text-[0.714em] text-[hsl(var(--code-muted))]">
            {savedPath || lang}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {downloadUrl ? (
            <a
              className="focus-ring inline-flex items-center gap-1 rounded-lg border border-[hsl(var(--code-border))] bg-[hsl(var(--code-bg))] px-2.5 py-1 text-[0.786em] text-[hsl(var(--code-fg))] hover:bg-[hsl(var(--code-border))] transition-all duration-200 active:scale-[0.98]"
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
              className="focus-ring inline-flex items-center gap-1 rounded-lg border border-[hsl(var(--code-border))] bg-[hsl(var(--code-bg))] px-2.5 py-1 text-[0.786em] text-[hsl(var(--code-fg))] hover:bg-[hsl(var(--code-border))] transition-all duration-200 active:scale-[0.98]"
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
          <div className="flex items-center gap-2 p-4 text-[hsl(var(--code-muted))] font-mono text-[0.857em]">
            <Loader2 className="animate-spin text-primary shrink-0" size={14} />
            Caricamento contenuto file...
          </div>
        ) : fetchError ? (
          <div className="p-4 text-destructive font-mono text-[0.857em] flex flex-col gap-1">
            <span className="font-semibold">Errore di caricamento</span>
            <span>{fetchError}</span>
            <button
              type="button"
              onClick={() => setFetched(null)}
              className="mt-2 w-fit text-primary hover:underline text-[0.786em]"
            >
              Riprova
            </button>
            {downloadUrl && (
              <a
                href={downloadUrl}
                target="_blank"
                rel="noreferrer"
                className="mt-2 text-primary hover:underline text-[0.786em] inline-flex items-center gap-1"
              >
                Tenta di scaricare direttamente
              </a>
            )}
          </div>
        ) : html ? (
          <div
            className="[&_pre]:!m-0 [&_pre]:!bg-transparent [&_pre]:!p-4 [&_pre]:text-[0.857em] [&_pre]:leading-relaxed [&_code]:font-mono"
            dangerouslySetInnerHTML={{ __html: html }}
          />
        ) : (
          <pre className="m-0 whitespace-pre-wrap break-words p-4 font-mono text-[0.857em] leading-relaxed text-[hsl(var(--code-fg))]">
            {displayedCode || "Artifact in attesa di contenuto..."}
          </pre>
        )}
      </div>

      {execution ? (
        <div className="border-t border-[hsl(var(--code-border))] bg-[hsl(var(--code-header-bg))]">
          <div className="px-3 py-2 text-[0.786em] font-medium text-[hsl(var(--code-muted))]">Risultato esecuzione</div>
          <pre className="m-0 max-h-56 overflow-auto whitespace-pre-wrap p-4 pt-0 font-mono text-[0.786em] leading-relaxed text-[hsl(var(--code-fg))]">
            {execution}
          </pre>
        </div>
      ) : null}
    </details>
  );
}
