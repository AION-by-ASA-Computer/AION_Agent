"use client";

import { useCallback, useEffect, useState } from "react";
import { ChevronLeft, ChevronRight, Loader2 } from "lucide-react";
import {
  zoomProjectDigest,
  type DigestZoomNode,
  type DigestZoomResult,
} from "@/lib/api/project-memory";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";

type Props = {
  userId: string;
  projectSlug: string;
  token?: string | null;
  seqCount: number;
};

function rangeLabel(lo: number, hi: number) {
  return `[${lo}, ${hi})`;
}

function nodeRange(node: DigestZoomNode): string | null {
  if (node.kind === "digest" && node.lo != null && node.hi != null) {
    return rangeLabel(node.lo, node.hi);
  }
  if (node.kind === "note" && node.seq != null) {
    return `#${node.seq}`;
  }
  return null;
}

export function ProjectMemoryDigestTree({
  userId,
  projectSlug,
  token,
  seqCount,
}: Props) {
  const t = useT();
  const [lo, setLo] = useState(0);
  const [hi, setHi] = useState(Math.max(1, seqCount));
  const [zoom, setZoom] = useState<DigestZoomResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [history, setHistory] = useState<Array<{ lo: number; hi: number }>>([]);

  const loadZoom = useCallback(
    async (rangeLo: number, rangeHi: number) => {
      if (!projectSlug.trim() || rangeHi <= rangeLo) return;
      setLoading(true);
      setError(null);
      try {
        const data = await zoomProjectDigest(
          userId,
          projectSlug,
          rangeLo,
          rangeHi,
          token
        );
        setZoom(data);
        setLo(rangeLo);
        setHi(rangeHi);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
        setZoom(null);
      } finally {
        setLoading(false);
      }
    },
    [userId, projectSlug, token]
  );

  useEffect(() => {
    if (seqCount > 0) {
      void loadZoom(0, seqCount);
      setHistory([]);
    }
  }, [seqCount, projectSlug, loadZoom]);

  const drill = (node: DigestZoomNode) => {
    if (node.kind !== "digest" || node.lo == null || node.hi == null) return;
    if (node.hi - node.lo < 2) return;
    setHistory((h) => [...h, { lo, hi }]);
    void loadZoom(node.lo, node.hi);
  };

  const goBack = () => {
    const prev = history[history.length - 1];
    if (!prev) return;
    setHistory((h) => h.slice(0, -1));
    void loadZoom(prev.lo, prev.hi);
  };

  const renderSide = (label: string, nodes: DigestZoomNode[] | undefined) => (
    <div className="min-w-0 flex-1 rounded-md border border-border/70 bg-card/50 p-2">
      <p className="mb-2 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
        {label}
      </p>
      {!nodes?.length ? (
        <p className="text-xs text-muted-foreground">{t("project_memory_debug.tree_empty")}</p>
      ) : (
        <ul className="space-y-1.5">
          {nodes.map((node, i) => {
            const range = nodeRange(node);
            const clickable = node.kind === "digest" && (node.hi ?? 0) - (node.lo ?? 0) >= 2;
            return (
              <li key={`${label}-${i}`}>
                <button
                  type="button"
                  disabled={!clickable}
                  onClick={() => drill(node)}
                  className={cn(
                    "w-full rounded px-2 py-1.5 text-left text-xs",
                    clickable
                      ? "hover:bg-muted/80 focus-ring"
                      : "cursor-default opacity-90"
                  )}
                >
                  <div className="mb-0.5 flex items-center gap-1.5">
                    <span
                      className={cn(
                        "rounded px-1 py-0.5 text-[9px] font-medium uppercase",
                        node.kind === "digest"
                          ? "bg-amber-500/15 text-amber-700 dark:text-amber-300"
                          : "bg-primary/10 text-primary"
                      )}
                    >
                      {node.kind}
                    </span>
                    {range ? (
                      <span className="font-mono text-[10px] text-muted-foreground">
                        {range}
                      </span>
                    ) : null}
                    {clickable ? (
                      <ChevronRight className="ml-auto h-3 w-3 text-muted-foreground" />
                    ) : null}
                  </div>
                  <p className="line-clamp-3 whitespace-pre-wrap break-words text-foreground/90">
                    {node.line}
                  </p>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );

  if (seqCount <= 0) {
    return (
      <p className="text-sm text-muted-foreground">{t("project_memory_debug.no_seq")}</p>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          className="focus-ring inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs disabled:opacity-40"
          onClick={goBack}
          disabled={!history.length || loading}
        >
          <ChevronLeft className="h-3.5 w-3.5" />
          {t("project_memory_debug.tree_back")}
        </button>
        <span className="font-mono text-xs text-muted-foreground">
          {rangeLabel(lo, hi)}
        </span>
        <button
          type="button"
          className="focus-ring rounded-md border px-2 py-1 text-xs"
          onClick={() => {
            setHistory([]);
            void loadZoom(0, seqCount);
          }}
          disabled={loading}
        >
          {t("project_memory_debug.tree_root")}
        </button>
      </div>

      {loading ? (
        <div className="flex justify-center py-6 text-muted-foreground">
          <Loader2 className="h-5 w-5 animate-spin" />
        </div>
      ) : null}
      {error ? <p className="text-xs text-destructive">{error}</p> : null}

      {zoom?.error ? (
        <p className="text-xs text-muted-foreground">
          {t("project_memory_debug.zoom_error")}: {zoom.error}
        </p>
      ) : null}

      {zoom?.digest ? (
        <div
          className={cn(
            "rounded-lg border p-3 text-sm",
            zoom.digest.ready
              ? "border-amber-500/30 bg-amber-500/5"
              : "border-destructive/30 bg-destructive/5"
          )}
        >
          <div className="mb-1 flex flex-wrap items-center gap-2">
            <span className="text-[10px] font-semibold uppercase text-amber-700 dark:text-amber-300">
              digest
            </span>
            <span
              className={cn(
                "rounded px-1.5 py-0.5 text-[10px] font-medium",
                zoom.digest.ready
                  ? "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300"
                  : "bg-destructive/15 text-destructive"
              )}
            >
              {zoom.digest.ready
                ? t("project_memory_debug.digest_ready")
                : t("project_memory_debug.digest_stale")}
            </span>
          </div>
          <p className="whitespace-pre-wrap break-words text-foreground/90">
            {zoom.digest.summary?.trim() || t("project_memory_debug.no_summary")}
          </p>
        </div>
      ) : null}

      {zoom && !zoom.error ? (
        <div className="flex gap-2">
          {renderSide(t("project_memory_debug.tree_left"), zoom.left)}
          {renderSide(t("project_memory_debug.tree_right"), zoom.right)}
        </div>
      ) : null}
    </div>
  );
}
