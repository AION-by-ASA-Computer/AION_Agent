"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, ArrowDown, ArrowUp, Calendar, Check, ChevronDown, Filter, MessageSquare, ThumbsDown, ThumbsUp, X } from "lucide-react";
import { cn } from "@/lib/cn";
import { getLocale } from "@/lib/i18n/i18n-store";
import { shortWhen, fullWhen, toMs } from "./format";
import type { Conversation } from "./types";

type T = (key: string, vars?: Record<string, string | number>) => string;
const k = "admin_conversations.list";

export type SortKey = "updated" | "messages" | "flags";
export type Sort = { key: SortKey; dir: "asc" | "desc" };

export const flagTotal = (c: Conversation) =>
  (c.disliked_count ?? 0) + (c.error_count ?? 0) + (c.liked_count ?? 0) + (c.comment_count ?? 0);

/** Values of the feedback column filter; "" means no filter. */
export const FEEDBACK_VALUES = ["disliked", "liked", "comment", "errors"] as const;
export type FeedbackFilter = (typeof FEEDBACK_VALUES)[number];

export function matchesFeedback(c: Conversation, f: string) {
  switch (f) {
    case "disliked": return (c.disliked_count ?? 0) > 0;
    case "liked": return (c.liked_count ?? 0) > 0;
    case "comment": return (c.comment_count ?? 0) > 0;
    case "errors": return (c.error_count ?? 0) > 0;
    default: return true;
  }
}

export type FilterCol = "conversation" | "user" | "profile" | "feedback";
export type Filters = Record<FilterCol, string>;
export type DateRange = { from: string; to: string };
export type FilterOption = { value: string; label: string };

export const GRID = "md:grid-cols-[minmax(0,2.1fr)_minmax(0,1.4fr)_minmax(0,1fr)_4.5rem_6.5rem_11rem]";

function SortHead({ id, sort, onSort, label, align = "left" }: { id: SortKey; sort: Sort; onSort: (k: SortKey) => void; label: string; align?: "left" | "right" }) {
  const active = sort.key === id;
  const Icon = sort.dir === "asc" ? ArrowUp : ArrowDown;
  return (
    <button
      type="button"
      onClick={() => onSort(id)}
      aria-label={label}
      aria-pressed={active}
      className={cn(
        "focus-ring -mx-2 inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs font-medium transition-colors hover:text-foreground",
        align === "right" && "justify-end",
        active ? "text-foreground" : "text-muted-foreground",
      )}
    >
      {label}
      <Icon className={cn("h-3 w-3", !active && "opacity-0")} aria-hidden />
    </button>
  );
}

