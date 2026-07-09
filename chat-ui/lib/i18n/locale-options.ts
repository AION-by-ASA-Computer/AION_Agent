import type { Locale } from "./i18n-store";

export const LOCALE_OPTIONS: ReadonlyArray<{
  code: Locale;
  name: string;
  flag: string;
}> = [
  { code: "it", name: "Italiano", flag: "🇮🇹" },
  { code: "en", name: "English", flag: "🇬🇧" },
  { code: "es", name: "Español", flag: "🇪🇸" },
  { code: "fr", name: "Français", flag: "🇫🇷" },
  { code: "de", name: "Deutsch", flag: "🇩🇪" },
];

export function localeOption(code: Locale) {
  return LOCALE_OPTIONS.find((opt) => opt.code === code) ?? LOCALE_OPTIONS[1];
}
