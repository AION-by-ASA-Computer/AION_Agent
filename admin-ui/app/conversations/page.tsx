"use client";

import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { AlertTriangle, ArrowLeft, ArrowDown, Check, Copy, Loader2, RefreshCw, ThumbsDown } from "lucide-react";
import { apiFetch } from "@/lib/api/headers";
import { apiBase } from "@/lib/api";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";
import { ghostBtn, outlineBtn } from "@/components/ui/classes";
import { SearchField } from "@/components/ui/SearchField";
import { Select } from "@/components/ui/Select";
import { Transcript } from "@/components/conversations/Transcript";
import { dayBucket, fullWhen, shortWhen, toMs } from "@/components/conversations/format";
import { isFlagged, needsAttention, type Conversation, type ThreadMessage } from "@/components/conversations/types";

const k = "admin_conversations";
const FETCH_LIMIT = 500;
const RANGES = [
  { id: "24h", ms: 24 * 3600_000 },
  { id: "7d", ms: 7 * 86400_000 },
  { id: "30d", ms: 30 * 86400_000 },
  { id: "all", ms: 0 },
] as const;
type RangeId = (typeof RANGES)[number]["id"];

const NO_MESSAGES: ThreadMessage[] = [];
type Thread = { id: string; state: "loading" | "ready" | "error"; messages: ThreadMessage[] };

