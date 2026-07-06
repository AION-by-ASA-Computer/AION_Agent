"use client";

import { useEffect, useState, useSyncExternalStore } from "react";
import { Moon, Sun } from "lucide-react";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";
import { applyChatTheme, readChatTheme, subscribeChatTheme } from "@/lib/theme/chat-theme";

export function ThemeToggle({ className }: { className?: string }) {
  const t = useT();
  const [mounted, setMounted] = useState(false);
  const theme = useSyncExternalStore(subscribeChatTheme, readChatTheme, () => "dark" as const);

  useEffect(() => {
    setMounted(true);
    applyChatTheme(readChatTheme());
  }, []);

  const toggle = () => {
    applyChatTheme(theme === "dark" ? "light" : "dark");
  };

  return (
    <button
      type="button"
      onClick={toggle}
      className={cn(
        "focus-ring rounded-md border border-border bg-muted/40 p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground",
        className
      )}
      aria-label={!mounted || theme === "dark" ? t("theme.toggle.to_light") : t("theme.toggle.to_dark")}
      title={t("theme.toggle.title")}
    >
      {!mounted || theme === "dark" ? (
        <Moon size={16} aria-hidden />
      ) : (
        <Sun size={16} aria-hidden />
      )}
    </button>
  );
}
