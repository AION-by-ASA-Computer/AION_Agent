"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Check, ChevronDown, Filter, X } from "lucide-react";
import { cn } from "@/lib/cn";

export type FilterOption = { value: string; label: string };

export interface ColumnFilterLabels {
  aria: (col: string) => string;
  clear: string;
  search: string;
  all: string;
}

/** Header that opens a small filter popover for its own column: free text for titles, a pick-list for users and profiles. */
export function ColumnFilter({
  label,
  value,
  onChange,
  options,
  typeable,
  alignRight,
  fill,
  labels,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options?: FilterOption[];
  /** Also accept free text; the typed text narrows both the rows and the suggestions. */
  typeable?: boolean;
  /** Anchor the popover to the right edge (last column). */
  alignRight?: boolean;
  /** Stretch the header/pill to the full column width. */
  fill?: boolean;
  labels: ColumnFilterLabels;
}) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!box.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey, true);
    };
  }, [open]);

  const needle = (typeable ? value : q).trim().toLowerCase();
  const shown = useMemo(() => (options ?? []).filter((o) => o.label.toLowerCase().includes(needle)), [options, needle]);
  const active = value !== "";
  const current = options?.find((o) => o.value === value)?.label ?? value;

  return (
    <div ref={box} className={cn("relative", fill && "w-full")}>
      <div
        className={cn(
          "flex items-center rounded-lg transition-colors",
          fill ? "w-full" : "-mx-2 inline-flex max-w-full",
          active ? "border border-border bg-secondary text-foreground" : "hover:bg-secondary",
        )}
      >
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-haspopup="dialog"
          aria-expanded={open}
          aria-label={labels.aria(label)}
          title={active ? `${label}: ${current}` : undefined}
          className={cn(
            "focus-ring inline-flex min-w-0 items-center gap-1.5 rounded-lg py-1 pl-2 text-left",
            fill && "flex-1",
            active ? "pr-1 text-sm font-medium" : "pr-2 text-xs font-medium text-muted-foreground hover:text-foreground",
          )}
        >
          {active ? <Filter className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden /> : null}
          <span className="truncate">{active ? current : label}</span>
          {!active && <ChevronDown className="h-3 w-3 shrink-0 opacity-60" aria-hidden />}
        </button>
        {active && (
          <button type="button" onClick={() => onChange("")} aria-label={labels.clear} className="focus-ring mr-1 shrink-0 rounded-md p-1 text-muted-foreground hover:bg-background hover:text-foreground">
            <X className="h-3.5 w-3.5" aria-hidden />
          </button>
        )}
      </div>

      {open && (
        <div role="dialog" aria-label={label} className={cn("absolute top-full z-20 mt-1.5 w-64 rounded-2xl border border-border bg-popover p-2 shadow-xl animate-in fade-in zoom-in-95 duration-100", alignRight ? "right-[-0.5rem]" : "left-[-0.5rem]")}>
          {options ? (
            <>
              {(typeable || options.length > 8) && (
                <input
                  autoFocus
                  value={typeable ? value : q}
                  onChange={(e) => (typeable ? onChange(e.target.value) : setQ(e.target.value))}
                  onKeyDown={(e) => e.key === "Enter" && setOpen(false)}
                  placeholder={labels.search}
                  aria-label={labels.search}
                  className="focus-ring mb-1.5 w-full rounded-xl border border-border bg-background px-3 py-2 text-sm"
                />
              )}
              <ul className="max-h-64 overflow-y-auto">
                {[...(typeable ? [] : [{ value: "", label: labels.all }]), ...shown].map((o) => (
                  <li key={o.value}>
                    <button
                      type="button"
                      onClick={() => {
                        onChange(o.value);
                        setOpen(false);
                        setQ("");
                      }}
                      className="focus-ring flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-sm hover:bg-secondary"
                    >
                      <Check className={cn("h-3.5 w-3.5 shrink-0", value === o.value ? "opacity-100" : "opacity-0")} aria-hidden />
                      <span className="truncate">{o.label}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <div className="relative">
              <input
                autoFocus
                value={value}
                onChange={(e) => onChange(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && setOpen(false)}
                placeholder={labels.search}
                aria-label={labels.search}
                className="focus-ring w-full rounded-xl border border-border bg-background py-2 pl-3 pr-9 text-sm"
              />
              {value && (
                <button type="button" onClick={() => onChange("")} aria-label={labels.clear} className="focus-ring absolute right-1.5 top-1/2 -translate-y-1/2 rounded-lg p-1.5 text-muted-foreground hover:bg-secondary">
                  <X className="h-3.5 w-3.5" aria-hidden />
                </button>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

