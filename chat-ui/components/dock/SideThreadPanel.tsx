"use client";

import Link from "next/link";
import { useEffect, useLayoutEffect, useRef, useState, type ComponentProps } from "react";
import {
  AlertCircle,
  ArrowUp,
  ChevronDown,
  CornerDownRight,
  Loader2,
  MessageSquareQuote,
  SquareArrowOutUpRight,
  Square,
} from "lucide-react";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";
import { useAutoResizeTextarea } from "@/lib/hooks/use-auto-resize-textarea";
import type { SideThreadAnchor, SideThreadSummary } from "@/lib/api/aion";
import type { useSideThreadChat } from "@/lib/side-thread/use-side-thread-chat";
import { TurnTimeline } from "@/components/chat/TurnTimeline";
import { AgentWorkingShimmer } from "@/components/chat/ShimmerText";

/** What the panel shows: an existing thread, or a draft that is created on first send. */
export type SideThreadTarget =
  | { kind: "thread"; thread: SideThreadSummary }
  | { kind: "draft"; messageId: string; anchor: SideThreadAnchor; truncated: boolean };

type TimelineProps = ComponentProps<typeof TurnTimeline>;

type Props = {
  target: SideThreadTarget;
  threads: SideThreadSummary[];
  chat: ReturnType<typeof useSideThreadChat>;
  passageMissing: boolean;
  onRevealPassage: () => void;
  onSelectThread: (threadId: string) => void;
  /** Bumped whenever a thread is opened, to move focus into the composer. */
  focusKey: number;
  toolsView: TimelineProps["toolsView"];
  token?: string | null;
  renderMarkdownLink?: TimelineProps["renderMarkdownLink"];
  formatTextWithCitations?: TimelineProps["formatTextWithCitations"];
};

const STARTERS = ["explain", "example", "relevance"] as const;