/** Header that opens a small filter popover for its own column: free text for titles, a pick-list for users and profiles. */
function FilterHead({
  label,
  value,
  onChange,
  options,
  typeable,
  alignRight,
  fill,
  t,
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
  t: T;
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
          aria-label={t(`${k}.filter_aria`, { col: label })}
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
          <button type="button" onClick={() => onChange("")} aria-label={t(`${k}.filter_clear`)} className="focus-ring mr-1 shrink-0 rounded-md p-1 text-muted-foreground hover:bg-background hover:text-foreground">
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
                  placeholder={t(`${k}.filter_search`)}
                  aria-label={t(`${k}.filter_search`)}
                  className="focus-ring mb-1.5 w-full rounded-xl border border-border bg-background px-3 py-2 text-sm"
                />
              )}
              <ul className="max-h-64 overflow-y-auto">
                {[...(typeable ? [] : [{ value: "", label: t(`${k}.filter_all`) }]), ...shown].map((o) => (
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
                placeholder={t(`${k}.filter_search`)}
                aria-label={t(`${k}.filter_search`)}
                className="focus-ring w-full rounded-xl border border-border bg-background py-2 pl-3 pr-9 text-sm"
              />
              {value && (
                <button type="button" onClick={() => onChange("")} aria-label={t(`${k}.filter_clear`)} className="focus-ring absolute right-1.5 top-1/2 -translate-y-1/2 rounded-lg p-1.5 text-muted-foreground hover:bg-secondary">
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

const pad = (n: number) => String(n).padStart(2, "0");
const ymd = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const niceDay = (v: string) => (v ? new Date(`${v}T00:00:00`).toLocaleDateString(getLocale(), { day: "numeric", month: "short", year: "numeric" }) : "");

export function describeRange(r: DateRange, t: T) {
  if (r.from && r.to) return r.from === r.to ? niceDay(r.from) : `${niceDay(r.from)} – ${niceDay(r.to)}`;
  if (r.from) return t(`${k}.date_since`, { d: niceDay(r.from) });
  if (r.to) return t(`${k}.date_until`, { d: niceDay(r.to) });
  return "";
}

/** Toolbar button: presets, an exact day, or a from/to period. */
export function DateFilter({ value, onChange, now, t }: { value: DateRange; onChange: (r: DateRange) => void; now: number; t: T }) {
  const [open, setOpen] = useState(false);
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

  const active = !!(value.from || value.to);
  const summary = describeRange(value, t);
  const preset = (days: number) => {
    const today = new Date(now);
    const from = new Date(now);
    from.setDate(from.getDate() - (days - 1));
    onChange({ from: ymd(from), to: days === 1 ? ymd(today) : "" });
  };
  const chip = "focus-ring rounded-lg border border-border px-2.5 py-1 text-xs font-medium hover:bg-secondary";
  const field = "focus-ring w-full rounded-xl border border-border bg-background px-3 py-2 text-sm";

  return (
    <div ref={box} className="relative">
      <div className={cn("inline-flex h-9 items-center rounded-xl border", active ? "border-foreground/30 bg-secondary" : "border-border bg-card hover:bg-secondary")}>
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-haspopup="dialog"
          aria-expanded={open}
          className="focus-ring inline-flex h-full items-center gap-2 rounded-xl px-3 text-sm font-medium"
        >
          <Calendar className="h-3.5 w-3.5 text-muted-foreground" aria-hidden />
          <span className="max-w-[16rem] truncate">{active ? summary : t(`${k}.date_label`)}</span>
          {!active && <ChevronDown className="h-3.5 w-3.5 opacity-60" aria-hidden />}
        </button>
        {active && (
          <button type="button" onClick={() => onChange({ from: "", to: "" })} aria-label={t(`${k}.filter_clear`)} className="focus-ring mr-1 rounded-lg p-1.5 text-muted-foreground hover:bg-background hover:text-foreground">
            <X className="h-3.5 w-3.5" aria-hidden />
          </button>
        )}
      </div>
      {open && (
        <div role="dialog" aria-label={t(`${k}.date_label`)} className="absolute left-0 top-full z-20 mt-1.5 w-72 rounded-2xl border border-border bg-popover p-3 text-left shadow-xl animate-in fade-in zoom-in-95 duration-100">
          <div className="flex flex-wrap gap-1.5">
            <button type="button" className={chip} onClick={() => preset(1)}>{t(`${k}.range_today`)}</button>
            <button type="button" className={chip} onClick={() => preset(7)}>{t(`${k}.range_7d`)}</button>
            <button type="button" className={chip} onClick={() => preset(30)}>{t(`${k}.range_30d`)}</button>
          </div>
          <div className="mt-3 grid grid-cols-2 gap-2">
            <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
              {t(`${k}.date_from`)}
              <input type="date" value={value.from} max={value.to || undefined} onChange={(e) => onChange({ ...value, from: e.target.value })} className={field} />
            </label>
            <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
              {t(`${k}.date_to`)}
              <input type="date" value={value.to} min={value.from || undefined} onChange={(e) => onChange({ ...value, to: e.target.value })} className={field} />
            </label>
          </div>
          <p className="mt-2 text-xs text-muted-foreground">{t(`${k}.date_hint`)}</p>
          {active && (
            <div className="mt-2 flex items-center justify-between gap-2 border-t border-border/60 pt-2">
              <span className="min-w-0 truncate text-sm font-medium">{summary}</span>
              <button type="button" className={cn(chip, "shrink-0")} onClick={() => onChange({ from: "", to: "" })}>{t(`${k}.filter_clear`)}</button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function ConversationList({
  rows,
  selectedId,
  sort,
  onSort,
  onOpen,
  filters,
  onFilter,
  userOptions,
  profileOptions,
  profileName,
  now,
  empty,
  t,
}: {
  rows: Conversation[];
  selectedId: string | null;
  sort: Sort;
  onSort: (k: SortKey) => void;
  onOpen: (id: string) => void;
  filters: Filters;
  onFilter: (col: FilterCol, value: string) => void;
  userOptions: FilterOption[];
  profileOptions: FilterOption[];
  profileName: (slug: string) => string;
  now: number;
  /** Shown under the headers when no row matches, so the column filters stay reachable. */
  empty?: React.ReactNode;
  t: T;
}) {
  const feedbackOptions = FEEDBACK_VALUES.map((v) => ({ value: v, label: t(`${k}.feedback_${v}`) }));
  return (
    <div className="rounded-3xl border border-border/70 bg-card">
      <div className={cn("hidden items-center gap-4 border-b border-border/60 px-5 py-2 md:grid", GRID)}>
        <FilterHead label={t(`${k}.col_conversation`)} value={filters.conversation} onChange={(v) => onFilter("conversation", v)} t={t} />
        <FilterHead label={t(`${k}.col_user`)} value={filters.user} onChange={(v) => onFilter("user", v)} options={userOptions} typeable t={t} />
        <FilterHead label={t(`${k}.col_profile`)} value={filters.profile} onChange={(v) => onFilter("profile", v)} options={profileOptions} t={t} />
        <div className="text-right">
          <SortHead id="messages" sort={sort} onSort={onSort} label={t(`${k}.col_messages`)} align="right" />
        </div>
        <div className="text-right">
          <SortHead id="updated" sort={sort} onSort={onSort} label={t(`${k}.col_activity`)} align="right" />
        </div>
        <div className="flex items-center justify-end gap-1">
          <div className="min-w-0 flex-1"><FilterHead label={t(`${k}.col_feedback`)} value={filters.feedback} onChange={(v) => onFilter("feedback", v)} options={feedbackOptions} alignRight fill t={t} /></div>
          <button
            type="button"
            onClick={() => onSort("flags")}
            aria-label={t(`${k}.sort_feedback`)}
            aria-pressed={sort.key === "flags"}
            className={cn("focus-ring ml-1 shrink-0 rounded-md p-1 transition-colors hover:text-foreground", sort.key === "flags" ? "text-foreground" : "text-muted-foreground/60")}
          >
            {sort.key === "flags" && sort.dir === "asc" ? <ArrowUp className="h-3 w-3" aria-hidden /> : <ArrowDown className="h-3 w-3" aria-hidden />}
          </button>
        </div>
      </div>

      {empty}
      <ul className="overflow-hidden rounded-b-3xl">
        {rows.map((c) => {
          const active = c.id === selectedId;
          const down = c.disliked_count ?? 0;
          const errs = c.error_count ?? 0;
          const ms = toMs(c.updated_at);
          const up = c.liked_count ?? 0;
          const notes = c.comment_count ?? 0;
          const flags = (
            <>
              {up > 0 && (
                <span className="inline-flex items-center gap-1 font-medium text-success" title={t("admin_conversations.detail.liked")}>
                  <ThumbsUp className="h-3.5 w-3.5" aria-hidden />
                  <span className="tabular-nums">{up}</span>
                </span>
              )}
              {down > 0 && (
                <span className="inline-flex items-center gap-1 font-medium text-destructive" title={t("admin_conversations.detail.disliked")}>
                  <ThumbsDown className="h-3.5 w-3.5" aria-hidden />
                  <span className="tabular-nums">{down}</span>
                </span>
              )}
              {notes > 0 && (
                <span className="inline-flex items-center gap-1 font-medium text-muted-foreground" title={t(`${k}.feedback_comment`)}>
                  <MessageSquare className="h-3.5 w-3.5" aria-hidden />
                  <span className="tabular-nums">{notes}</span>
                </span>
              )}
              {errs > 0 && (
                <span className="inline-flex items-center gap-1 font-medium text-destructive" title={t("admin_conversations.detail.tool_errors", { n: errs })}>
                  <AlertTriangle className="h-3.5 w-3.5" aria-hidden />
                  <span className="tabular-nums">{errs}</span>
                </span>
              )}
            </>
          );
          return (
            <li key={c.id} className="border-b border-border/40 last:border-b-0">
              <button
                type="button"
                data-conv-id={c.id}
                aria-current={active ? "true" : undefined}
                onClick={() => onOpen(c.id)}
                className={cn(
                  "focus-ring grid w-full grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 gap-y-0.5 px-5 py-3 text-left transition-colors",
                  GRID,
                  active ? "bg-secondary" : "hover:bg-secondary/60",
                )}
              >
                <span className="min-w-0 line-clamp-2 break-words text-sm font-medium">{c.title || t(`${k}.untitled`)}</span>

                <span className="flex items-center justify-end gap-2.5 text-xs md:order-last md:w-full">{flags}</span>

                <span className="col-span-2 flex min-w-0 items-center gap-1.5 text-xs text-muted-foreground md:hidden">
                  <span className="truncate">
                    {c.user_id}
                    {c.profile_slug ? ` · ${profileName(c.profile_slug)}` : ""}
                  </span>
                  <span className="shrink-0">· {t(`${k}.messages`, { n: c.message_count })}</span>
                  <span className="shrink-0 tabular-nums">· {shortWhen(ms, now)}</span>
                </span>

                <span className="hidden min-w-0 flex-col md:flex">
                  <span className="truncate text-sm">{c.user_id}</span>
                  {c.tenant_id && <span className="truncate text-xs text-muted-foreground">{c.tenant_id}</span>}
                </span>
                <span className="hidden truncate text-sm text-muted-foreground md:block">{c.profile_slug ? profileName(c.profile_slug) : "—"}</span>
                <span className="hidden text-right text-sm tabular-nums text-muted-foreground md:block">{c.message_count}</span>
                <span className="hidden text-right text-sm tabular-nums text-muted-foreground md:block" title={fullWhen(ms)}>
                  {shortWhen(ms, now)}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

