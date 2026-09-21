"use client";

import { useEffect, useRef, useState } from "react";
import {
  BookOpen,
  CheckCircle2,
  ChevronDown,
  Wrench,
  XCircle,
  Zap,
} from "lucide-react";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";

export type UsedTool = {
  name: string;
  callCount: number;
  hasError: boolean;
};

function formatSlug(slug: string): string {
  return slug
    .replace(/[-_]/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

export function CapabilitiesChip({
  usedTools,
  skills,
}: {
  usedTools: UsedTool[];
  skills: string[];
}) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  const totalTools = usedTools.length;
  const hasAny = totalTools > 0 || skills.length > 0;

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("mousedown", onDoc);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("mousedown", onDoc);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (!hasAny) return null;

  const hasErrors = usedTools.some((t) => t.hasError);

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        id="capabilities-chip-trigger"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-haspopup="true"
        className={cn(
          "focus-ring inline-flex h-8 items-center gap-1.5 rounded-full border px-3 text-[0.786em] font-semibold transition-all duration-200 hover:scale-[1.01] active:scale-[0.99]",
          open
            ? "border-primary/40 bg-primary/10 text-primary"
            : hasErrors
              ? "border-rose-500/40 bg-rose-500/10 text-rose-500 hover:bg-rose-500/15"
              : "border-border/80 bg-muted/20 text-muted-foreground hover:bg-muted/40 hover:text-foreground",
        )}
        title={t("chat.capabilities.label")}
      >
        <Wrench size={12} className="shrink-0" aria-hidden />
        {totalTools > 0 && (
          <span className="tabular-nums">{totalTools}</span>
        )}
        <ChevronDown
          size={10}
          className={cn(
            "shrink-0 opacity-70 transition-transform duration-150",
            open && "rotate-180",
          )}
          aria-hidden
        />
      </button>

      {open && (
        <div
          role="dialog"
          aria-label={t("chat.capabilities.label")}
          className={cn(
            "absolute left-0 top-full z-50 mt-2 w-[min(100vw-2rem,17rem)] rounded-xl border border-border bg-card/95 shadow-xl backdrop-blur-md",
            "animate-in fade-in-0 slide-in-from-top-2 duration-150",
          )}
        >
          {/* ── Section: Tools actually used ── */}
          <div className="px-3 pt-3 pb-1">
            <div className="mb-1.5 flex items-center justify-between">
              <div className="flex items-center gap-1.5">
                <Zap size={11} className="text-violet-500 shrink-0" aria-hidden />
                <span className="text-[0.714em] font-bold uppercase tracking-wider text-violet-500">
                  {t("chat.capabilities.tools_used")}
                </span>
              </div>
              {totalTools > 0 && (
                <span className="rounded-full bg-violet-500/15 px-1.5 py-0.5 text-[0.65em] font-bold tabular-nums text-violet-500">
                  {totalTools}
                </span>
              )}
            </div>

            {totalTools === 0 ? (
              <p className="py-1.5 text-[0.75em] text-muted-foreground/70 italic">
                {t("chat.capabilities.no_tools")}
              </p>
            ) : (
              <ul className="space-y-0.5">
                {usedTools.map((tool) => (
                  <li
                    key={tool.name}
                    className="flex items-center justify-between rounded-lg px-1.5 py-1 hover:bg-muted/40 transition-colors"
                  >
                    <div className="flex items-center gap-1.5 min-w-0">
                      {tool.hasError ? (
                        <XCircle
                          size={13}
                          className="shrink-0 text-rose-500"
                          aria-hidden
                        />
                      ) : (
                        <CheckCircle2
                          size={13}
                          className="shrink-0 text-emerald-500"
                          aria-hidden
                        />
                      )}
                      <span className="truncate text-[0.786em] font-medium text-foreground">
                        {formatSlug(tool.name)}
                      </span>
                    </div>
                    {tool.callCount > 1 && (
                      <span className="ml-2 shrink-0 rounded-full bg-muted px-1.5 py-0.5 text-[0.65em] font-mono tabular-nums text-muted-foreground">
                        ×{tool.callCount}
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="my-1.5 border-t border-border/40" />

          {/* ── Section: Skills ── */}
          <div className="px-3 pb-3 pt-1">
            <div className="mb-1.5 flex items-center justify-between">
              <div className="flex items-center gap-1.5">
                <BookOpen size={11} className="text-amber-500 shrink-0" aria-hidden />
                <span className="text-[0.714em] font-bold uppercase tracking-wider text-amber-500">
                  {t("chat.capabilities.skills")}
                </span>
              </div>
              {skills.length > 0 && (
                <span className="rounded-full bg-amber-500/15 px-1.5 py-0.5 text-[0.65em] font-bold tabular-nums text-amber-500">
                  {skills.length}
                </span>
              )}
            </div>

            {skills.length === 0 ? (
              <p className="py-1.5 text-[0.75em] text-muted-foreground/70 italic">
                {t("chat.capabilities.no_skills")}
              </p>
            ) : (
              <ul className="space-y-0.5">
                {skills.map((skill) => (
                  <li
                    key={skill}
                    className="flex items-center gap-1.5 rounded-lg px-1.5 py-1 hover:bg-muted/40 transition-colors"
                  >
                    <span className="truncate text-[0.786em] font-medium text-foreground">
                      {formatSlug(skill)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {/* ── Footer ── */}
          {totalTools > 0 && (
            <>
              <div className="border-t border-border/40" />
              <p className="px-3 py-2 text-[0.68em] text-muted-foreground/50 select-none">
                {t("chat.capabilities.realtime_hint")}
              </p>
            </>
          )}
        </div>
      )}
    </div>
  );
}
