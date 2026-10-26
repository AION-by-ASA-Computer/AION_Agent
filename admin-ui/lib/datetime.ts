import { getLocale } from "@/lib/i18n/i18n-store";

export const toMs = (v: string | number | null | undefined): number => {
  if (v == null) return 0;
  const n = typeof v === "number" ? (v < 1e12 ? v * 1000 : v) : Date.parse(v);
  return Number.isFinite(n) ? n : 0;
};

/** "5 min ago" for the last day, a short date after that. */
export function shortWhen(ms: number, now = Date.now()): string {
  if (!ms) return "";
  const loc = getLocale();
  const diff = now - ms;
  if (diff < 24 * 3600_000 && diff > -60_000) {
    const rtf = new Intl.RelativeTimeFormat(loc, { numeric: "auto", style: "short" });
    if (diff < 60_000) return rtf.format(0, "second");
    if (diff < 3600_000) return rtf.format(-Math.round(diff / 60_000), "minute");
    return rtf.format(-Math.round(diff / 3600_000), "hour");
  }
  return new Intl.DateTimeFormat(loc, { day: "numeric", month: "short" }).format(ms);
}

export const fullWhen = (ms: number): string =>
  ms ? new Intl.DateTimeFormat(getLocale(), { dateStyle: "medium", timeStyle: "short" }).format(ms) : "";
