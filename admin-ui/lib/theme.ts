"use client";

import { useSyncExternalStore } from "react";

export type Theme = "light" | "dark";

const KEY = "aion-admin-theme";
const listeners = new Set<() => void>();

function read(): Theme {
  return document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark";
}

export function setTheme(theme: Theme): void {
  document.documentElement.setAttribute("data-theme", theme);
  try {
    localStorage.setItem(KEY, theme);
  } catch {
    // storage unavailable: the choice lasts for this page only
  }
  listeners.forEach((fn) => fn());
}

function subscribe(fn: () => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function useTheme(): Theme {
  return useSyncExternalStore(subscribe, read, () => "dark");
}
