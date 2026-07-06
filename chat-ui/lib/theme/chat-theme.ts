"use client";

import { useSyncExternalStore } from "react";

export type ChatTheme = "dark" | "light";

export const CHAT_THEME_STORAGE_KEY = "aion-chat-theme";

const listeners = new Set<() => void>();

function notifyThemeListeners(): void {
  listeners.forEach((fn) => fn());
}

export function subscribeChatTheme(fn: () => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function readChatTheme(): ChatTheme {
  if (typeof window === "undefined") return "dark";
  try {
    const stored = localStorage.getItem(CHAT_THEME_STORAGE_KEY);
    if (stored === "light" || stored === "dark") return stored;
  } catch {
    /* ignore */
  }
  return document.documentElement.dataset.theme === "light" ? "light" : "dark";
}

export function applyChatTheme(theme: ChatTheme): void {
  document.documentElement.dataset.theme = theme;
  try {
    localStorage.setItem(CHAT_THEME_STORAGE_KEY, theme);
  } catch {
    /* ignore */
  }
  notifyThemeListeners();
}

export function useChatTheme(): [ChatTheme, (theme: ChatTheme) => void] {
  const theme = useSyncExternalStore(subscribeChatTheme, readChatTheme, () => "dark" as ChatTheme);
  const setTheme = (next: ChatTheme) => applyChatTheme(next);
  return [theme, setTheme];
}
