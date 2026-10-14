"use client";

import { useEffect, useRef, useState } from "react";
import { AlertTriangle, ArrowDown, ArrowUp, Calendar, ChevronDown, ChevronRight, MessageSquare, MessageSquareQuote, ThumbsDown, ThumbsUp, X } from "lucide-react";
import { cn } from "@/lib/cn";
import { getLocale } from "@/lib/i18n/i18n-store";
import { shortWhen, fullWhen, toMs } from "./format";
import type { Conversation, ConversationFamily } from "./types";

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
import { ColumnFilter, type FilterOption } from "@/components/ui/ColumnFilter";
export type { FilterOption };

/** A list entry: a top-level conversation and the side threads currently shown under it. */
export type FamilyRow = ConversationFamily & {
  /** Threads that pass the filters (all of them when the parent itself matches). */
  shownThreads: Conversation[];
  expanded: boolean;
  /** The parent is only context: it is listed because one of its threads matched. */
  dimmed: boolean;
  /** Latest activity across the parent and its threads, used for sorting. */
  latest: number;
  flagSum: number;
  threadAttention: boolean;
};

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

function FilterHead(props: Omit<React.ComponentProps<typeof ColumnFilter>, "labels"> & { t: T }) {
  const { t, ...rest } = props;
  const labels = {
    aria: (col: string) => t(`${k}.filter_aria`, { col }),
    clear: t(`${k}.filter_clear`),
    search: t(`${k}.filter_search`),
    all: t(`${k}.filter_all`),
  };
  return <ColumnFilter {...rest} labels={labels} />;
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

function Flags({ c, t }: { c: Conversation; t: T }) {
  const down = c.disliked_count ?? 0;
  const errs = c.error_count ?? 0;
  const up = c.liked_count ?? 0;
  const notes = c.comment_count ?? 0;
  return (
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
}

/** The highlighted passage a side thread was opened on, as a one-line quote. */
function Quote({ text }: { text: string }) {
  return (
    <span className="flex min-w-0 items-center gap-1.5 text-xs text-muted-foreground">
      <MessageSquareQuote className="h-3.5 w-3.5 shrink-0 text-primary/80" aria-hidden />
      <span className="truncate">“{text}”</span>
    </span>
  );
}

function Row({
  c,
  active,
  child,
  dimmed,
  threadCount = 0,
  threadAttention,
  onOpen,
  profileName,
  now,
  t,
}: {
  c: Conversation;
  active: boolean;
  /** Rendered as a side thread nested under its parent. */
  child?: boolean;
  dimmed?: boolean;
  threadCount?: number;
  threadAttention?: boolean;
  onOpen: (id: string) => void;
  profileName: (slug: string) => string;
  now: number;
  t: T;
}) {
  const ms = toMs(c.updated_at);
  const isThread = !!c.parent_conversation_id;
  return (
    <button
      type="button"
      data-conv-id={c.id}
      aria-current={active ? "true" : undefined}
      onClick={() => onOpen(c.id)}
      className={cn(
        "focus-ring grid w-full grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 gap-y-0.5 py-3 pl-11 pr-5 text-left transition-colors",
        GRID,
        child && "py-2.5",
        active ? "bg-secondary" : "hover:bg-secondary/60",
      )}
    >
      <span className={cn("flex min-w-0 flex-col gap-1", dimmed && "opacity-60")}>
        <span className="flex min-w-0 items-center gap-2">
          <span className={cn("min-w-0 line-clamp-2 break-words font-medium", child ? "text-[13px]" : "text-sm")}>{c.title || t(`${k}.untitled`)}</span>
          {isThread && !child && (
            <span className="shrink-0 rounded-md bg-primary/10 px-1.5 py-0.5 text-[11px] font-medium text-primary">{t(`${k}.thread_badge`)}</span>
          )}
          {threadCount > 0 && (
            <span
              className={cn(
                "inline-flex shrink-0 items-center gap-1 rounded-md border px-1.5 py-0.5 text-[11px] font-medium tabular-nums",
                threadAttention ? "border-destructive/40 text-destructive" : "border-border text-muted-foreground",
              )}
              title={threadAttention ? t(`${k}.thread_attention`) : undefined}
            >
              <MessageSquareQuote className="h-3 w-3" aria-hidden />
              {t(`${k}.thread_count`, { n: threadCount })}
            </span>
          )}
        </span>
        {isThread && c.anchor_quote && <Quote text={c.anchor_quote} />}
      </span>

      <span className="flex items-center justify-end gap-2.5 text-xs md:order-last md:w-full">
        <Flags c={c} t={t} />
      </span>

      <span className="col-span-2 flex min-w-0 items-center gap-1.5 text-xs text-muted-foreground md:hidden">
        <span className="truncate">
          {c.user_id}
          {c.profile_slug ? ` · ${profileName(c.profile_slug)}` : ""}
        </span>
        <span className="shrink-0">· {t(`${k}.messages`, { n: c.message_count })}</span>
        <span className="shrink-0 tabular-nums">· {shortWhen(ms, now)}</span>
      </span>

      <span className={cn("hidden min-w-0 flex-col md:flex", child && "text-muted-foreground")}>
        <span className="truncate text-sm">{c.user_id}</span>
        {c.tenant_id && !child && <span className="truncate text-xs text-muted-foreground">{c.tenant_id}</span>}
      </span>
      <span className="hidden truncate text-sm text-muted-foreground md:block">{c.profile_slug ? profileName(c.profile_slug) : "—"}</span>
      <span className="hidden text-right text-sm tabular-nums text-muted-foreground md:block">{c.message_count}</span>
      <span className="hidden text-right text-sm tabular-nums text-muted-foreground md:block" title={fullWhen(ms)}>
        {shortWhen(ms, now)}
      </span>
    </button>
  );
}

export function ConversationList({
  rows,
  selectedId,
  sort,
  onSort,
  onOpen,
  onToggle,
  filters,
  onFilter,
  userOptions,
  profileOptions,
  profileName,
  now,
  empty,
  t,
}: {
  rows: FamilyRow[];
  selectedId: string | null;
  sort: Sort;
  onSort: (k: SortKey) => void;
  onOpen: (id: string) => void;
  /** Expands or collapses the side threads of a parent conversation. */
  onToggle: (parentId: string) => void;
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
      <div className={cn("hidden items-center gap-4 border-b border-border/60 py-2 pl-11 pr-5 md:grid", GRID)}>
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
        {rows.map((r) => {
          const { root } = r;
          const count = r.shownThreads.length;
          const groupId = `threads-of-${root.id}`;
          return (
            <li key={root.id} className="relative border-b border-border/40 last:border-b-0">
              <Row
                c={root}
                active={root.id === selectedId}
                dimmed={r.dimmed}
                threadCount={r.threads.length}
                threadAttention={r.threadAttention}
                onOpen={onOpen}
                profileName={profileName}
                now={now}
                t={t}
              />
              {count > 0 && (
                <button
                  type="button"
                  onClick={() => onToggle(root.id)}
                  aria-expanded={r.expanded}
                  aria-controls={groupId}
                  aria-label={r.expanded ? t(`${k}.threads_hide`) : t(`${k}.threads_show`, { n: count })}
                  title={r.expanded ? t(`${k}.threads_hide`) : t(`${k}.threads_show`, { n: count })}
                  className="focus-ring absolute left-2.5 top-3 flex h-6 w-6 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-background hover:text-foreground"
                >
                  <ChevronRight className={cn("h-4 w-4 transition-transform duration-200 ease-out motion-reduce:transition-none", r.expanded && "rotate-90")} aria-hidden />
                </button>
              )}
              {r.expanded && (
                <ul id={groupId} aria-label={t(`${k}.threads_of`, { title: root.title || t(`${k}.untitled`) })} className="border-t border-border/30 bg-muted/25">
                  {r.shownThreads.map((th, i) => {
                    const last = i === r.shownThreads.length - 1;
                    return (
                      <li key={th.id} className="relative border-b border-border/25 last:border-b-0">
                        {/* Tree connector from the parent's chevron to each thread. */}
                        <span aria-hidden className={cn("pointer-events-none absolute left-[1.3rem] top-0 w-px bg-border", last ? "h-1/2" : "h-full")} />
                        <span aria-hidden className="pointer-events-none absolute left-[1.3rem] top-1/2 h-px w-3 bg-border" />
                        <Row c={th} child active={th.id === selectedId} onOpen={onOpen} profileName={profileName} now={now} t={t} />
                      </li>
                    );
                  })}
                </ul>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
