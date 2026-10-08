"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Check, ChevronDown, Search } from "lucide-react";
import { cn } from "@/lib/cn";

export type ProfileItem = {
  name: string;
  slug: string;
  description?: string;
};

export function ProfileSelectorDropdown({
  profiles,
  value,
  onChange,
  label = "Profilo Agente AI",
  className,
}: {
  profiles: ProfileItem[];
  value: string;
  onChange: (slug: string) => void;
  label?: string;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const dropdownRef = useRef<HTMLDivElement>(null);

  const selectedProfile = useMemo(
    () => profiles.find((p) => p.slug === value || p.name === value),
    [profiles, value],
  );

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    if (open) {
      document.addEventListener("mousedown", handleClickOutside);
      return () => document.removeEventListener("mousedown", handleClickOutside);
    }
  }, [open]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return profiles;
    return profiles.filter(
      (p) =>
        p.name.toLowerCase().includes(q) ||
        (p.description && p.description.toLowerCase().includes(q)) ||
        p.slug.toLowerCase().includes(q),
    );
  }, [profiles, search]);

  return (
    <div ref={dropdownRef} className={cn("relative", open && "z-40", className)}>
      {label ? (
        <label className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-muted-foreground select-none">
          {label}
        </label>
      ) : null}
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={cn(
          "flex w-full items-center justify-between gap-3 rounded-2xl border border-input bg-background/80 px-3.5 py-2.5 text-left transition hover:border-primary/50 focus:border-primary focus:ring-2 focus:ring-primary/20 outline-none cursor-pointer",
          open && "border-primary ring-2 ring-primary/20",
        )}
      >
        <div className="flex items-center gap-3 min-w-0">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary font-bold text-xs">
            {selectedProfile ? selectedProfile.name.charAt(0).toUpperCase() : "A"}
          </div>
          <div className="min-w-0 flex-1">
            <div className="text-sm font-semibold text-foreground truncate">
              {selectedProfile?.name || value || "Seleziona profilo…"}
            </div>
            {selectedProfile?.description ? (
              <div className="text-xs text-muted-foreground truncate">
                {selectedProfile.description}
              </div>
            ) : null}
          </div>
        </div>
        <ChevronDown
          className={cn(
            "h-4 w-4 text-muted-foreground transition-transform duration-200 shrink-0",
            open && "rotate-180",
          )}
        />
      </button>

      {open && (
        <div className="absolute top-full left-0 z-[60] mt-1.5 w-full rounded-2xl border border-border bg-popover text-popover-foreground p-2.5 shadow-2xl ring-1 ring-border/50 animate-in fade-in-0 zoom-in-95 duration-150">
          <div className="flex items-center justify-between border-b border-border/40 pb-2 px-1">
            <span className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground">
              Seleziona Profilo
            </span>
            <span className="text-[11px] text-muted-foreground font-medium">
              {filtered.length} {filtered.length === 1 ? "profilo" : "profili"}
            </span>
          </div>

          <div className="relative my-2">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground pointer-events-none" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Cerca profilo o abilità…"
              className="w-full rounded-xl border border-input bg-muted/40 pl-8 pr-7 py-1.5 text-xs text-foreground placeholder:text-muted-foreground focus:border-primary focus:bg-background focus:outline-none focus:ring-2 focus:ring-primary/20 transition-all"
              autoFocus
            />
            {search && (
              <button
                type="button"
                onClick={() => setSearch("")}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground text-xs p-0.5 rounded-full"
              >
                ✕
              </button>
            )}
          </div>

          <div className="max-h-56 overflow-y-auto space-y-1 custom-scrollbar p-0.5">
            {filtered.map((p) => {
              const isSelected = p.slug === value || p.name === value;
              return (
                <button
                  key={p.slug}
                  type="button"
                  onClick={() => {
                    onChange(p.slug);
                    setOpen(false);
                    setSearch("");
                  }}
                  className={cn(
                    "flex w-full items-center justify-between gap-2.5 rounded-xl border p-2 text-left transition cursor-pointer",
                    isSelected
                      ? "border-primary/50 bg-primary/10 text-primary shadow-xs font-semibold"
                      : "border-transparent hover:bg-muted/60 text-foreground",
                  )}
                >
                  <div className="flex items-center gap-2.5 min-w-0">
                    <div
                      className={cn(
                        "flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-xs font-bold transition-colors",
                        isSelected
                          ? "bg-primary text-primary-foreground"
                          : "bg-muted text-muted-foreground",
                      )}
                    >
                      {p.name.charAt(0).toUpperCase()}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="text-xs font-semibold text-foreground truncate">{p.name}</div>
                      {p.description ? (
                        <div className="text-[11px] text-muted-foreground truncate max-w-sm">
                          {p.description}
                        </div>
                      ) : null}
                    </div>
                  </div>
                  {isSelected && <Check className="h-4 w-4 shrink-0 text-primary ml-2" />}
                </button>
              );
            })}
            {filtered.length === 0 && (
              <div className="py-4 text-center text-xs text-muted-foreground">
                Nessun profilo trovato
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
