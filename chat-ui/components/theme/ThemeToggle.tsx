"use client";

import { Moon, Sun } from "lucide-react";
import { useState, useEffect } from "react";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";

const STORAGE_KEY = "aion-chat-theme";

function readTheme(): "dark" | "light" {
  if (typeof window === "undefined") return "dark";
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === "light" || stored === "dark") return stored;
  } catch {
    /* ignore */
  }
  return document.documentElement.dataset.theme === "light" ? "light" : "dark";
}

export function ThemeToggle({ className }: { className?: string }) {
  const t = useT();
  const [mounted, setMounted] = useState(false);
  const [theme, setTheme] = useState<"dark" | "light">("dark");

  useEffect(() => {
    setMounted(true);
    const initial = readTheme();
    setTheme(initial);
    // Assicurati che il DOM rifletta lo stato (evita reset da idratazione React)
    document.documentElement.dataset.theme = initial;
  }, []);

  const toggle = () => {
    const next = theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      /* ignore */
    }
    setTheme(next);
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
