"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Check, ChevronDown, ChevronRight, Database, Search } from "lucide-react";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";
import { fetchSqlProjects, type SqlProject } from "@/lib/api/query-memory";

type Props = {
  userId: string;
  token?: string | null;
  profileSlug?: string;
  projectSlug: string;
  onChangeProject?: (slug: string) => void;
  onOpenPanel: () => void;
  className?: string;
};

export function ProjectMemoryChip({
  userId,
  token,
  profileSlug,
  projectSlug,
  onChangeProject,
  onOpenPanel,
  className,
}: Props) {
  const t = useT();
  const [projects, setProjects] = useState<SqlProject[]>([]);
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const menuRef = useRef<HTMLDivElement>(null);

  const loadProjects = useCallback(async () => {
    try {
      const list = await fetchSqlProjects(userId, token, profileSlug);
      setProjects(list);
    } catch {
      setProjects([]);
    }
  }, [userId, token, profileSlug]);

  useEffect(() => {
    void loadProjects();
  }, [loadProjects]);

  useEffect(() => {
    if (!open) return;
    const handleClickOutside = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", handleClickOutside);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [open]);

  const currentProject = projects.find((p) => p.slug === projectSlug);
  const label = currentProject?.display_name ?? projectSlug;

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return projects;
    return projects.filter(
      (p) =>
        p.display_name.toLowerCase().includes(q) ||
        p.slug.toLowerCase().includes(q) ||
        (p.description && p.description.toLowerCase().includes(q)),
    );
  }, [projects, search]);

  if (!onChangeProject) {
    return (
      <button
        type="button"
        title={t("memory_dock.open_panel")}
        onClick={onOpenPanel}
        className={cn(
          "focus-ring inline-flex h-8 max-w-[9rem] sm:max-w-[13rem] shrink items-center gap-1.5 rounded-full border border-black/[0.08] dark:border-white/[0.08] bg-card/70 dark:bg-card/40 px-3 text-[0.786em] font-medium text-foreground shadow-2xs backdrop-blur-xl transition-all duration-200 hover:scale-[1.02] hover:bg-card/95 dark:hover:bg-card/70 active:scale-[0.98]",
          className,
        )}
      >
        <Database size={12} className="shrink-0 text-rose-500 dark:text-rose-400" aria-hidden />
        <span className="truncate">{label}</span>
        <ChevronRight size={10} className="shrink-0 opacity-60" aria-hidden />
      </button>
    );
  }

  return (
    <div ref={menuRef} className="relative shrink-0">
      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        className={cn(
          "focus-ring inline-flex h-8 max-w-[9rem] sm:max-w-[13rem] items-center gap-1.5 rounded-full border px-2.5 text-[0.786em] font-medium shadow-2xs backdrop-blur-md transition-all duration-200 cursor-pointer",
          open
            ? "border-rose-500/40 bg-rose-500/10 text-rose-600 dark:text-rose-400 shadow-xs"
            : "border-black/[0.08] bg-card/70 text-muted-foreground hover:bg-card/95 hover:text-foreground dark:border-white/[0.12] dark:bg-card/80 dark:hover:bg-card/95",
          className,
        )}
        title={label}
        aria-expanded={open}
        aria-haspopup="listbox"
      >
        <Database size={12} className="shrink-0 text-rose-500 dark:text-rose-400" aria-hidden />
        <span className="truncate">{label}</span>
        <ChevronDown
          size={10}
          className={cn("shrink-0 opacity-60 transition-transform duration-200", open && "rotate-180")}
          aria-hidden
        />
      </button>

      {open && (
        <div
          className="absolute bottom-full right-0 z-50 mb-2 w-[min(100vw-2rem,22rem)] rounded-2xl border border-border bg-popover text-popover-foreground p-2.5 shadow-2xl ring-1 ring-border/50 animate-in fade-in-0 zoom-in-95 slide-in-from-bottom-2 duration-200"
          role="listbox"
        >
          <div className="flex items-center justify-between border-b border-border/40 pb-2 px-1">
            <span className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground">
              Progetti Memoria
            </span>
            <span className="text-[11px] text-muted-foreground font-medium">
              {filtered.length} {filtered.length === 1 ? "progetto" : "progetti"}
            </span>
          </div>

          <div className="relative my-2">
            <Search
              size={13}
              className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground"
            />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Cerca progetto..."
              className="w-full rounded-xl border border-input bg-muted/40 py-1.5 pl-8 pr-7 text-xs text-foreground placeholder:text-muted-foreground focus:border-primary focus:bg-background focus:outline-none focus:ring-2 focus:ring-primary/20 transition-all"
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
            {filtered.length === 0 ? (
              <div className="py-4 text-center text-xs text-muted-foreground">
                Nessun progetto trovato
              </div>
            ) : (
              filtered.map((p) => {
                const isSelected = p.slug === projectSlug;
                return (
                  <button
                    key={p.id}
                    type="button"
                    onClick={() => {
                      onChangeProject(p.slug);
                      setOpen(false);
                      setSearch("");
                    }}
                    className={cn(
                      "flex w-full items-center justify-between gap-2.5 rounded-xl border p-2 text-left text-xs transition cursor-pointer",
                      isSelected
                        ? "border-rose-500/40 bg-rose-500/10 text-rose-600 dark:text-rose-400 font-bold shadow-xs"
                        : "border-transparent hover:bg-muted/60 text-foreground",
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
                            : "bg-muted text-muted-foreground",
                        )}
                      >
                        <Database size={13} />
                      </div>
                      <div className="min-w-0 flex-1">
                        <p className="truncate font-semibold leading-tight text-foreground">
                          {p.display_name}
                        </p>
                        <p className="font-mono text-[10px] text-muted-foreground truncate mt-0.5">
                          {p.slug}
                        </p>
                      </div>
                    </div>
                    {isSelected && (
                      <Check size={14} className="shrink-0 text-rose-600 dark:text-rose-400" />
                    )}
                  </button>
                );
              })
            )}
          </div>

          <div className="mt-1.5 pt-1.5 border-t border-border/40">
            <button
              type="button"
              onClick={() => {
                setOpen(false);
                onOpenPanel();
              }}
              className="flex w-full items-center justify-between rounded-xl px-2.5 py-1.5 text-xs font-medium text-muted-foreground hover:bg-muted/60 hover:text-foreground transition cursor-pointer"
            >
              <span>Apri pannello memoria</span>
              <ChevronRight size={13} />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
