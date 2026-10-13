"use client";

import { FileText, Loader2, RefreshCw } from "lucide-react";
import { cn } from "@/lib/cn";
import { getLocale } from "@/lib/i18n/i18n-store";
import { ghostBtn, outlineBtn } from "@/components/ui/classes";
import { kb, stamp } from "./format";
import type { ReportFile, T } from "./types";

const k = "admin_diagnostics.history";
export const REPORTS_DIR = "evals/agent_smoke_tests/outputs/";

export function History({
  items,
  state,
  onRefresh,
  onOpen,
  t,
}: {
  items: ReportFile[];
  state: "loading" | "ready" | "error";
  onRefresh: () => void;
  onOpen: (filename: string) => void;
  t: T;
}) {
  const locale = getLocale();

  return (
    <section aria-labelledby="history-title" className="flex flex-col gap-3">
      <div className="flex items-center gap-3 px-1">
        <div className="min-w-0 flex-1">
          <h2 id="history-title" className="text-lg font-semibold tracking-[-0.015em]">{t(`${k}.title`)}</h2>
          <p className="truncate font-mono text-xs text-muted-foreground">{REPORTS_DIR}</p>
        </div>
        <button type="button" className={outlineBtn} onClick={onRefresh} disabled={state === "loading"}>
          <RefreshCw className={cn("h-3.5 w-3.5", state === "loading" && "animate-spin")} aria-hidden />
          {t(`${k}.refresh`)}
        </button>
      </div>

      {state === "loading" && items.length === 0 ? (
        <div className="flex items-center gap-2 px-1 py-10 text-sm text-muted-foreground" role="status">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
          {t(`${k}.loading`)}
        </div>
      ) : state === "error" && items.length === 0 ? (
        <div role="alert" className="rounded-2xl bg-destructive/[0.09] px-4 py-3.5 text-sm dark:bg-destructive/[0.12]">
          {t(`${k}.error`)}
        </div>
      ) : items.length === 0 ? (
        <div className="flex flex-col items-center rounded-3xl border border-dashed border-border px-6 py-20 text-center">
          <FileText className="mb-4 h-8 w-8 text-muted-foreground" strokeWidth={1.5} aria-hidden />
          <h3 className="text-lg font-semibold tracking-[-0.015em]">{t(`${k}.empty_title`)}</h3>
          <p className="mt-1.5 max-w-[46ch] text-sm text-muted-foreground">{t(`${k}.empty_body`, { path: REPORTS_DIR })}</p>
        </div>
      ) : (
        <ul className="divide-y divide-border/50 overflow-hidden rounded-3xl border border-border/60 bg-card/40">
          {items.map((r) => {
            const single = r.filename.startsWith("report_test_");
            return (
              <li key={r.filename} className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-3 transition-colors hover:bg-secondary/40 sm:px-5">
                <FileText className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
                <div className="min-w-0 flex-1 basis-56">
                  <div className="truncate font-mono text-sm font-medium" title={r.filename}>{r.filename}</div>
                  <div className="text-xs tabular-nums text-muted-foreground">
                    {stamp(r.modified_at, locale)} · {kb(r.size_bytes, locale)}
                  </div>
                </div>
                <span className="rounded-full bg-secondary px-2.5 py-0.5 text-xs font-medium text-muted-foreground">
                  {t(`${k}.${single ? "kind_single" : "kind_suite"}`)}
                </span>
                <button type="button" className={ghostBtn} onClick={() => onOpen(r.filename)}>
                  {t(`${k}.open`)}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
