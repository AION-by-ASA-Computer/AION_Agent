"use client";

import { useSyncExternalStore } from "react";

export const CHAT_FONT_SIZE_STORAGE_KEY = "aion-chat-font-size";
const LEGACY_SCALE_STORAGE_KEY = "aion-chat-font-scale";

export const CHAT_FONT_SIZE_MIN = 12;
export const CHAT_FONT_SIZE_MAX = 18;
export const CHAT_FONT_SIZE_DEFAULT = 14;
export const CHAT_FONT_SIZE_STEP = 1;

/** Fenced code blocks stay smaller than body text but scale with the same slider. */
export const CHAT_CODE_FONT_RATIO = 0.75;

const LEGACY_SCALE_PX: Record<string, number> = {
  small: 13,
  medium: 14,
  large: 15,
};

const listeners = new Set<() => void>();

function notifyFontSizeListeners(): void {
  listeners.forEach((fn) => fn());
}

export function subscribeChatFontSize(fn: () => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function clampChatFontSize(value: number): number {
  const n = Math.round(value);
  return Math.min(CHAT_FONT_SIZE_MAX, Math.max(CHAT_FONT_SIZE_MIN, n));
}

function parseStoredFontSize(raw: string | null): number | null {
  if (!raw) return null;
  const n = Number.parseInt(raw, 10);
  if (Number.isFinite(n)) return clampChatFontSize(n);
  const legacy = LEGACY_SCALE_PX[raw];
  return legacy != null ? legacy : null;
}

export function readChatFontSize(): number {
  if (typeof window === "undefined") return CHAT_FONT_SIZE_DEFAULT;
  try {
    const stored = parseStoredFontSize(localStorage.getItem(CHAT_FONT_SIZE_STORAGE_KEY));
    if (stored != null) return stored;
    const legacy = parseStoredFontSize(localStorage.getItem(LEGACY_SCALE_STORAGE_KEY));
    if (legacy != null) return legacy;
  } catch {
    /* ignore */
  }
  return CHAT_FONT_SIZE_DEFAULT;
}

export function applyChatFontSize(sizePx: number): void {
  const px = clampChatFontSize(sizePx);
  const codePx = Math.round(px * CHAT_CODE_FONT_RATIO * 10) / 10;
  document.documentElement.style.setProperty("--aion-chat-font-size", `${px}px`);
  document.documentElement.style.setProperty("--aion-chat-code-font-size", `${codePx}px`);
  document.documentElement.dataset.chatFontSize = String(px);
  try {
    localStorage.setItem(CHAT_FONT_SIZE_STORAGE_KEY, String(px));
    localStorage.removeItem(LEGACY_SCALE_STORAGE_KEY);
  } catch {
    /* ignore */
  }
  notifyFontSizeListeners();
}

export function useChatFontSize(): [number, (size: number) => void] {
  const size = useSyncExternalStore(
    subscribeChatFontSize,
    readChatFontSize,
    () => CHAT_FONT_SIZE_DEFAULT,
  );
  return [size, applyChatFontSize];
}
