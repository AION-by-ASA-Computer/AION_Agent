"use client";

import { Paperclip, Sparkles } from "lucide-react";

import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";

const SUGGESTION_KEYS = [
  "chat.empty.suggestions.explain",
  "chat.empty.suggestions.plan",
  "chat.empty.suggestions.attach",
  "chat.empty.suggestions.research",
] as const;

export function ChatEmptyState({
  onSuggestion,
  profileName,
  className,
}: {
  onSuggestion?: (text: string) => void;
  profileName?: string;
  className?: string;
}) {
  const t = useT();

  return (
    <div
      className={cn(
        "flex min-h-[min(52vh,28rem)] flex-col items-center justify-center px-4 py-10 text-center sm:px-6",
        className,
      )}
    >
      <div
        className="mb-5 flex size-14 items-center justify-center rounded-full border border-primary/15 bg-primary/8 shadow-[0_0_40px_-12px_hsl(var(--primary)/0.45)]"
        aria-hidden
      >
        <Sparkles className="size-6 text-primary" />
      </div>

      <h2 className="text-2xl font-semibold tracking-tight text-foreground sm:text-[1.65rem]">
        {t("chat.empty.title")}
      </h2>

      <p className="mt-2.5 max-w-md text-sm leading-relaxed text-muted-foreground">
        {profileName
          ? t("chat.empty.subtitle_profile", { profile: profileName })
          : t("chat.empty.subtitle")}
      </p>

      <div className="mt-3 inline-flex items-center gap-1.5 rounded-full border border-border/60 bg-muted/25 px-3 py-1 text-[0.786em] text-muted-foreground">
        <Paperclip size={12} aria-hidden />
        <span>{t("chat.empty.hint_attach")}</span>
      </div>

      <div className="mt-8 grid w-full max-w-2xl grid-cols-1 gap-2.5 sm:grid-cols-2">
        {SUGGESTION_KEYS.map((key) => {
          const text = t(key);
          return (
            <button
              key={key}
              type="button"
              onClick={() => onSuggestion?.(text)}
              className="group rounded-2xl border border-border/70 bg-card/35 px-4 py-3.5 text-left text-sm text-foreground shadow-sm backdrop-blur-sm transition hover:border-primary/35 hover:bg-card/60 hover:shadow-md"
            >
              <span className="block leading-snug text-foreground/90 group-hover:text-foreground">
                {text}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