function ConversationsContent() {
  const t = useT();
  const router = useRouter();
  const params = useSearchParams();
  const selectedId = params.get("id");
  const messageParam = params.get("message");

  const [convs, setConvs] = useState<Conversation[]>([]);
  const [listState, setListState] = useState<"loading" | "ready" | "error">("loading");
  const [query, setQuery] = useState("");
  const [range, setRange] = useState<RangeId>("all");
  const [profile, setProfile] = useState("");
  const [attention, setAttention] = useState(false);
  const [showTools, setShowTools] = useState(false);
  const [thread, setThread] = useState<Thread | null>(null);
  const [copied, setCopied] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const flagCursor = useRef(-1);

  const loadList = useCallback(() => {
    apiFetch(`${apiBase()}/admin/conversations/global?limit=${FETCH_LIMIT}`)
      .then((res) => (res.ok ? res.json() : Promise.reject(res)))
      .then((data) => {
        setConvs(data.conversations || []);
        setNow(Date.now());
        setListState("ready");
      })
      .catch(() => setListState("error"));
  }, []);

  useEffect(() => {
    loadList();
  }, [loadList]);

  const refresh = () => {
    setListState("loading");
    loadList();
  };

  // Thread is keyed on the URL, so deep links from Feedback, reloads and back/forward all behave.
  useEffect(() => {
    if (!selectedId) return;
    let live = true;
    flagCursor.current = -1;
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
    }, 120);
    return () => window.clearTimeout(id);
  }, [messageParam, current]);

  const select = (id: string) => router.replace(`/conversations?id=${encodeURIComponent(id)}`, { scroll: false });
  const close = () => router.replace("/conversations", { scroll: false });

  const profiles = useMemo(() => Array.from(new Set(convs.map((c) => c.profile_slug).filter(Boolean))).sort(), [convs]);

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    const floor = RANGES.find((r) => r.id === range)!.ms;
    return convs.filter((c) => {
      if (floor && now - toMs(c.updated_at) > floor) return false;
      if (profile && c.profile_slug !== profile) return false;
      if (attention && !needsAttention(c)) return false;
      if (!q) return true;
      return [c.title, c.id, c.user_id, c.tenant_id, c.profile_slug].some((v) => (v || "").toLowerCase().includes(q));
    });
  }, [convs, query, range, profile, attention, now]);

  const todayLabel = t(`${k}.list.today`);
  const groups = useMemo(() => {
    const out: { key: string; label: string; items: Conversation[] }[] = [];
    for (const c of visible) {
      const b = dayBucket(toMs(c.updated_at), t, now);
      const last = out[out.length - 1];
      if (last && last.key === b.key) last.items.push(c);
      else out.push({ ...b, items: [c] });
    }
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible, now, todayLabel]);

  const attentionTotal = useMemo(() => convs.filter(needsAttention).length, [convs]);
  const filtering = !!query || range !== "all" || !!profile || attention;
  const clearFilters = () => {
    setQuery("");
    setRange("all");
    setProfile("");
    setAttention(false);
  };

  const summary = convs.find((c) => c.id === selectedId) ?? null;
  const messages = current?.messages ?? NO_MESSAGES;
  const flaggedIds = useMemo(() => messages.filter(isFlagged).map((m) => m.id), [messages]);
  const toolCount = messages.filter((m) => m.tool_name).length;

  const nextFlag = () => {
    if (!flaggedIds.length) return;
    flagCursor.current = (flagCursor.current + 1) % flaggedIds.length;
    document.getElementById(`message-${flaggedIds[flagCursor.current]}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
  };

  const copyId = async () => {
    if (!selectedId) return;
    try {
      await navigator.clipboard.writeText(selectedId);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      /* clipboard unavailable */
    }
  };

  const title = summary?.title || t(`${k}.list.untitled`);
  const detailOpen = !!selectedId;
  const noneAtAll = listState === "ready" && convs.length === 0;

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
        <div className="grid items-start gap-6 lg:grid-cols-[22rem_minmax(0,1fr)]">
          {/* ───────── List ───────── */}
          <aside className={cn("flex min-w-0 flex-col gap-3 lg:sticky lg:top-4 lg:max-h-[calc(100dvh-2rem)]", detailOpen && "hidden lg:flex")}>
            <SearchField value={query} onChange={setQuery} placeholder={t(`${k}.list.search`)} />

            <div role="group" aria-label={t(`${k}.list.range_aria`)} className="grid grid-cols-4 gap-1 rounded-xl bg-secondary p-1">
              {RANGES.map((r) => (
                <button
                  key={r.id}
                  type="button"
                  aria-pressed={range === r.id}
                  onClick={() => setRange(r.id)}
                  className={cn(
                    "focus-ring h-8 truncate rounded-lg px-1 text-xs font-medium transition-colors",
                    range === r.id ? "bg-card text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground",
                  )}
                >
                  {t(`${k}.list.range_${r.id}`)}
                </button>
              ))}
            </div>

            <div className="flex items-center gap-2">
              {profiles.length > 1 && (
                <Select
                  size="sm"
                  className="min-w-0 flex-1"
                  aria-label={t(`${k}.list.profile_aria`)}
                  value={profile}
                  onChange={setProfile}
                  options={[{ value: "", label: t(`${k}.list.profile_all`) }, ...profiles.map((p) => ({ value: p, label: p }))]}
                />
              )}
              {attentionTotal > 0 && (
                <button
                  type="button"
                  aria-pressed={attention}
                  onClick={() => setAttention((v) => !v)}
                  className={cn(
                    "focus-ring inline-flex h-9 shrink-0 items-center gap-1.5 rounded-xl border px-3 text-sm font-medium transition-colors",
                    attention ? "border-destructive/40 bg-destructive/10 text-destructive" : "border-border bg-card hover:bg-secondary",
                    profiles.length <= 1 && "flex-1 justify-center",
                  )}
                >
                  <AlertTriangle className="h-3.5 w-3.5" aria-hidden />
                  {t(`${k}.list.attention`)}
                  <span className="tabular-nums text-muted-foreground">{attentionTotal}</span>
                </button>
              )}
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto pr-1">
              {listState === "loading" ? (
                <div className="flex items-center gap-2 px-1 py-6 text-sm text-muted-foreground" role="status">
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                  {t(`${k}.loading`)}
                </div>
              ) : listState === "error" ? (
                <div className="flex flex-col items-start gap-3 px-1 py-6">
                  <p className="text-sm text-destructive">{t(`${k}.error`)}</p>
                  <button type="button" className={outlineBtn} onClick={refresh}>
                    {t(`${k}.retry`)}
                  </button>
                </div>
              ) : visible.length === 0 ? (
                <div className="px-1 py-6">
                  <h2 className="text-sm font-semibold">{t(`${k}.list.empty_title`)}</h2>
                  <p className="mt-1 text-sm text-muted-foreground">{t(`${k}.list.empty_body`)}</p>
                  {filtering && (
                    <button type="button" className={cn(ghostBtn, "-ml-2 mt-2")} onClick={clearFilters}>
                      {t(`${k}.list.clear`)}
                    </button>
                  )}
                </div>
              ) : (
                <nav aria-label={t(`${k}.list.aria`)} className="flex flex-col gap-4">
                  {groups.map((g) => (
                    <section key={g.key}>
                      <h2 className="px-3 pb-1 text-xs font-medium text-muted-foreground">{g.label}</h2>
                      <ul className="flex flex-col gap-0.5">
                        {g.items.map((c) => {
                          const active = c.id === selectedId;
                          const down = c.disliked_count ?? 0;
                          const errs = c.error_count ?? 0;
                          return (
                            <li key={c.id}>
                              <button
                                type="button"
                                aria-current={active ? "true" : undefined}
                                onClick={() => !active && select(c.id)}
                                className={cn(
                                  "focus-ring w-full rounded-xl px-3 py-2.5 text-left transition-colors",
                                  active ? "bg-secondary" : "hover:bg-secondary/60",
                                )}
                              >
                                <div className="flex items-baseline gap-2">
                                  <span className="min-w-0 flex-1 truncate text-sm font-medium">{c.title || t(`${k}.list.untitled`)}</span>
                                  <span className="shrink-0 text-xs tabular-nums text-muted-foreground">{shortWhen(toMs(c.updated_at), now)}</span>
                                </div>
                                <div className="mt-0.5 flex items-center gap-2 text-xs text-muted-foreground">
                                  <span className="min-w-0 flex-1 truncate">
                                    {c.user_id}
                                    {c.profile_slug ? ` · ${c.profile_slug}` : ""}
                                  </span>
                                  {down > 0 && (
                                    <span className="inline-flex shrink-0 items-center gap-0.5 font-medium text-destructive" title={t(`${k}.detail.disliked`)}>
                                      <ThumbsDown className="h-3 w-3" aria-hidden />
                                      {down}
                                    </span>
                                  )}
                                  {errs > 0 && (
                                    <span className="inline-flex shrink-0 items-center gap-0.5 font-medium text-destructive" title={t(`${k}.detail.tool_errors`, { n: errs })}>
                                      <AlertTriangle className="h-3 w-3" aria-hidden />
                                      {errs}
                                    </span>
                                  )}
                                  <span className="shrink-0 tabular-nums">{t(`${k}.list.messages`, { n: c.message_count })}</span>
                                </div>
                              </button>
                            </li>
                          );
                        })}
                      </ul>
                    </section>
                  ))}
                  {convs.length >= FETCH_LIMIT && !filtering && (
                    <p className="px-3 text-xs text-muted-foreground">{t(`${k}.list.truncated`, { n: FETCH_LIMIT })}</p>
                  )}
                </nav>
              )}
            </div>
          </aside>

          {/* ───────── Thread ───────── */}
          <section className={cn("min-w-0", !detailOpen && "hidden lg:block")} aria-busy={!current}>
            {!detailOpen ? (
              <div className="rounded-3xl border border-dashed border-border px-6 py-20 text-center">
                <h2 className="text-lg font-semibold tracking-[-0.015em]">{t(`${k}.detail.pick_title`)}</h2>
                <p className="mt-1.5 text-sm text-muted-foreground">{t(`${k}.detail.pick_body`)}</p>
              </div>
            ) : (
              <div className="rounded-3xl border border-border/70 bg-card">
                <div className="flex flex-col gap-3 border-b border-border/60 p-5 sm:p-6">
                  <div className="flex items-start gap-2">
                    <button type="button" className={cn(ghostBtn, "-ml-2 -mt-1 shrink-0 lg:hidden")} onClick={close}>
                      <ArrowLeft className="h-4 w-4" aria-hidden />
                      <span className="sr-only">{t(`${k}.list.back`)}</span>
                    </button>
                    <h2 className="min-w-0 flex-1 text-balance text-lg font-semibold tracking-[-0.015em]">{title}</h2>
                    <button type="button" className={cn(ghostBtn, "-mr-2 -mt-1 shrink-0")} onClick={copyId} title={selectedId ?? undefined}>
                      {copied ? <Check className="h-3.5 w-3.5" aria-hidden /> : <Copy className="h-3.5 w-3.5" aria-hidden />}
                      <span role="status">{copied ? t(`${k}.detail.copied`) : t(`${k}.detail.copy_id`)}</span>
                    </button>
                  </div>
                  {summary && (
                    <dl className="grid grid-cols-2 gap-x-6 gap-y-3 text-sm sm:grid-cols-4">
                      <Meta label={t(`${k}.detail.user`)} value={summary.user_id} />
                      <Meta label={t(`${k}.detail.tenant`)} value={summary.tenant_id} />
                      <Meta label={t(`${k}.detail.profile`)} value={summary.profile_slug} />
                      <Meta label={t(`${k}.detail.updated`)} value={fullWhen(toMs(summary.updated_at))} />
                    </dl>
                  )}
                </div>

                <div className="sticky top-0 z-10 flex flex-wrap items-center gap-2 border-b border-border/60 bg-card/95 px-5 py-2 backdrop-blur-sm sm:px-6">
                  <span className="text-sm tabular-nums text-muted-foreground">
                    {t(`${k}.list.messages`, { n: messages.length || summary?.message_count || 0 })}
                  </span>
                  <div className="ml-auto flex flex-wrap items-center gap-1">
                    {flaggedIds.length > 0 && (
                      <button type="button" className={cn(ghostBtn, "text-destructive hover:text-destructive")} onClick={nextFlag} title={t(`${k}.detail.next_flag`)}>
                        <ArrowDown className="h-3.5 w-3.5" aria-hidden />
                        {t(`${k}.detail.flagged`, { n: flaggedIds.length })}
                      </button>
                    )}
                    {toolCount > 0 && (
                      <button
                        type="button"
                        aria-pressed={showTools}
                        onClick={() => setShowTools((v) => !v)}
                        className={cn(ghostBtn, showTools && "bg-secondary text-foreground")}
                      >
                        {t(`${k}.detail.show_tools`)}
                        <span className="tabular-nums">{toolCount}</span>
                      </button>
                    )}
                  </div>
                </div>

                <div className="p-5 sm:p-6">
                  {!current ? (
                    <div className="flex items-center gap-2 py-10 text-sm text-muted-foreground" role="status">
                      <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                      {t(`${k}.detail.loading`)}
                    </div>
                  ) : current.state === "error" ? (
                    <p className="py-10 text-sm text-destructive">{t(`${k}.detail.load_error`)}</p>
                  ) : messages.length === 0 ? (
                    <p className="py-10 text-sm text-muted-foreground">{t(`${k}.detail.no_messages`)}</p>
                  ) : (
                    <Transcript messages={messages} convId={current.id} highlightId={messageParam} showTools={showTools} t={t} />
                  )}
                </div>
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="mt-0.5 truncate font-medium" title={value}>
        {value || "—"}
      </dd>
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