export function SideThreadPanel({
  target,
  threads,
  chat,
  passageMissing,
  onRevealPassage,
  onSelectThread,
  focusKey,
  toolsView,
  token,
  renderMarkdownLink,
  formatTextWithCitations,
}: Props) {
  const t = useT();
  const [draft, setDraft] = useState("");
  const [switcherOpen, setSwitcherOpen] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const stickRef = useRef(true);
  useAutoResizeTextarea(textareaRef, draft, { minHeight: 24, maxHeight: 180 });

  const threadId = target.kind === "thread" ? target.thread.id : null;
  const anchor = target.kind === "thread" ? target.thread.anchor : target.anchor;
  const title =
    target.kind === "thread" ? target.thread.title || anchor.quote : t("sideThread.panel.new_title");
  const others = threads.filter((th) => th.id !== threadId);
  const { messages, turn, streaming, loading, error, failedInput } = chat;
  const isEmpty = !loading && messages.length === 0 && !turn;

  useEffect(() => {
    // Delay so the dock slide-in does not fight the focus scroll.
    const id = window.setTimeout(() => textareaRef.current?.focus({ preventScroll: true }), 60);
    return () => window.clearTimeout(id);
  }, [focusKey]);

  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (el && stickRef.current) el.scrollTop = el.scrollHeight;
  }, [messages, turn, error]);

  const submit = (text: string) => {
    const value = text.trim();
    if (!value || streaming) return;
    stickRef.current = true;
    setDraft("");
    void chat.send(value);
  };

  return (
    <section className="flex h-full min-h-0 flex-col" aria-label={t("sideThread.panel.aria")}>
      <header className="shrink-0 space-y-2.5 border-b border-border/70 px-4 pb-3 pt-3.5">
        <div className="flex items-start gap-2">
          <h2 className="min-w-0 flex-1 text-[15px] font-semibold leading-snug text-foreground [text-wrap:balance] line-clamp-2">
            {title}
          </h2>
          {threadId ? (
            <Link
              href={`/c/${threadId}`}
              className="focus-ring -mr-1 shrink-0 rounded-lg p-1.5 text-muted-foreground transition-colors hover:bg-muted/60 hover:text-foreground"
              title={t("sideThread.panel.open_full")}
              aria-label={t("sideThread.panel.open_full")}
            >
              <SquareArrowOutUpRight className="size-4" aria-hidden />
            </Link>
          ) : null}
        </div>

        <button
          type="button"
          onClick={onRevealPassage}
          disabled={passageMissing}
          className={cn(
            "focus-ring group flex w-full items-start gap-2 rounded-lg bg-muted/45 px-3 py-2 text-left transition-colors",
            "enabled:hover:bg-muted/80 disabled:cursor-default",
          )}
          title={passageMissing ? undefined : t("sideThread.panel.reveal")}
        >
          <MessageSquareQuote className="mt-0.5 size-3.5 shrink-0 text-primary/80" aria-hidden />
          <span className="min-w-0 flex-1">
            <span className="line-clamp-3 text-[13px] leading-relaxed text-muted-foreground group-enabled:group-hover:text-foreground">
              {anchor.quote}
            </span>
            {passageMissing ? (
              <span className="mt-1 block text-[11.5px] text-muted-foreground/90">
                {t("sideThread.panel.passage_missing")}
              </span>
            ) : null}
            {target.kind === "draft" && target.truncated ? (
              <span className="mt-1 block text-[11.5px] text-muted-foreground/90">
                {t("sideThread.popover.truncated", { max: 2000 })}
              </span>
            ) : null}
          </span>
        </button>

        {others.length > 0 ? (
          <div>
            <button
              type="button"
              onClick={() => setSwitcherOpen((v) => !v)}
              aria-expanded={switcherOpen}
              className="focus-ring -ml-1 flex items-center gap-1 rounded-md px-1 py-0.5 text-[12px] font-medium text-muted-foreground transition-colors hover:text-foreground"
            >
              <ChevronDown
                className={cn("size-3.5 transition-transform duration-200", switcherOpen && "rotate-180")}
                aria-hidden
              />
              {t("sideThread.panel.other_threads", { count: others.length })}
            </button>
            {switcherOpen ? (
              <ul className="mt-1.5 max-h-48 space-y-0.5 overflow-y-auto">
                {others.map((th) => (
                  <li key={th.id}>
                    <button
                      type="button"
                      onClick={() => onSelectThread(th.id)}
                      className="focus-ring flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-[13px] text-foreground/85 transition-colors hover:bg-muted/60 hover:text-foreground"
                    >
                      <CornerDownRight className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
                      <span className="min-w-0 flex-1 truncate">{th.title || th.anchor.quote}</span>
                      {th.message_count ? (
                        <span className="shrink-0 tabular-nums text-[11px] text-muted-foreground">
                          {th.message_count}
                        </span>
                      ) : null}
                    </button>
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        ) : null}
      </header>

      <div
        ref={scrollRef}
        onScroll={(e) => {
          const el = e.currentTarget;
          stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 48;
        }}
        className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 py-4"
        aria-live="polite"
        aria-busy={streaming || loading}
      >
        {loading ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" aria-hidden />
            {t("sideThread.panel.loading")}
          </div>
        ) : null}

        {isEmpty ? (
          <div className="flex flex-col gap-3">
            <p className="text-[13px] leading-relaxed text-muted-foreground">{t("sideThread.panel.empty")}</p>
            <div className="flex flex-wrap gap-1.5">
              {STARTERS.map((key) => (
                <button
                  key={key}
                  type="button"
                  disabled={streaming}
                  onClick={() => submit(t(`sideThread.starters.${key}`))}
                  className="focus-ring rounded-full border border-border px-3 py-1 text-[12.5px] text-foreground/85 transition-colors hover:border-primary/40 hover:bg-primary/5 hover:text-foreground disabled:opacity-50"
                >
                  {t(`sideThread.starters.${key}`)}
                </button>
              ))}
            </div>
          </div>
        ) : null}

        <div className="flex flex-col gap-4">
          {messages.map((m) =>
            m.role === "user" ? (
              <div
                key={m.id}
                className="ml-auto max-w-[88%] whitespace-pre-wrap break-words rounded-2xl rounded-br-md bg-muted px-3.5 py-2 text-[14px] leading-relaxed text-foreground"
              >
                {m.content}
              </div>
            ) : (
              <div key={m.id} className="chat-font min-w-0 text-[14px]">
                <TurnTimeline
                  segments={m.segments ?? []}
                  toolsView={toolsView}
                  conversationId={threadId ?? undefined}
                  token={token}
                  messageId={m.id}
                  renderMarkdownLink={renderMarkdownLink}
                  formatTextWithCitations={formatTextWithCitations}
                />
              </div>
            ),
          )}
          {turn ? (
            <div className="chat-font min-w-0 text-[14px]">
              {turn.segments.length === 0 ? <AgentWorkingShimmer /> : null}
              <TurnTimeline
                segments={turn.segments}
                toolsView={toolsView}
                streaming={streaming}
                conversationId={threadId ?? undefined}
                token={token}
                renderMarkdownLink={renderMarkdownLink}
                formatTextWithCitations={formatTextWithCitations}
              />
            </div>
          ) : null}
          {error ? (
            <div
              role="alert"
              className="flex items-start gap-2 rounded-xl bg-destructive/10 px-3 py-2.5 text-[13px] text-destructive"
            >
              <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden />
              <div className="min-w-0 flex-1">
                <p className="break-words">{t("sideThread.panel.error", { msg: error })}</p>
                <div className="mt-1.5 flex gap-3">
                  {failedInput ? (
                    <button
                      type="button"
                      onClick={() => {
                        chat.dismissError();
                        submit(failedInput);
                      }}
                      className="focus-ring rounded font-semibold underline-offset-2 hover:underline"
                    >
                      {t("sideThread.panel.retry")}
                    </button>
                  ) : null}
                  <button
                    type="button"
                    onClick={chat.dismissError}
                    className="focus-ring rounded text-destructive/80 underline-offset-2 hover:underline"
                  >
                    {t("sideThread.panel.dismiss")}
                  </button>
                </div>
              </div>
            </div>
          ) : null}
        </div>
      </div>

      <form
        className="shrink-0 border-t border-border/70 p-3"
        onSubmit={(e) => {
          e.preventDefault();
          submit(draft);
        }}
      >
        <div className="flex items-end gap-2 rounded-2xl bg-muted/50 py-1.5 pl-3.5 pr-1.5 ring-1 ring-transparent transition-shadow focus-within:ring-ring/50">
          <textarea
            ref={textareaRef}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                submit(draft);
              }
            }}
            rows={1}
            placeholder={t("sideThread.composer.placeholder")}
            aria-label={t("sideThread.composer.placeholder")}
            className="min-h-6 flex-1 resize-none bg-transparent py-1 text-[14px] leading-6 text-foreground outline-none placeholder:text-muted-foreground/80"
          />
          {streaming ? (
            <button
              type="button"
              onClick={() => void chat.stop()}
              className="focus-ring flex size-8 shrink-0 items-center justify-center rounded-full bg-foreground text-background transition-opacity hover:opacity-85"
              aria-label={t("sideThread.composer.stop")}
              title={t("sideThread.composer.stop")}
            >
              <Square className="size-3 fill-current" aria-hidden />
            </button>
          ) : (
            <button
              type="submit"
              disabled={!draft.trim()}
              className="focus-ring flex size-8 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground transition-opacity hover:opacity-90 disabled:bg-muted-foreground/25 disabled:text-background"
              aria-label={t("sideThread.composer.send")}
              title={t("sideThread.composer.send")}
            >
              <ArrowUp className="size-4" aria-hidden />
            </button>
          )}
        </div>
      </form>
    </section>
  );
}
