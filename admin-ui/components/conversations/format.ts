import { getLocale } from "@/lib/i18n/i18n-store";

export const toMs = (v: string | number | null | undefined): number => {
  if (v == null) return 0;
  const n = typeof v === "number" ? (v < 1e12 ? v * 1000 : v) : Date.parse(v);
  return Number.isFinite(n) ? n : 0;
};

const startOfDay = (ms: number) => {
  const d = new Date(ms);
  d.setHours(0, 0, 0, 0);
  return d.getTime();
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

export const timeOnly = (ms: number): string =>
  ms ? new Intl.DateTimeFormat(getLocale(), { hour: "2-digit", minute: "2-digit" }).format(ms) : "";

/** Day bucket key + label for grouping the list: today, yesterday, then one bucket per date. */
export function dayBucket(ms: number, t: (k: string) => string, now = Date.now()): { key: string; label: string } {
  const day = startOfDay(ms);
  const today = startOfDay(now);
  if (day === today) return { key: "today", label: t("admin_conversations.list.today") };
  if (day === today - 86400_000) return { key: "yesterday", label: t("admin_conversations.list.yesterday") };
  const sameYear = new Date(ms).getFullYear() === new Date(now).getFullYear();
  const label = new Intl.DateTimeFormat(getLocale(), sameYear ? { day: "numeric", month: "long" } : { day: "numeric", month: "long", year: "numeric" }).format(ms);
  return { key: String(day), label };
}
