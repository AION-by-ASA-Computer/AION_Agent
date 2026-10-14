"use client";

import { useEffect, useRef, useState } from "react";
import { AlertTriangle, ArrowDown, ArrowUpLeft, Check, ChevronDown, ChevronUp, Copy, Loader2, MessageSquareQuote, X } from "lucide-react";
import { cn } from "@/lib/cn";
import { ghostBtn } from "@/components/ui/classes";
import { Transcript } from "./Transcript";
import { fullWhen, toMs } from "./format";
import { isFlagged, type Conversation, type ThreadMessage } from "./types";

type T = (key: string, vars?: Record<string, string | number>) => string;
const k = "admin_conversations";

export function Reader({
  id,
  summary,
  parent,
  threads,
  onOpen,
  state,
  messages,
  highlightId,
  position,
  onClose,
  onStep,
  t,
}: {
  id: string;
  summary: Conversation | null;
  /** Parent conversation when this one is a side thread (null if not loaded). */
  parent: Conversation | null;
  /** Side threads opened from this conversation. */
  threads: Conversation[];
  onOpen: (id: string, messageId?: string | null) => void;
  state: "loading" | "ready" | "error";
  messages: ThreadMessage[];
  highlightId: string | null;
  position: { index: number; total: number } | null;
  onClose: () => void;
  onStep: (dir: 1 | -1) => void;
  t: T;
}) {
  const [showTools, setShowTools] = useState(false);
  const [copied, setCopied] = useState(false);
  const closeRef = useRef<HTMLButtonElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const flagCursor = useRef(-1);

  // Modal behaviour: lock page scroll, take focus, give it back to the row on close.
  useEffect(() => {
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeRef.current?.focus();
    return () => {
      document.body.style.overflow = prev;
    };
  }, []);

  useEffect(() => {
    flagCursor.current = -1;
    scrollRef.current?.scrollTo({ top: 0 });
  }, [id]);

  const flagged = messages.filter(isFlagged).map((m) => m.id);
  const toolCount = messages.filter((m) => m.tool_name).length;

  const nextFlag = () => {
    if (!flagged.length) return;
    flagCursor.current = (flagCursor.current + 1) % flagged.length;
    document.getElementById(`message-${flagged[flagCursor.current]}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
  };

  const copyId = async () => {
    try {
      await navigator.clipboard.writeText(id);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      /* clipboard unavailable */
    }
  };

  const title = summary?.title || t(`${k}.list.untitled`);
  const isThread = !!summary?.parent_conversation_id;
  // Threads whose source message is not in the transcript still need a way in.
  const shownIds = new Set(messages.map((m) => m.id));
  const looseThreads = state === "ready" ? threads.filter((th) => !th.parent_message_id || !shownIds.has(th.parent_message_id)) : [];
  const count = messages.length || summary?.message_count || 0;

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center p-3 sm:p-8">
      <button type="button" tabIndex={-1} aria-hidden onClick={onClose} className="absolute inset-0 bg-background/70 backdrop-blur-[2px] animate-in fade-in duration-200" />
      <aside
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="relative flex h-[min(92vh,60rem)] w-full max-w-5xl flex-col overflow-hidden rounded-3xl border border-border bg-background shadow-2xl animate-in fade-in zoom-in-95 duration-200"
      >
        <header className="flex flex-col gap-3 border-b border-border/60 px-5 pb-3 pt-4 sm:px-8">
          {isThread && (
            <div className="-mb-1 flex min-w-0 items-center gap-1.5 text-sm text-muted-foreground">
              {parent ? (
                <button
                  type="button"
                  onClick={() => onOpen(parent.id, summary?.parent_message_id)}
                  title={t(`${k}.detail.open_parent`)}
                  className="focus-ring -ml-1 inline-flex min-w-0 items-center gap-1.5 rounded-lg px-1 py-0.5 hover:text-foreground"
                >
                  <ArrowUpLeft className="h-3.5 w-3.5 shrink-0" aria-hidden />
                  <span className="shrink-0">{t(`${k}.detail.thread_from`)}</span>
                  <span className="truncate font-medium text-foreground">{parent.title || t(`${k}.list.untitled`)}</span>
                </button>
              ) : (
                <span>{t(`${k}.detail.parent_missing`)}</span>
              )}
            </div>
          )}
          <div className="flex items-center gap-2">
            <h2 className="min-w-0 flex-1 truncate text-lg font-semibold tracking-[-0.015em]">{title}</h2>
            {position && (
              <div className="flex shrink-0 items-center gap-0.5">
                <span className="mr-1 hidden text-xs tabular-nums text-muted-foreground sm:inline">{t(`${k}.detail.position`, { i: position.index + 1, n: position.total })}</span>
                <button type="button" className={cn(ghostBtn, "w-9 justify-center px-0")} onClick={() => onStep(-1)} disabled={position.index <= 0} title={`${t(`${k}.detail.prev`)} (K)`}>
                  <ChevronUp className="h-4 w-4" aria-hidden />
                  <span className="sr-only">{t(`${k}.detail.prev`)}</span>
                </button>
                <button type="button" className={cn(ghostBtn, "w-9 justify-center px-0")} onClick={() => onStep(1)} disabled={position.index >= position.total - 1} title={`${t(`${k}.detail.next`)} (J)`}>
                  <ChevronDown className="h-4 w-4" aria-hidden />
                  <span className="sr-only">{t(`${k}.detail.next`)}</span>
                </button>
              </div>
            )}
            <button ref={closeRef} type="button" className={cn(ghostBtn, "w-9 shrink-0 justify-center px-0")} onClick={onClose} title="Esc">
              <X className="h-4 w-4" aria-hidden />
              <span className="sr-only">{t(`${k}.detail.close`)}</span>
            </button>
          </div>

          <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-sm text-muted-foreground">
            {summary && (
              <>
                <span className="font-medium text-foreground">{summary.user_id}</span>
                {summary.tenant_id && <span>{summary.tenant_id}</span>}
                {summary.profile_slug && <span>{summary.profile_slug}</span>}
                <span className="tabular-nums">{fullWhen(toMs(summary.updated_at))}</span>
              </>
            )}
            <span className="tabular-nums">{t(`${k}.list.messages`, { n: count })}</span>
            <button type="button" onClick={copyId} title={id} className="focus-ring -ml-1 inline-flex items-center gap-1.5 rounded-lg px-1 py-0.5 hover:text-foreground">
              {copied ? <Check className="h-3.5 w-3.5" aria-hidden /> : <Copy className="h-3.5 w-3.5" aria-hidden />}
              <span role="status">{copied ? t(`${k}.detail.copied`) : t(`${k}.detail.copy_id`)}</span>
            </button>
          </div>

          {isThread && summary?.anchor_quote && (
            <blockquote className="flex min-w-0 items-start gap-2 rounded-xl border border-primary/25 bg-primary/[0.06] px-3 py-2 text-sm">
              <MessageSquareQuote className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" aria-hidden />
              <span className="line-clamp-3 min-w-0 break-words">{summary.anchor_quote}</span>
            </blockquote>
          )}

          {looseThreads.length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="mr-1 text-xs font-medium text-muted-foreground">{t(`${k}.detail.threads`, { n: looseThreads.length })}</span>
              {looseThreads.map((th) => (
                <ThreadChip key={th.id} thread={th} onOpen={onOpen} t={t} />
              ))}
            </div>
          )}

          {(flagged.length > 0 || toolCount > 0) && (
            <div className="flex flex-wrap items-center gap-2">
              {flagged.length > 0 && (
                <button type="button" onClick={nextFlag} title={t(`${k}.detail.next_flag`)} className="focus-ring inline-flex h-8 items-center gap-1.5 rounded-lg border border-destructive/40 bg-destructive/10 px-2.5 text-xs font-medium text-destructive">
                  <AlertTriangle className="h-3.5 w-3.5" aria-hidden />
                  {t(`${k}.detail.flagged`, { n: flagged.length })}
                  <ArrowDown className="h-3 w-3" aria-hidden />
                </button>
              )}
              {toolCount > 0 && (
                <button
                  type="button"
                  aria-pressed={showTools}
                  onClick={() => setShowTools((v) => !v)}
                  className={cn("focus-ring inline-flex h-8 items-center gap-1.5 rounded-lg border px-2.5 text-xs font-medium transition-colors", showTools ? "border-foreground/30 bg-secondary" : "border-border hover:bg-secondary")}
                >
                  {t(`${k}.detail.show_tools`)}
                  <span className="tabular-nums text-muted-foreground">{toolCount}</span>
                </button>
              )}
            </div>
          )}
        </header>

        <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto px-3 py-6 sm:px-6 sm:py-8" aria-busy={state === "loading"}>
          {state === "loading" ? (
            <div className="flex items-center justify-center gap-2 py-20 text-sm text-muted-foreground" role="status">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
              {t(`${k}.detail.loading`)}
            </div>
          ) : state === "error" ? (
            <p className="py-20 text-center text-sm text-destructive">{t(`${k}.detail.load_error`)}</p>
          ) : messages.length === 0 ? (
            <p className="py-20 text-center text-sm text-muted-foreground">{t(`${k}.detail.no_messages`)}</p>
          ) : (
            <Transcript
              messages={messages}
              convId={id}
              highlightId={highlightId}
              showTools={showTools}
              renderAfter={(m) => {
                const own = threads.filter((th) => th.parent_message_id === m.id);
                return own.length ? (
                  <div className="flex flex-wrap gap-1.5">
                    {own.map((th) => (
                      <ThreadChip key={th.id} thread={th} onOpen={onOpen} t={t} />
                    ))}
                  </div>
                ) : null;
              }}
              t={t}
            />
          )}
        </div>
      </aside>
    </div>
  );
}

/** Opens a side thread; labelled with the passage it was started on. */
function ThreadChip({ thread, onOpen, t }: { thread: Conversation; onOpen: (id: string) => void; t: T }) {
  const label = thread.anchor_quote || thread.title || t(`${k}.list.untitled`);
  return (
    <button
      type="button"
      onClick={() => onOpen(thread.id)}
      title={t(`${k}.detail.open_thread`)}
      className="focus-ring inline-flex h-7 max-w-[22rem] items-center gap-1.5 rounded-lg border border-primary/30 bg-primary/[0.06] px-2.5 text-xs font-medium text-foreground transition-colors hover:border-primary/60 hover:bg-primary/10"
    >
      <MessageSquareQuote className="h-3.5 w-3.5 shrink-0 text-primary" aria-hidden />
      <span className="truncate">“{label}”</span>
      <span className="shrink-0 tabular-nums text-muted-foreground">· {t(`${k}.list.messages`, { n: thread.message_count })}</span>
    </button>
  );
}
