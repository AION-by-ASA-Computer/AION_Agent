"use client";

import { useEffect, useMemo, useRef, useState, useSyncExternalStore, type ElementType } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowRight, Search } from "lucide-react";
import { cn } from "@/lib/cn";
import { ADMIN_NAV } from "@/lib/admin-nav";
import { useT } from "@/lib/i18n/use-t";

type Entry = { id: string; href: string; label: string; group: string; haystack: string; icon: ElementType };

const QUICK = [
  { id: "quick_models", href: "/settings" },
  { id: "quick_mcp", href: "/hub" },
  { id: "quick_profiles", href: "/profiles" },
  { id: "quick_users", href: "/users" },
  { id: "quick_api_keys", href: "/api-keys" },
];

const noopSubscribe = () => () => {};

function fold(s: string): string {
  return s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
}

export function CommandBar() {
  const t = useT();
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const isMac = useSyncExternalStore(
    noopSubscribe,
    () => /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent),
    () => true,
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        inputRef.current?.focus();
        inputRef.current?.select();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const entries: Entry[] = useMemo(
    () =>
      ADMIN_NAV.flatMap((g) =>
        g.items
          .filter((i) => i.href !== "/")
          .map((i) => {
            const label = t(i.labelKey);
            const keywords = t(`admin_dashboard.command.keywords.${i.id}`);
            return {
              id: i.id,
              href: i.href,
              label,
              group: g.labelKey ? t(g.labelKey) : "",
              haystack: fold(`${label} ${keywords} ${i.href}`),
              icon: i.icon,
            };
          }),
      ),
    [t],
  );

  const results = useMemo(() => {
    const q = fold(query.trim());
    if (!q) return [];
    const words = q.split(/\s+/);
    return entries
      .filter((e) => words.every((w) => e.haystack.includes(w)))
      .sort((a, b) => Number(!fold(a.label).startsWith(words[0])) - Number(!fold(b.label).startsWith(words[0])))
      .slice(0, 7);
  }, [entries, query]);

  const go = (href: string) => {
    setOpen(false);
    setQuery("");
    router.push(href);
  };

  const showList = open && query.trim().length > 0;

  return (
    <div className="relative">
      <div
        className={cn(
          "flex items-center gap-3 rounded-2xl border bg-card px-4 transition-[border-color,box-shadow] duration-200",
          showList ? "border-foreground/25" : "border-border/80 hover:border-foreground/20",
          "focus-within:border-foreground/30 focus-within:shadow-[0_8px_24px_-14px_rgba(0,0,0,0.18)] dark:focus-within:shadow-[0_8px_28px_-12px_rgba(0,0,0,0.6)]",
        )}
      >
        <Search className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
        <input
          ref={inputRef}
          type="text"
          role="combobox"
          aria-expanded={showList}
          aria-controls="admin-command-list"
          aria-activedescendant={showList && results[active] ? `cmd-${results[active].id}` : undefined}
          aria-autocomplete="list"
          aria-label={t("admin_dashboard.command.label")}
          placeholder={t("admin_dashboard.command.placeholder")}
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setActive(0);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 120)}
          onKeyDown={(e) => {
            if (!showList) return;
            if (e.key === "ArrowDown") {
              e.preventDefault();
              setActive((a) => Math.min(a + 1, results.length - 1));
            } else if (e.key === "ArrowUp") {
              e.preventDefault();
              setActive((a) => Math.max(a - 1, 0));
            } else if (e.key === "Enter" && results[active]) {
              e.preventDefault();
              go(results[active].href);
            } else if (e.key === "Escape") {
              setOpen(false);
            }
          }}
          className="h-12 min-w-0 flex-1 bg-transparent text-[15px] text-foreground outline-none placeholder:text-muted-foreground/80"
        />
        <kbd className="hidden shrink-0 rounded-md border border-border px-1.5 py-0.5 font-sans text-[11px] font-medium text-muted-foreground sm:inline-block">
          {isMac ? "⌘ K" : "Ctrl K"}
        </kbd>
      </div>

      {showList && (
        <ul
          id="admin-command-list"
          role="listbox"
          aria-label={t("admin_dashboard.command.results")}
          className="absolute inset-x-0 top-[calc(100%+6px)] z-30 overflow-hidden rounded-2xl border border-border bg-popover p-1.5 shadow-[0_16px_36px_-14px_rgba(0,0,0,0.22)] dark:shadow-[0_16px_40px_-12px_rgba(0,0,0,0.65)]"
        >
          {results.length === 0 ? (
            <li className="px-3 py-3 text-sm text-muted-foreground">{t("admin_dashboard.command.empty")}</li>
          ) : (
            results.map((r, i) => (
              <li
                key={r.id}
                id={`cmd-${r.id}`}
                role="option"
                aria-selected={i === active}
                onMouseEnter={() => setActive(i)}
                onMouseDown={(e) => {
                  e.preventDefault();
                  go(r.href);
                }}
                className={cn(
                  "flex cursor-pointer items-center gap-3 rounded-xl px-3 py-2.5 text-sm",
                  i === active ? "bg-secondary text-foreground" : "text-muted-foreground",
                )}
              >
                <r.icon className={cn("h-4 w-4 shrink-0", i === active && "text-primary")} aria-hidden />
                <span className="min-w-0 flex-1 truncate font-medium">{r.label}</span>
                <span className="shrink-0 text-xs text-muted-foreground">{r.group}</span>
                {i === active && <ArrowRight className="h-3.5 w-3.5 shrink-0" aria-hidden />}
              </li>
            ))
          )}
        </ul>
      )}

      <div className="mt-3 flex flex-wrap gap-2">
        {QUICK.map((q) => (
          <Link
            key={q.id}
            href={q.href}
            className="focus-ring rounded-full border border-border/80 px-3 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:border-foreground/25 hover:bg-secondary hover:text-foreground"
          >
            {t(`admin_dashboard.command.${q.id}`)}
          </Link>
        ))}
      </div>
    </div>
  );
}
