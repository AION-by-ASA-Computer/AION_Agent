"use client";

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { AlertTriangle, Loader2, RefreshCw } from "lucide-react";
import { apiFetch } from "@/lib/api/headers";
import { apiBase } from "@/lib/api";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";
import { ghostBtn, outlineBtn } from "@/components/ui/classes";
import { SearchField } from "@/components/ui/SearchField";
import { ConversationList, DateFilter, FEEDBACK_VALUES, flagTotal, matchesFeedback, type DateRange, type FamilyRow, type FilterCol, type Filters, type Sort, type SortKey } from "@/components/conversations/ConversationList";
import { Reader } from "@/components/conversations/Reader";
import { toMs } from "@/components/conversations/format";
import { needsAttention, type Conversation, type ConversationFamily, type ThreadMessage } from "@/components/conversations/types";

const k = "admin_conversations";
const FETCH_LIMIT = 500;
const PAGE = 60;
const NO_FILTERS: Filters = { conversation: "", user: "", profile: "", feedback: "" };
const NO_MESSAGES: ThreadMessage[] = [];
type Thread = { id: string; state: "ready" | "error"; messages: ThreadMessage[] };

function ConversationsContent() {
  const t = useT();
  const router = useRouter();
  const params = useSearchParams();
  const selectedId = params.get("id");
  const messageParam = params.get("message");

  const [convs, setConvs] = useState<Conversation[]>([]);
  const [truncated, setTruncated] = useState(false);
  const [listState, setListState] = useState<"loading" | "ready" | "error">("loading");
  const [now, setNow] = useState(() => Date.now());
  const [query, setQuery] = useState("");
  const [dateRange, setDateRange] = useState<DateRange>({ from: "", to: "" });
  const [filters, setFilters] = useState<Filters>(() => {
    const f = params.get("feedback") ?? "";
    return { ...NO_FILTERS, feedback: (FEEDBACK_VALUES as readonly string[]).includes(f) ? f : "" };
  });
  const [profileNames, setProfileNames] = useState<Record<string, string>>({});
  const [attention, setAttention] = useState(false);
  const [sort, setSort] = useState<Sort>({ key: "updated", dir: "desc" });
  const [limit, setLimit] = useState(PAGE);
  const [thread, setThread] = useState<Thread | null>(null);
  // Explicit expand/collapse choices per parent; unset parents follow the automatic rule.
  const [expandChoice, setExpandChoice] = useState<Record<string, boolean>>({});

  const loadList = useCallback(() => {
    apiFetch(`${apiBase()}/admin/conversations/global?limit=${FETCH_LIMIT}`)
      .then((res) => (res.ok ? res.json() : Promise.reject(res)))
      .then((data) => {
        const list: Conversation[] = data.conversations || [];
        setConvs(list);
        setTruncated(data.truncated ?? list.length >= FETCH_LIMIT);
        setNow(Date.now());
        setListState("ready");
      })
      .catch(() => setListState("error"));
  }, []);

  useEffect(() => {
    loadList();
  }, [loadList]);

  // Profiles are shown by their name, not the slug the conversation stores.
  useEffect(() => {
    apiFetch(`${apiBase()}/admin/profiles`)
      .then((res) => (res.ok ? res.json() : Promise.reject(res)))
      .then((data: { slug: string; name: string }[]) => setProfileNames(Object.fromEntries((data || []).map((p) => [p.slug, p.name || p.slug]))))
      .catch(() => {});
  }, []);
  const profileName = useCallback((slug: string) => profileNames[slug] || slug, [profileNames]);

  const refresh = () => {
    setListState("loading");
    loadList();
  };

  // The open thread lives in the URL, so deep links from Feedback, reloads and back/forward all work.
  useEffect(() => {
    if (!selectedId) return;
    let live = true;
    apiFetch(`${apiBase()}/admin/conversations/${encodeURIComponent(selectedId)}/messages?include_internal=true`)
      .then((res) => (res.ok ? res.json() : Promise.reject(res)))
      .then((data) => live && setThread({ id: selectedId, state: "ready", messages: data.messages || [] }))
      .catch(() => live && setThread({ id: selectedId, state: "error", messages: [] }));
    return () => {
      live = false;
    };
  }, [selectedId]);

  const current = thread && thread.id === selectedId ? thread : null; // null while the next thread loads

  useEffect(() => {
    if (!messageParam || !current || current.state !== "ready") return;
    const id = window.setTimeout(() => {
      document.getElementById(`message-${messageParam}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
    }, 160);
    return () => window.clearTimeout(id);
  }, [messageParam, current]);

  const open = useCallback(
    (id: string, messageId?: string | null) =>
      router.replace(`/conversations?id=${encodeURIComponent(id)}${messageId ? `&message=${encodeURIComponent(messageId)}` : ""}`, { scroll: false }),
    [router],
  );
  const close = useCallback(() => {
    const id = selectedId;
    router.replace("/conversations", { scroll: false });
    if (id) window.setTimeout(() => document.querySelector<HTMLElement>(`[data-conv-id="${CSS.escape(id)}"]`)?.focus(), 60);
  }, [router, selectedId]);

  const userOptions = useMemo(() => Array.from(new Set(convs.map((c) => c.user_id).filter(Boolean))).sort().map((v) => ({ value: v, label: v })), [convs]);
  const profileOptions = useMemo(
    () => Array.from(new Set(convs.map((c) => c.profile_slug).filter(Boolean))).map((v) => ({ value: v, label: profileName(v) })).sort((a, b) => a.label.localeCompare(b.label)),
    [convs, profileName],
  );
  const setFilter = (col: FilterCol, value: string) => setFilters((f) => ({ ...f, [col]: value }));

  // Side threads are child conversations: group them under their parent.
  const byId = useMemo(() => new Map(convs.map((c) => [c.id, c])), [convs]);
  const families = useMemo<ConversationFamily[]>(() => {
    const kids = new Map<string, Conversation[]>();
    const out: ConversationFamily[] = [];
    for (const c of convs) {
      const pid = c.parent_conversation_id;
      if (pid && byId.has(pid)) kids.set(pid, [...(kids.get(pid) ?? []), c]);
    }
    for (const c of convs) {
      const pid = c.parent_conversation_id;
      if (pid && byId.has(pid)) continue;
      const threads = (kids.get(c.id) ?? []).sort((x, y) => toMs(y.updated_at) - toMs(x.updated_at));
      out.push({ root: c, threads, orphan: !!pid });
    }
    return out;
  }, [convs, byId]);

  const filtering = !!query || !!(dateRange.from || dateRange.to) || Object.values(filters).some(Boolean) || attention;

  const rows = useMemo<FamilyRow[]>(() => {
    const q = query.trim().toLowerCase();
    const lo = dateRange.from ? new Date(`${dateRange.from}T00:00:00`).getTime() : 0;
    const hi = dateRange.to ? new Date(`${dateRange.to}T23:59:59.999`).getTime() : Infinity;
    const matches = (c: Conversation) => {
      const at = toMs(c.updated_at);
      if (at < lo || at > hi) return false;
      if (filters.user && !c.user_id.toLowerCase().includes(filters.user.trim().toLowerCase())) return false;
      if (filters.feedback && !matchesFeedback(c, filters.feedback)) return false;
      if (filters.profile && c.profile_slug !== filters.profile) return false;
      const ct = filters.conversation.trim().toLowerCase();
      if (ct && !`${c.title || ""} ${c.anchor_quote || ""} ${c.id}`.toLowerCase().includes(ct)) return false;
      if (attention && !needsAttention(c)) return false;
      if (!q) return true;
      return [c.title, c.anchor_quote, c.id, c.user_id, c.tenant_id, c.profile_slug, profileName(c.profile_slug)].some((v) => (v || "").toLowerCase().includes(q));
    };
    const out: FamilyRow[] = [];
    for (const f of families) {
      const rootHit = matches(f.root);
      const hits = f.threads.filter(matches);
      if (!rootHit && hits.length === 0) continue;
      // A family shown only because of a thread keeps its parent as context, dimmed.
      const shownThreads = rootHit ? f.threads : hits;
      const auto = (!rootHit && hits.length > 0) || f.threads.some((th) => th.id === selectedId);
      const members = [f.root, ...f.threads];
      out.push({
        ...f,
        shownThreads,
        expanded: shownThreads.length > 0 && (expandChoice[f.root.id] ?? auto),
        dimmed: !rootHit,
        latest: Math.max(...members.map((c) => toMs(c.updated_at))),
        flagSum: members.reduce((n, c) => n + flagTotal(c), 0),
        threadAttention: f.threads.some(needsAttention),
      });
    }
    const val = (r: FamilyRow) => (sort.key === "messages" ? r.root.message_count : sort.key === "flags" ? r.flagSum : r.latest);
    const sign = sort.dir === "asc" ? 1 : -1;
    return out.sort((a, b) => (val(a) - val(b)) * sign || b.latest - a.latest);
  }, [families, query, dateRange, filters, attention, sort, profileName, expandChoice, selectedId]);

  const toggleFamily = useCallback(
    (id: string) => setExpandChoice((m) => ({ ...m, [id]: !(rows.find((r) => r.root.id === id)?.expanded ?? false) })),
    [rows],
  );

  const attentionTotal = useMemo(() => families.filter((f) => needsAttention(f.root) || f.threads.some(needsAttention)).length, [families]);
  const clearFilters = () => {
    setQuery("");
    setDateRange({ from: "", to: "" });
    setFilters(NO_FILTERS);
    setAttention(false);
  };

  const shown = rows.slice(0, limit);
  // J/K walk what the list shows: each parent, then its threads when expanded.
  const order = useMemo(() => rows.flatMap((r) => [r.root.id, ...(r.expanded ? r.shownThreads.map((th) => th.id) : [])]), [rows]);
  const index = selectedId ? order.indexOf(selectedId) : -1;
  const position = index >= 0 ? { index, total: order.length } : null;
  const step = useCallback(
    (dir: 1 | -1) => {
      const next = order[index + dir];
      if (next) open(next);
    },
    [order, index, open],
  );

  // Keyboard: Esc closes the reader, J/K walk the list while it is open.
  useEffect(() => {
    if (!selectedId) return;
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      if (el && /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName)) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === "Escape") close();
      else if (e.key === "j") step(1);
      else if (e.key === "k") step(-1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selectedId, close, step]);

  const onSort = (key: SortKey) => setSort((s) => (s.key === key ? { key, dir: s.dir === "desc" ? "asc" : "desc" } : { key, dir: "desc" }));

  const noneAtAll = listState === "ready" && convs.length === 0;
  const summary = (selectedId && byId.get(selectedId)) || null;
  const parentConv = summary?.parent_conversation_id ? (byId.get(summary.parent_conversation_id) ?? null) : null;
  const childThreads = useMemo(() => (selectedId ? families.find((f) => f.root.id === selectedId)?.threads ?? [] : []), [families, selectedId]);

  return (
    <div className="mx-auto flex max-w-[84rem] flex-col gap-6">
      <header className="flex flex-col gap-4 pt-2 sm:flex-row sm:items-end">
        <div className="min-w-0 flex-1">
          <h1 className="text-balance text-2xl font-semibold tracking-[-0.02em] sm:text-[28px]">{t(`${k}.title`)}</h1>
          <p className="mt-1 max-w-[60ch] text-sm text-muted-foreground">{t(`${k}.subtitle`)}</p>
        </div>
        <button type="button" className={outlineBtn} onClick={refresh} disabled={listState === "loading"}>
          <RefreshCw className={cn("h-3.5 w-3.5", listState === "loading" && "animate-spin")} aria-hidden />
          {t(`${k}.refresh`)}
        </button>
      </header>

      {noneAtAll ? (
        <div className="flex flex-col items-center rounded-3xl border border-dashed border-border px-6 py-20 text-center">
          <h2 className="text-lg font-semibold tracking-[-0.015em]">{t(`${k}.list.none_title`)}</h2>
          <p className="mt-1.5 max-w-[46ch] text-sm text-muted-foreground">{t(`${k}.list.none_body`)}</p>
        </div>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <div className="min-w-[14rem] flex-1 sm:max-w-sm">
              <SearchField value={query} onChange={setQuery} placeholder={t(`${k}.list.search`)} />
            </div>

            <DateFilter value={dateRange} onChange={setDateRange} now={now} t={t} />

            {attentionTotal > 0 && (
              <button
                type="button"
                aria-pressed={attention}
                onClick={() => setAttention((v) => !v)}
                className={cn(
                  "focus-ring inline-flex h-9 items-center gap-1.5 rounded-xl border px-3 text-sm font-medium transition-colors",
                  attention ? "border-destructive/40 bg-destructive/10 text-destructive" : "border-border bg-card hover:bg-secondary",
                )}
              >
                <AlertTriangle className="h-3.5 w-3.5" aria-hidden />
                {t(`${k}.list.attention`)}
                <span className="tabular-nums opacity-70">{attentionTotal}</span>
              </button>
            )}

            {listState === "ready" && (
              <span className="ml-auto text-sm tabular-nums text-muted-foreground">
                {filtering ? t(`${k}.list.count_filtered`, { shown: rows.length, total: families.length }) : t(`${k}.list.count`, { n: families.length })}
              </span>
            )}
          </div>

          {listState === "loading" ? (
            <div className="flex items-center gap-2 px-1 py-10 text-sm text-muted-foreground" role="status">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
              {t(`${k}.loading`)}
            </div>
          ) : listState === "error" ? (
            <div className="flex flex-col items-start gap-3 px-1 py-10">
              <p className="text-sm text-destructive">{t(`${k}.error`)}</p>
              <button type="button" className={outlineBtn} onClick={refresh}>
                {t(`${k}.retry`)}
              </button>
            </div>
          ) : (
            <>
              <ConversationList rows={shown} selectedId={selectedId} sort={sort} onSort={onSort} onOpen={open} onToggle={toggleFamily} filters={filters} onFilter={setFilter} userOptions={userOptions} profileOptions={profileOptions} profileName={profileName}
                now={now}
                t={t}
                empty={
                  rows.length === 0 ? (
                    <div className="px-6 py-16 text-center">
                      <h2 className="text-lg font-semibold tracking-[-0.015em]">{t(`${k}.list.empty_title`)}</h2>
                      <p className="mt-1.5 text-sm text-muted-foreground">{t(`${k}.list.empty_body`)}</p>
                      {filtering && (
                        <button type="button" className={cn(ghostBtn, "mt-3")} onClick={clearFilters}>
                          {t(`${k}.list.clear`)}
                        </button>
                      )}
                    </div>
                  ) : null
                }
              />
              <div className="flex flex-col items-center gap-2 pb-6">
                {rows.length > shown.length && (
                  <button type="button" className={outlineBtn} onClick={() => setLimit((n) => n + PAGE)}>
                    {t(`${k}.list.show_more`, { n: Math.min(PAGE, rows.length - shown.length) })}
                  </button>
                )}
                {truncated && !filtering && <p className="text-xs text-muted-foreground">{t(`${k}.list.truncated`, { n: FETCH_LIMIT })}</p>}
              </div>
            </>
          )}
        </>
      )}

      {selectedId && (
        <Reader
          id={selectedId}
          summary={summary}
          parent={parentConv}
          threads={childThreads}
          onOpen={open}
          state={current ? current.state : "loading"}
          messages={current?.messages ?? NO_MESSAGES}
          highlightId={messageParam}
          position={position}
          onClose={close}
          onStep={step}
          t={t}
        />
      )}
    </div>
  );
}

export default function ConversationsPage() {
  return (
    <Suspense fallback={null}>
      <ConversationsContent />
    </Suspense>
  );
}
