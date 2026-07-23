"use client";

import { useSyncExternalStore } from "react";

function subscribeMq(query: string, cb: () => void) {
  const mq = window.matchMedia(query);
  mq.addEventListener("change", cb);
  return () => mq.removeEventListener("change", cb);
}

function getMq(query: string) {
  return () => window.matchMedia(query).matches;
}

/** `true` when viewport is at least Tailwind `lg` (1024px). */
export function useIsLgUp(): boolean {
  return useSyncExternalStore(
    (cb) => subscribeMq("(min-width: 1024px)", cb),
    getMq("(min-width: 1024px)"),
    () => true,
  );
}
