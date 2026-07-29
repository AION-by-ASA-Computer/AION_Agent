"use client";

import { useCallback, useState } from "react";
import { Brain, Check, Copy, RotateCw, ThumbsDown, ThumbsUp } from "lucide-react";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";
import type { MessageRating } from "@/lib/message-feedback";

type Props = {
  messageId: string;
  copyText: string;
  rating?: MessageRating | null;
  onRate?: (messageId: string, rating: MessageRating | null) => void;
  onRegenerate?: () => void;
  showRegenerate?: boolean;
  /** Last assistant message keeps actions visible (OpenWebUI pattern). */
  pinned?: boolean;
  className?: string;
  onMemorize?: () => void;
};

function ActionButton({
  label,
  onClick,
  active,
  disabled,
  children,
  className,
}: {
  label: string;
  onClick: () => void;
  active?: boolean;
  disabled?: boolean;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "rounded-lg p-1.5 text-muted-foreground transition-colors relative",
        "hover:bg-foreground/5 hover:text-foreground",
        "disabled:cursor-not-allowed disabled:opacity-50",
        active && "bg-muted text-foreground",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        className,
      )}
    >
      {children}
    </button>
  );
}

export function MessageActions({
  messageId,
  copyText,
  rating = null,
  onRate,
  onRegenerate,
  showRegenerate = false,
  pinned = false,
  className,
  onMemorize,
}: Props) {
  const t = useT();
  const [copied, setCopied] = useState(false);
  const [animateLike, setAnimateLike] = useState(false);
  const [animateDislike, setAnimateDislike] = useState(false);

  const handleCopy = useCallback(async () => {
    const text = (copyText || "").trim();
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      /* fallback ignored */
    }
  }, [copyText]);

  const visibility = pinned
    ? "opacity-100"
    : "opacity-100 lg:opacity-0 lg:group-hover:opacity-100 lg:group-focus-within:opacity-100 focus-within:opacity-100";

  return (
    <div
      className={cn(
        "flex items-center gap-0.5 transition-opacity duration-150",
        visibility,
        className,
      )}
    >
      <ActionButton
        label={copied ? t("chat.actions.copied") : t("chat.actions.copy")}
        onClick={() => void handleCopy()}
        disabled={!copyText.trim()}
      >
        {copied ? <Check className="size-4" aria-hidden /> : <Copy className="size-4" aria-hidden />}
      </ActionButton>

      {onRate ? (
        <>
          <ActionButton
            label={t("chat.actions.good")}
            active={false}
            onClick={() => {
              setAnimateLike(true);
              setTimeout(() => setAnimateLike(false), 450);
              onRate(messageId, rating === 1 ? null : 1);
            }}
            className={cn(
              rating === 1 && "bg-emerald-500/10 text-emerald-500 border border-emerald-500/20 hover:text-emerald-400 hover:bg-emerald-500/20"
            )}
          >
            {animateLike && (
              <>
                <span className="absolute inset-0 rounded-lg bg-emerald-500/50 animate-ping pointer-events-none" />
                <span className="absolute left-1/2 top-1/2 w-1 h-1 bg-emerald-400 rounded-full animate-sparkle-1 pointer-events-none" />
                <span className="absolute left-1/2 top-1/2 w-1 h-1 bg-emerald-400 rounded-full animate-sparkle-2 pointer-events-none" />
                <span className="absolute left-1/2 top-1/2 w-1 h-1 bg-emerald-400 rounded-full animate-sparkle-3 pointer-events-none" />
                <span className="absolute left-1/2 top-1/2 w-1 h-1 bg-emerald-400 rounded-full animate-sparkle-4 pointer-events-none" />
              </>
            )}
            <ThumbsUp
              className={cn(
                "size-4 transition-transform",
                rating === 1 && "fill-current text-emerald-500",
                animateLike && "animate-pop-bounce text-emerald-500"
              )}
              aria-hidden
            />
          </ActionButton>
          <ActionButton
            label={t("chat.actions.bad")}
            active={false}
            onClick={() => {
              setAnimateDislike(true);
              setTimeout(() => setAnimateDislike(false), 450);
              onRate(messageId, rating === -1 ? null : -1);
            }}
            className={cn(
              rating === -1 && "bg-red-500/10 text-red-500 border border-red-500/20 hover:text-red-400 hover:bg-red-500/20"
            )}
          >
            {animateDislike && (
              <>
                <span className="absolute inset-0 rounded-lg bg-red-500/50 animate-ping pointer-events-none" />
                <span className="absolute left-1/2 top-1/2 w-1 h-1 bg-red-400 rounded-full animate-sparkle-1 pointer-events-none" />
                <span className="absolute left-1/2 top-1/2 w-1 h-1 bg-red-400 rounded-full animate-sparkle-2 pointer-events-none" />
                <span className="absolute left-1/2 top-1/2 w-1 h-1 bg-red-400 rounded-full animate-sparkle-3 pointer-events-none" />
                <span className="absolute left-1/2 top-1/2 w-1 h-1 bg-red-400 rounded-full animate-sparkle-4 pointer-events-none" />
              </>
            )}
            <ThumbsDown
              className={cn(
                "size-4 transition-transform",
                rating === -1 && "fill-current text-red-500",
                animateDislike && "animate-pop-bounce text-red-500"
              )}
              aria-hidden
            />
          </ActionButton>
        </>
      ) : null}

      {showRegenerate && onRegenerate ? (
        <ActionButton label={t("chat.actions.regenerate")} onClick={onRegenerate}>
          <RotateCw className="size-4" aria-hidden />
        </ActionButton>
      ) : null}

      {onMemorize ? (
        <ActionButton label={t("chat.actions.memorize")} onClick={onMemorize}>
          <Brain className="size-4" aria-hidden />
        </ActionButton>
      ) : null}
    </div>
  );
}
