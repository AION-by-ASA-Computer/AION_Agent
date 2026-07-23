"use client";

import { useSyncExternalStore } from "react";

export type ChatFontScale = "small" | "medium" | "large";

export const CHAT_FONT_SCALE_STORAGE_KEY = "aion-chat-font-scale";

/** Base chat message size (px). Code blocks and inline code scale via em from this. */
export const CHAT_FONT_SCALE_PX: Record<ChatFontScale, number> = {
  small: 13,
  medium: 14,
  large: 15,
};

const listeners = new Set<() => void>();

function notifyFontScaleListeners(): void {
  listeners.forEach((fn) => fn());
}

export function subscribeChatFontScale(fn: () => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function isChatFontScale(value: unknown): value is ChatFontScale {
  return value === "small" || value === "medium" || value === "large";
}

export function readChatFontScale(): ChatFontScale {
  if (typeof window === "undefined") return "medium";
  try {
    const stored = localStorage.getItem(CHAT_FONT_SCALE_STORAGE_KEY);
    if (isChatFontScale(stored)) return stored;
  } catch {
    /* ignore */
  }
  const attr = document.documentElement.dataset.chatFontScale;
  if (isChatFontScale(attr)) return attr;
  return "medium";
}

export function applyChatFontScale(scale: ChatFontScale): void {
  document.documentElement.dataset.chatFontScale = scale;
  document.documentElement.style.setProperty(
    "--aion-chat-font-size",
    `${CHAT_FONT_SCALE_PX[scale]}px`,
  );
  try {
    localStorage.setItem(CHAT_FONT_SCALE_STORAGE_KEY, scale);
  } catch {
    /* ignore */
  }
  notifyFontScaleListeners();
}

export function useChatFontScale(): [ChatFontScale, (scale: ChatFontScale) => void] {
  const scale = useSyncExternalStore(
    subscribeChatFontScale,
    readChatFontScale,
    () => "medium" as ChatFontScale,
  );
  return [scale, applyChatFontScale];
}
