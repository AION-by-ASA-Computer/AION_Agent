"use client";

import { useMemo } from "react";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";

export function ChatEmptyState({
  profileName,
  userDisplayName,
  className,
}: {
  profileName?: string;
  userDisplayName?: string;
  className?: string;
}) {
  const t = useT();

  const firstName = useMemo(() => {
    if (!userDisplayName) return "";
    const cleaned = userDisplayName.trim();
    if (!cleaned) return "";
    const first = cleaned.split(/\s+/)[0];
    if (!first) return "";
    return first.charAt(0).toUpperCase() + first.slice(1);
  }, [userDisplayName]);

  const greeting = useMemo(() => {
    if (firstName) {
      const template = t("chat.empty.greeting_user", { name: firstName });
      if (template && template !== "chat.empty.greeting_user") {
        return template;
      }
      return `E ora, ${firstName}?`;
    }
    return t("chat.empty.title");
  }, [firstName, t]);

  return (
    <div
      className={cn(
        "relative flex flex-col items-center justify-center text-center px-4 select-none animate-in fade-in-0 zoom-in-95 duration-500",
        className,
      )}
    >
      {/* Ambient glowing radial aura in the center */}
      <div
        className="pointer-events-none absolute left-1/2 top-1/2 -z-10 h-64 w-[min(92vw,38rem)] -translate-x-1/2 -translate-y-1/2 rounded-full bg-primary/20 blur-[90px] transition-all duration-700 dark:bg-primary/[0.24] dark:blur-[110px]"
        aria-hidden
      />

      {/* Main Hero Title - Gemini Style */}
      <h1 className="text-3xl font-medium tracking-tight text-foreground/95 sm:text-4xl md:text-[2.6rem] transition-all duration-300 drop-shadow-xs">
        {greeting}
      </h1>

      {/* Subtle Subtitle */}
      <p className="mt-2.5 max-w-lg text-sm leading-relaxed text-muted-foreground/80 font-normal">
        {profileName
          ? t("chat.empty.subtitle_profile", { profile: profileName })
          : t("chat.empty.subtitle")}
      </p>
    </div>
  );
}
