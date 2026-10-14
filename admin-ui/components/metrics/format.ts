/** Locale-aware number and time formatting shared by the metrics page. */
export function makeFormat(locale: string) {
  const int = new Intl.NumberFormat(locale);
  const compact = new Intl.NumberFormat(locale, { notation: "compact", maximumFractionDigits: 1 });
  const dec = new Intl.NumberFormat(locale, { maximumFractionDigits: 1 });
  return {
    int: (n: number | undefined) => (n === undefined ? "—" : int.format(n)),
    compact: (n: number | undefined) => (n === undefined ? "—" : compact.format(n)),
    seconds: (n: number | undefined) => (n === undefined ? "—" : `${dec.format(n)} s`),
    percent: (n: number | undefined) => (n === undefined ? "—" : `${dec.format(n)}%`),
  };
}
export type Format = ReturnType<typeof makeFormat>;

export function formatStamp(ts: string | undefined, range: string, locale: string): string {
  if (!ts) return "";
  const d = new Date(ts);
  if (isNaN(d.getTime())) return ts;
  const long = range === "7d" || range === "30d" || range === "all";
  return new Intl.DateTimeFormat(
    locale,
    long
      ? { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }
      : { hour: "2-digit", minute: "2-digit" },
  ).format(d);
}

/** Reliability bands for a success rate: the only place state colour is earned. */
export function rateTone(rate: number): "ok" | "warn" | "bad" {
  return rate >= 95 ? "ok" : rate >= 80 ? "warn" : "bad";
}
