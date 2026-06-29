/**
 * i18n-store — store globale SSR-safe per la gestione della lingua.
 *
 * Basato sullo stesso pattern di `lib/layout/dock-width-store.ts` e
 * `lib/auth/use-stored-auth.ts` già presenti nel codebase:
 * usa `useSyncExternalStore` per propagare i cambiamenti a tutti i
 * componenti React senza bisogno di un Provider.
 *
 * La lingua viene letta/scritta in localStorage alla chiave
 * "aion_chat_language" (stessa chiave già usata in settings/page.tsx).
 */

import it from "./locales/it.json";
import en from "./locales/en.json";
import es from "./locales/es.json";
import fr from "./locales/fr.json";
import de from "./locales/de.json";

// ─── Tipi ────────────────────────────────────────────────────────────────────

export type Locale = "it" | "en" | "es" | "fr" | "de";

type NestedDict = { [key: string]: string | NestedDict };

// ─── Dizionari ───────────────────────────────────────────────────────────────

const DICTIONARIES: Record<Locale, NestedDict> = { it, en, es, fr, de };

const SUPPORTED_LOCALES: Locale[] = ["it", "en", "es", "fr", "de"];
const STORAGE_KEY = "aion_chat_language";
const DEFAULT_LOCALE: Locale = "en";

// ─── Stato interno ───────────────────────────────────────────────────────────

let currentLocale: Locale = DEFAULT_LOCALE;
const listeners = new Set<() => void>();

function notifyListeners(): void {
  listeners.forEach((fn) => fn());
}

function isValidLocale(value: unknown): value is Locale {
  return SUPPORTED_LOCALES.includes(value as Locale);
}

/** Map ``navigator.language`` to a supported chat locale (fallback ``en``). */
export function detectBrowserLocale(): Locale {
  if (typeof navigator === "undefined") return DEFAULT_LOCALE;
  const primary = (navigator.language || "").split("-")[0]?.toLowerCase();
  if (isValidLocale(primary)) return primary;
  for (const lang of navigator.languages || []) {
    const code = String(lang).split("-")[0]?.toLowerCase();
    if (isValidLocale(code)) return code;
  }
  return DEFAULT_LOCALE;
}

/**
 * Inizializza la lingua dal localStorage.
 * Da chiamare lato client post-idratazione (es. in un useEffect) per evitare hydration mismatch.
 */
export function initLocaleFromStorage(): void {
  if (typeof window === "undefined") return;
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (isValidLocale(stored)) {
      currentLocale = stored;
      notifyListeners();
      return;
    }
    const detected = detectBrowserLocale();
    currentLocale = detected;
    localStorage.setItem(STORAGE_KEY, detected);
    notifyListeners();
  } catch {
    // ignore — localStorage non disponibile (es. iframe sandboxed)
  }
}

// ─── API pubblica ─────────────────────────────────────────────────────────────

/** Registra un listener per i cambiamenti di lingua (per useSyncExternalStore). */
export function subscribe(fn: () => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

/** Restituisce la lingua corrente (snapshot per useSyncExternalStore). */
export function getLocale(): Locale {
  return currentLocale;
}

/**
 * Imposta la lingua corrente e aggiorna localStorage.
 * Notifica tutti i componenti in ascolto.
 * Chiamare questa funzione da `handleSaveLanguage` in settings/page.tsx.
 */
export function setLocale(locale: Locale): void {
  if (!isValidLocale(locale)) return;
  currentLocale = locale;
  try {
    localStorage.setItem(STORAGE_KEY, locale);
  } catch {
    // ignore
  }
  notifyListeners();
}

// ─── Funzione t() ─────────────────────────────────────────────────────────────

/**
 * Risolve un path dotted su un dizionario nested.
 * Esempio: get(dict, "settings.tab.account") → "Profilo & Account"
 */
function getNestedValue(dict: NestedDict, path: string): string | undefined {
  const keys = path.split(".");
  let current: string | NestedDict = dict;
  for (const key of keys) {
    if (typeof current !== "object" || current === null) return undefined;
    current = (current as NestedDict)[key];
  }
  return typeof current === "string" ? current : undefined;
}

/**
 * Interpola variabili nel formato `{{nome}}` nella stringa tradotta.
 * Esempio: t("settings.usermd.chars", { count: 42 }) → "42 / 1400 caratteri"
 */
function interpolate(template: string, vars?: Record<string, string | number>): string {
  if (!vars) return template;
  return template.replace(/\{\{(\w+)\}\}/g, (_, key) =>
    vars[key] !== undefined ? String(vars[key]) : `{{${key}}}`
  );
}

/**
 * Traduce una chiave dotted nella lingua corrente, con fallback a IT.
 *
 * @param key   - Chiave dotted, es. "settings.tab.account"
 * @param vars  - Variabili da interpolare, es. { count: 42 }
 * @returns     - Stringa tradotta, o la chiave stessa se non trovata
 *
 * @example
 * t("settings.title")                           // "User Settings" (EN)
 * t("settings.usermd.chars", { count: 342 })   // "342 / 1400 characters" (EN)
 */
export function t(key: string, vars?: Record<string, string | number>): string {
  const dict = DICTIONARIES[currentLocale];
  const value = getNestedValue(dict, key);

  if (value !== undefined) {
    return interpolate(value, vars);
  }

  // Fallback a inglese se la chiave non è tradotta nella lingua corrente
  if (currentLocale !== DEFAULT_LOCALE) {
    const fallback = getNestedValue(DICTIONARIES[DEFAULT_LOCALE], key);
    if (fallback !== undefined) {
      return interpolate(fallback, vars);
    }
  }

  // Ultima risorsa: restituisce la chiave stessa (segnala chiave mancante)
  return key;
}
