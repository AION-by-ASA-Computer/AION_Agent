"use client";

import React, { useCallback, useMemo, useState } from "react";
import {
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock,
  ExternalLink,
  FileText,
  Loader2,
  Wrench,
  XCircle,
} from "lucide-react";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";
import {
  fetchSessionFileText,
  sessionDownloadUrl,
  type ToolLedgerEntry,
} from "@/lib/api/aion";

const PREVIEW_MAX_HEIGHT = "min(42vh, 420px)";

function formatChars(n?: number): string {
  const v = Number(n || 0);
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 1000) return `${(v / 1000).toFixed(1)}k`;
  return String(v);
}

function formatBytes(bytes?: number): string {
  if (bytes === undefined || bytes === null || Number.isNaN(bytes)) return "";
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
}

function formatTime(ts?: number): string {
  if (!ts) return "";
  try {
    return new Date(ts * 1000).toLocaleTimeString(undefined, {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return "";
  }
}

function detectPreviewLanguage(text: string, path?: string): string {
  const p = (path || "").toLowerCase();
  if (p.endsWith(".json")) return "json";
  if (p.endsWith(".md")) return "markdown";
  if (p.endsWith(".html") || p.endsWith(".htm")) return "html";
  const trimmed = text.trimStart();
  if (trimmed.startsWith("{") || trimmed.startsWith("[")) {
    try {
      JSON.parse(trimmed.slice(0, 2000));
      return "json";
    } catch {
      /* fall through */
    }
  }
  return "text";
}

type PreviewState = {
  key: string;
  title: string;
  subtitle?: string;
  relativePath?: string;
  inlineNote?: string;
};

export function ToolResultsPanel({
  entries,
  conversationId,
  token,
}: {
  entries: ToolLedgerEntry[];
  conversationId?: string;
  token?: string | null;
}) {
  const t = useT();
  const [expanded, setExpanded] = useState(true);
  const [preview, setPreview] = useState<PreviewState | null>(null);
  const [previewText, setPreviewText] = useState("");
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);

  const sorted = useMemo(
    () => [...entries].sort((a, b) => Number(a.seq || 0) - Number(b.seq || 0)),
    [entries],
  );

  const openPreview = useCallback(
    async (entry: ToolLedgerEntry) => {
      const rel = (entry.path || "").trim();
      const key = `seq-${entry.seq ?? "?"}`;
      const title = String(entry.tool || "tool");
      const subtitle = String(entry.target || "");

      if (!rel || rel === "inline") {
        setPreview({
          key,
          title,
          subtitle,
          inlineNote: t("artifacts.tool_results.inline_only"),
        });
        setPreviewText("");
        setPreviewError(null);
        setPreviewLoading(false);
        return;
      }

      if (!conversationId) return;

      setPreview({ key, title, subtitle, relativePath: rel });
      setPreviewText("");
      setPreviewError(null);
      setPreviewLoading(true);
      try {
        const text = await fetchSessionFileText(conversationId, rel, token);
        setPreviewText(text);
      } catch (err) {
        setPreviewError(err instanceof Error ? err.message : String(err));
      } finally {
        setPreviewLoading(false);
      }
    },
    [conversationId, token, t],
  );

  if (!sorted.length) {
    return null;
  }

  const previewLang = preview?.relativePath
    ? detectPreviewLanguage(previewText, preview.relativePath)
    : "text";

  return (
    <div className="space-y-2">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center justify-between px-1 py-1 border-b border-border/15 pb-2 select-none"
      >
        <h3 className="text-[0.786em] font-bold uppercase tracking-wider text-muted-foreground/60 flex items-center gap-1.5">
          <Wrench size={12} className="text-amber-500/80" />
          {t("artifacts.tool_results.title")}
        </h3>
        <span className="flex items-center gap-1.5 text-[0.714em] text-muted-foreground/60">
          <span className="bg-amber-500/10 text-amber-600 dark:text-amber-400 border border-amber-500/20 px-1.5 py-0.5 rounded-full">
            {sorted.length}
          </span>
          {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        </span>
      </button>

      {expanded ? (
        <div className="space-y-2 animate-in fade-in-50 duration-150">
          <div className="rounded-lg border border-border/50 overflow-hidden bg-card/30">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-[0.786em]">
                <thead>
                  <tr className="border-b border-border/40 bg-muted/30 text-muted-foreground">
                    <th className="px-2 py-1.5 font-semibold w-8">#</th>
                    <th className="px-2 py-1.5 font-semibold">{t("artifacts.tool_results.col_tool")}</th>
                    <th className="px-2 py-1.5 font-semibold hidden sm:table-cell">
                      {t("artifacts.tool_results.col_target")}
                    </th>
                    <th className="px-2 py-1.5 font-semibold w-12 text-right">
                      {t("artifacts.tool_results.col_size")}
                    </th>
                    <th className="px-2 py-1.5 font-semibold w-8" />
                  </tr>
                </thead>
                <tbody>
                  {sorted.map((row) => {
                    const seq = row.seq ?? "?";
                    const tool = String(row.tool || "tool");
                    const target = String(row.target || "—");
                    const ok = row.ok !== false;
                    const hasFile = Boolean(row.path && row.path !== "inline");
                    const isActive = preview?.key === `seq-${seq}`;
                    return (
                      <tr
                        key={`${seq}-${tool}`}
                        className={cn(
                          "border-b border-border/25 last:border-0 transition-colors",
                          isActive ? "bg-amber-500/10" : "hover:bg-muted/25",
                        )}
                      >
                        <td className="px-2 py-1.5 font-mono text-muted-foreground">{seq}</td>
                        <td className="px-2 py-1.5">
                          <div className="flex items-center gap-1.5 min-w-0">
                            {ok ? (
                              <CheckCircle2 size={12} className="shrink-0 text-emerald-500/80" />
                            ) : (
                              <XCircle size={12} className="shrink-0 text-rose-500/80" />
                            )}
                            <span className="truncate font-medium text-foreground/90">{tool}</span>
                          </div>
                          {row.dur_ms != null ? (
                            <span className="mt-0.5 flex items-center gap-1 text-[0.643em] text-muted-foreground/70 pl-5">
                              <Clock size={10} />
                              {row.dur_ms}ms
                              {row.ts ? ` · ${formatTime(row.ts)}` : ""}
                            </span>
                          ) : null}
                        </td>
                        <td className="px-2 py-1.5 hidden sm:table-cell max-w-[9rem]">
                          <span className="line-clamp-2 text-muted-foreground break-all">{target}</span>
                        </td>
                        <td className="px-2 py-1.5 text-right font-mono text-muted-foreground">
                          {formatChars(row.chars)}
                        </td>
                        <td className="px-1 py-1">
                          <button
                            type="button"
                            disabled={!hasFile && !row.path}
                            onClick={() => void openPreview(row)}
                            className={cn(
                              "focus-ring rounded px-1.5 py-0.5 text-[0.643em] font-medium transition-colors",
                              hasFile || row.path === "inline"
                                ? "text-amber-600 dark:text-amber-400 hover:bg-amber-500/15"
                                : "text-muted-foreground/40 cursor-default",
                            )}
                            title={hasFile ? row.path : undefined}
                          >
                            {t("artifacts.tool_results.view")}
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>

          {preview ? (
            <div className="rounded-lg border border-amber-500/25 bg-amber-500/5 overflow-hidden">
              <div className="flex items-start justify-between gap-2 border-b border-amber-500/20 px-3 py-2">
                <div className="min-w-0">
                  <p className="text-xs font-semibold text-foreground truncate">{preview.title}</p>
                  {preview.subtitle ? (
                    <p className="text-[0.714em] text-muted-foreground truncate">{preview.subtitle}</p>
                  ) : null}
                  {preview.relativePath ? (
                    <p className="mt-0.5 font-mono text-[0.643em] text-muted-foreground/80 truncate">
                      {preview.relativePath}
                    </p>
                  ) : null}
                </div>
                <div className="flex shrink-0 items-center gap-1">
                  {preview.relativePath && conversationId ? (
                    <a
                      href={sessionDownloadUrl(conversationId, preview.relativePath, token)}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="focus-ring rounded p-1 text-muted-foreground hover:text-foreground hover:bg-muted/50"
                      title={t("artifacts.download")}
                    >
                      <ExternalLink size={14} />
                    </a>
                  ) : null}
                  <button
                    type="button"
                    onClick={() => {
                      setPreview(null);
                      setPreviewText("");
                      setPreviewError(null);
                    }}
                    className="focus-ring rounded p-1 text-muted-foreground hover:text-foreground hover:bg-muted/50"
                  >
                    <span className="sr-only">Close</span>×
                  </button>
                </div>
              </div>

              <div className="p-2">
                {preview.inlineNote ? (
                  <p className="text-xs text-muted-foreground px-1 py-2">{preview.inlineNote}</p>
                ) : null}
                {previewLoading ? (
                  <div className="flex items-center justify-center gap-2 py-8 text-muted-foreground text-xs">
                    <Loader2 size={16} className="animate-spin" />
                    {t("artifacts.tool_results.loading")}
                  </div>
                ) : null}
                {previewError ? (
                  <p className="text-xs text-rose-500 px-1 py-2">{previewError}</p>
                ) : null}
                {!previewLoading && !previewError && previewText ? (
                  <pre
                    className={cn(
                      "overflow-auto rounded-md border border-border/40 bg-background/80 p-3 text-[0.714em] leading-relaxed font-mono text-foreground/90 whitespace-pre-wrap break-words",
                    )}
                    style={{ maxHeight: PREVIEW_MAX_HEIGHT }}
                  >
                    {previewText}
                  </pre>
                ) : null}
                {!previewLoading && !previewError && preview.relativePath && !previewText ? (
                  <p className="text-xs text-muted-foreground px-1 py-2 flex items-center gap-1.5">
                    <FileText size={12} />
                    {t("artifacts.tool_results.empty_file")}
                  </p>
                ) : null}
                {previewText && previewLang === "json" ? (
                  <p className="mt-1 text-[0.643em] text-muted-foreground/60 px-1">JSON</p>
                ) : null}
              </div>
            </div>
          ) : (
            <p className="text-[0.714em] text-muted-foreground/60 px-1">
              {t("artifacts.tool_results.hint")}
            </p>
          )}
        </div>
      ) : null}
    </div>
  );
}
