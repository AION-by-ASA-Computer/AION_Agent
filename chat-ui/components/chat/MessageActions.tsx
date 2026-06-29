"use client";

import { useCallback, useState } from "react";
import { Check, Copy, RotateCw, ThumbsDown, ThumbsUp } from "lucide-react";
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
};

function ActionButton({
  label,
  onClick,
  active,
  disabled,
  children,
}: {
  label: string;
  onClick: () => void;
  active?: boolean;
  disabled?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "rounded-lg p-1.5 text-muted-foreground transition-colors",
        "hover:bg-foreground/5 hover:text-foreground",
        "disabled:cursor-not-allowed disabled:opacity-50",
        active && "bg-muted text-foreground",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
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
}: Props) {
  const t = useT();
  const [copied, setCopied] = useState(false);

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
            active={rating === 1}
            onClick={() => onRate(messageId, rating === 1 ? null : 1)}
          >
            <ThumbsUp className="size-4" aria-hidden />
          </ActionButton>
          <ActionButton
            label={t("chat.actions.bad")}
            active={rating === -1}
            onClick={() => onRate(messageId, rating === -1 ? null : -1)}
          >
            <ThumbsDown className="size-4" aria-hidden />
          </ActionButton>
        </>
      ) : null}

      {showRegenerate && onRegenerate ? (
        <ActionButton label={t("chat.actions.regenerate")} onClick={onRegenerate}>
          <RotateCw className="size-4" aria-hidden />
        </ActionButton>
      ) : null}
    </div>
  );
}
