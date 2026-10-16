/**
 * i18n-store — store globale SSR-safe per la gestione della lingua in Admin UI.
 *
 * Basato sul pattern di useSyncExternalStore per propagare i cambiamenti a tutti i
 * componenti React senza bisogno di un Provider.
 *
 * Risolve la lingua preferita dell'utente loggato:
 * 1. Metadata utente da /auth/me (users.metadata_json.language)
 * 2. localStorage: "aion_admin_language" (o fallback su "aion_chat_language")
 * 3. Browser navigator.language
 * 4. Fallback predefinito: "it" / "en"
 */

import it from "./locales/it.json";
import en from "./locales/en.json";
import es from "./locales/es.json";
import fr from "./locales/fr.json";
import de from "./locales/de.json";
import { getStoredToken } from "@/lib/auth/storage";
import { apiBase } from "@/lib/api";

export type Locale = "it" | "en" | "es" | "fr" | "de";

type NestedDict = { [key: string]: string | NestedDict };

const DICTIONARIES: Record<Locale, NestedDict> = { it, en, es, fr, de };
const SUPPORTED_LOCALES: Locale[] = ["it", "en", "es", "fr", "de"];
const ADMIN_STORAGE_KEY = "aion_admin_language";
const CHAT_STORAGE_KEY = "aion_chat_language";
const DEFAULT_LOCALE: Locale = "it";

let currentLocale: Locale = DEFAULT_LOCALE;
const listeners = new Set<() => void>();

function notifyListeners(): void {
  listeners.forEach((fn) => fn());
}

export function isValidLocale(value: unknown): value is Locale {
  return SUPPORTED_LOCALES.includes(value as Locale);
}

/** Map navigator.language to a supported locale (fallback it / en). */
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
 * Inizializza la lingua all'avvio dal localStorage e dal profilo utente /auth/me.
 */
export function initLocaleFromStorage(): void {
  if (typeof window === "undefined") return;

  try {
    const adminStored = localStorage.getItem(ADMIN_STORAGE_KEY);
    if (isValidLocale(adminStored)) {
      currentLocale = adminStored;
      notifyListeners();
    } else {
      const chatStored = localStorage.getItem(CHAT_STORAGE_KEY);
      if (isValidLocale(chatStored)) {
        currentLocale = chatStored;
        localStorage.setItem(ADMIN_STORAGE_KEY, chatStored);
        notifyListeners();
      } else {
        const detected = detectBrowserLocale();
        currentLocale = detected;
        localStorage.setItem(ADMIN_STORAGE_KEY, detected);
        notifyListeners();
      }
    }
  } catch {
    // ignore
  }

  // Verifica asincrona dal profilo utente se presente token
  const token = getStoredToken();
  if (token) {
    void fetch(`${apiBase()}/auth/me`, {
      headers: { Authorization: `Bearer ${token}` },
      cache: "no-store",
    })
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        const userLang = data?.metadata?.language;
        if (isValidLocale(userLang) && userLang !== currentLocale) {
          setLocale(userLang);
        }
      })
      .catch(() => {
        // ignore network error
      });
  }
}

/** Sottoscrizione per useSyncExternalStore. */
export function subscribe(fn: () => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

/** Snapshot corrente della lingua. */
export function getLocale(): Locale {
  return currentLocale;
}

/** Imposta la lingua e aggiorna localStorage e listener. */
export function setLocale(locale: Locale): void {
  if (!isValidLocale(locale)) return;
  currentLocale = locale;
  try {
    localStorage.setItem(ADMIN_STORAGE_KEY, locale);
  } catch {
    // ignore
  }
  notifyListeners();
}

/** Risolve un path punteggiato su un dizionario nested. */
function getNestedValue(dict: NestedDict, path: string): string | undefined {
  const keys = path.split(".");
  let current: string | NestedDict = dict;
  for (const key of keys) {
    if (typeof current !== "object" || current === null) return undefined;
    current = (current as NestedDict)[key];
  }
  return typeof current === "string" ? current : undefined;
}

/** Interpola variabili {{nome}} nella stringa. */
function interpolate(template: string, vars?: Record<string, string | number>): string {
  if (!vars) return template;
  return template.replace(/\{\{(\w+)\}\}/g, (_, key) =>
    vars[key] !== undefined ? String(vars[key]) : `{{${key}}}`
  );
}

/** Traduce una chiave dotted nella lingua corrente con fallback su EN e IT. */
export function t(key: string, vars?: Record<string, string | number>): string {
  const dict = DICTIONARIES[currentLocale];
  const value = getNestedValue(dict, key);
  if (value !== undefined) {
    return interpolate(value, vars);
  }

  // Fallback EN
  if (currentLocale !== "en") {
    const fallbackEn = getNestedValue(DICTIONARIES.en, key);
    if (fallbackEn !== undefined) {
      return interpolate(fallbackEn, vars);
    }
  }

  // Fallback IT
  if (currentLocale !== "it") {
    const fallbackIt = getNestedValue(DICTIONARIES.it, key);
    if (fallbackIt !== undefined) {
      return interpolate(fallbackIt, vars);
    }
  }

  return key;
}
