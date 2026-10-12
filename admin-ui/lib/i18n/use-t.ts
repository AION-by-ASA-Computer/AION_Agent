"use client";

import { useSyncExternalStore } from "react";
import { subscribe, getLocale, t } from "./i18n-store";

export function useT(): typeof t {
  useSyncExternalStore(subscribe, getLocale, () => "it" as const);
  return t;
}
