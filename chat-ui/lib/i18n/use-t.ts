"use client";

/**
 * useT — hook React per accedere alla funzione di traduzione `t()`.
 *
 * Utilizza `useSyncExternalStore` per sottoscriversi allo store della lingua,
 * garantendo che il componente si ri-renderizzi automaticamente ogni volta che
 * la lingua cambia (es. quando l'utente la modifica in Impostazioni).
 *
 * Non richiede alcun Provider. Funziona in qualsiasi Client Component.
 *
 * @example
 * function MyComponent() {
 *   const t = useT();
 *   return <h1>{t("settings.title")}</h1>;
 * }
 *
 * // Con interpolazione:
 *   t("settings.usermd.chars", { count: 342 })
 */

import { useSyncExternalStore } from "react";
import { subscribe, getLocale, t } from "./i18n-store";

export function useT(): typeof t {
  // La subscription garantisce re-render al cambio lingua.
  // Il valore di ritorno (getLocale) viene scartato — serve solo per
  // triggerare il re-render. La funzione t() viene restituita direttamente.
  useSyncExternalStore(subscribe, getLocale, () => "it" as const);
  return t;
}
