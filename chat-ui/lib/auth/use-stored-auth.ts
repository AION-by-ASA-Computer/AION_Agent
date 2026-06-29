"use client";

import { useSyncExternalStore } from "react";
import { getStoredToken, getStoredUserId } from "./storage";

function subscribe(listener: () => void): () => void {
  if (typeof window === "undefined") return () => {};
  window.addEventListener("storage", listener);
  return () => window.removeEventListener("storage", listener);
}

/** Allinea SSR/primo paint (`default`) con lettura da localStorage dopo l’idratazione. */
export function useStoredUserId(): string {
  return useSyncExternalStore(
    subscribe,
    () => getStoredUserId() || "default",
    () => "default"
  );
}

export function useStoredToken(): string | null {
  return useSyncExternalStore(subscribe, () => getStoredToken(), () => null);
}
