export type Tone = "success" | "warning" | "destructive";

/** Score bands match the backend's pass threshold (60). */
export const scoreTone = (score: number): Tone => (score >= 80 ? "success" : score >= 60 ? "warning" : "destructive");

export const toneText: Record<Tone, string> = {
  success: "text-success",
  warning: "text-warning",
  destructive: "text-destructive",
};

export const toneBar: Record<Tone, string> = {
  success: "bg-success",
  warning: "bg-warning",
  destructive: "bg-destructive",
};

export const kb = (bytes: number, locale: string) =>
  `${new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }).format((bytes || 0) / 1024)} KB`;

export const clock = (iso: string | undefined, locale: string) => {
  const d = iso ? new Date(iso) : null;
  return d && !Number.isNaN(d.getTime()) ? new Intl.DateTimeFormat(locale, { timeStyle: "medium" }).format(d) : "";
};

export const stamp = (iso: string, locale: string) => {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "short" }).format(d);
};

export const cleanFilePath = (raw: string) => raw.replace(/^file:\/\/\/?(app\/)?/i, "").replace(/^[./\\]+/, "");
