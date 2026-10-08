"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Check, ChevronDown, Database, Folder, Search, Sparkles } from "lucide-react";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";
import { fetchSqlProjects, type SqlProject } from "@/lib/api/query-memory";

const STORAGE_KEY = "aion_sql_query_project";

type Props = {
  userId: string;
  token?: string | null;
  profileSlug?: string;
  value: string;
  onChange: (slug: string) => void;
  compact?: boolean;
  variant?: "compact" | "panel" | "hero";
  className?: string;
};

export function ProjectMemoryToolbar({
  userId,
  token,
  profileSlug,
  value,
  onChange,
  compact = false,
  variant: variantProp,
  className,
}: Props) {
  const variant = variantProp ?? (compact ? "compact" : "hero");
  const t = useT();
  const [projects, setProjects] = useState<SqlProject[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const containerRef = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    setLoadError(null);
    try {
      const list = await fetchSqlProjects(userId, token, profileSlug);
      setProjects(list);
      if (list.length && !value) {
        onChange(list[0].slug);
      }
    } catch (e) {
      setLoadError(String(e));
      setProjects([]);
    }
  }, [userId, token, profileSlug, value, onChange]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (value) localStorage.setItem(STORAGE_KEY, value);
  }, [value]);

  useEffect(() => {
    if (!open) return;
    const handlePointerDown = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("mousedown", handlePointerDown);
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("mousedown", handlePointerDown);
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [open]);

  const current = projects.find((p) => p.slug === value);
  const currentLabel = current ? current.display_name : value || "default";
  const currentDesc = current?.description || (current?.slug !== currentLabel ? current?.slug : "");

  const filteredProjects = projects.filter((p) => {
    if (!search.trim()) return true;
    const q = search.toLowerCase();
    return (
      p.display_name.toLowerCase().includes(q) ||
      p.slug.toLowerCase().includes(q) ||
      (p.description && p.description.toLowerCase().includes(q))
    );
  });

  const isHero = variant === "hero";

  return (
    <div ref={containerRef} className={cn("relative w-full", open ? "z-50" : "z-10", className)}>
      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        className={cn(
          "group flex w-full items-center justify-between gap-3 rounded-2xl border transition-all duration-200 text-left backdrop-blur-xl cursor-pointer active:scale-[0.99]",
          isHero
            ? "p-3.5 bg-card/80 dark:bg-card/40 border-black/[0.08] dark:border-white/[0.08] shadow-sm hover:border-primary/40 hover:bg-card hover:shadow-md"
            : "p-2 px-3 bg-card/80 dark:bg-card/40 border-black/[0.08] dark:border-white/[0.08] shadow-2xs hover:border-primary/40 hover:bg-card",
          open && "border-primary ring-2 ring-primary/20 bg-card shadow-md"
        )}
        aria-expanded={open}
        aria-haspopup="listbox"
        aria-label={t("memory_project.label")}
      >
        <div className="flex min-w-0 flex-1 items-center gap-3">
          {/* Prominent Database Icon Container */}
          <div
            className={cn(
              "flex shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-rose-500/20 to-red-600/20 text-rose-500 dark:text-rose-400 border border-rose-500/30 group-hover:scale-105 transition-transform shadow-xs",
              isHero ? "size-10" : "size-7"
            )}
          >
            <Database size={isHero ? 18 : 14} aria-hidden />
          </div>

          <div className="min-w-0 flex-1 flex flex-col">
            <div className="flex items-center gap-1.5 mb-0.5">
              <span className="text-[9px] font-bold uppercase tracking-wider text-muted-foreground leading-none">
                {t("memory_project.label") || "PROGETTO ATTIVO"}
              </span>
              <span className="size-1.5 rounded-full bg-emerald-500 animate-pulse shrink-0" />
            </div>
            <span
              className={cn(
                "truncate font-bold text-foreground group-hover:text-primary transition-colors",
                isHero ? "text-sm" : "text-xs"
              )}
            >
              {currentLabel}
            </span>
            {isHero && currentDesc && (
              <span className="truncate text-[10px] text-muted-foreground mt-0.5">
                {currentDesc}
              </span>
            )}
          </div>
        </div>

        <div className="flex items-center gap-1.5 shrink-0">
          <span className="rounded-full bg-muted/60 text-muted-foreground px-2 py-0.5 text-[10px] font-semibold">
            {projects.length} {projects.length === 1 ? "progetto" : "progetti"}
          </span>
          <ChevronDown
            size={16}
            className={cn(
              "shrink-0 text-muted-foreground transition-transform duration-200 group-hover:text-foreground",
              open && "rotate-180 text-primary"
            )}
            aria-hidden
          />
        </div>
      </button>

      {/* Custom Dropdown Popover */}
      {open && (
        <div
          className="absolute left-0 right-0 top-full z-[100] mt-1.5 max-h-80 overflow-hidden rounded-2xl border border-border bg-popover text-popover-foreground dark:bg-zinc-900 p-2.5 shadow-2xl animate-in fade-in-0 zoom-in-95 duration-150"
          role="listbox"
        >
          <div className="flex items-center justify-between border-b border-border/40 pb-2 px-1">
            <span className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground">
              Seleziona Progetto Memoria
            </span>
            <span className="text-[11px] text-muted-foreground font-medium">
              {filteredProjects.length} {filteredProjects.length === 1 ? "progetto" : "progetti"}
            </span>
          </div>

          <div className="relative my-2">
            <Search
              size={13}
              className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground"
            />
            <input
              type="text"
              className="w-full rounded-xl border border-input bg-muted/40 py-1.5 pl-8 pr-7 text-xs text-foreground placeholder:text-muted-foreground focus:border-primary focus:bg-background focus:outline-none focus:ring-2 focus:ring-primary/20 transition-all"
              placeholder="Cerca progetto..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              autoFocus
            />
            {search && (
              <button
                type="button"
                onClick={() => setSearch("")}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground text-xs p-0.5 rounded-full cursor-pointer"
              >
                ✕
              </button>
            )}
          </div>

          <div className="max-h-56 overflow-y-auto space-y-1 custom-scrollbar pr-0.5">
            {filteredProjects.length === 0 ? (
              <div className="px-3 py-4 text-center text-xs text-muted-foreground">
                {projects.length === 0 ? "Nessun progetto disponibile" : "Nessun risultato trovato"}
              </div>
            ) : (
              filteredProjects.map((p) => {
                const isSelected = p.slug === value;
                return (
                  <button
                    key={p.id}
                    type="button"
                    onClick={() => {
                      onChange(p.slug);
                      setOpen(false);
                      setSearch("");
                    }}
                    className={cn(
                      "flex w-full items-center justify-between gap-2.5 rounded-xl border p-2 text-left text-xs transition cursor-pointer",
                      isSelected
                        ? "border-rose-500/40 bg-rose-500/10 text-rose-600 dark:text-rose-400 font-bold shadow-xs"
                        : "border-transparent hover:bg-muted/60 text-foreground"
                    )}
                    role="option"
                    aria-selected={isSelected}
                  >
                    <div className="flex min-w-0 items-center gap-2.5">
                      <div
                        className={cn(
                          "flex size-7 shrink-0 items-center justify-center rounded-lg text-xs font-bold transition-colors",
                          isSelected
                            ? "bg-rose-500/20 text-rose-600 dark:text-rose-400"
                            : "bg-muted text-muted-foreground"
                        )}
                      >
                        <Database size={13} />
                      </div>
                      <div className="min-w-0 flex-1">
                        <p className="truncate font-semibold leading-tight text-foreground">{p.display_name}</p>
                        <p className="font-mono text-[10px] text-muted-foreground truncate mt-0.5">
                          {p.slug}
                        </p>
                      </div>
                    </div>
                    {isSelected && (
                      <Check size={14} className="shrink-0 text-rose-600 dark:text-rose-400" aria-hidden />
                    )}
                  </button>
                );
              })
            )}
          </div>
        </div>
      )}

      {loadError && (
        <p className="mt-1 text-[11px] text-destructive truncate px-1" title={loadError}>
          {loadError}
        </p>
      )}
    </div>
  );
}

export function readStoredSqlProject(): string {
  if (typeof window === "undefined") return "default";
  return localStorage.getItem(STORAGE_KEY) || "default";
}
