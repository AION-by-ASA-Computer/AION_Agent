/**
 * Build and describe standard 5-field cron expressions for the schedule UI.
 * Keeps logic client-side (no croniter dependency in chat-ui).
 */

export type ScheduleFrequency =
  | "daily"
  | "weekdays"
  | "weekly"
  | "monthly"
  | "hourly"
  | "every_n_minutes"
  | "custom";

export type ScheduleBuilderState = {
  frequency: ScheduleFrequency;
  minute: number;
  hour: number;
  /** 0 = Sunday … 6 = Saturday (cron convention) */
  dayOfWeek: number;
  dayOfMonth: number;
  everyNMinutes: number;
  customExpression: string;
};

export const DEFAULT_SCHEDULE_STATE: ScheduleBuilderState = {
  frequency: "daily",
  minute: 0,
  hour: 9,
  dayOfWeek: 1,
  dayOfMonth: 1,
  everyNMinutes: 15,
  customExpression: "0 9 * * *",
};

export function clampMinute(n: number): number {
  return Math.min(59, Math.max(0, Math.round(n)));
}

export function clampHour(n: number): number {
  return Math.min(23, Math.max(0, Math.round(n)));
}

export function clampDayOfMonth(n: number): number {
  return Math.min(28, Math.max(1, Math.round(n)));
}

export function clampEveryNMinutes(n: number): number {
  const allowed = [5, 10, 15, 20, 30, 60];
  if (allowed.includes(n)) return n;
  return 15;
}

export function buildCronExpression(state: ScheduleBuilderState): string {
  const m = clampMinute(state.minute);
  const h = clampHour(state.hour);
  switch (state.frequency) {
    case "daily":
      return `${m} ${h} * * *`;
    case "weekdays":
      return `${m} ${h} * * 1-5`;
    case "weekly":
      return `${m} ${h} * * ${state.dayOfWeek}`;
    case "monthly":
      return `${m} ${h} ${clampDayOfMonth(state.dayOfMonth)} * *`;
    case "hourly":
      return `${m} * * * *`;
    case "every_n_minutes":
      return `*/${clampEveryNMinutes(state.everyNMinutes)} * * * *`;
    case "custom":
      return (state.customExpression || "").trim() || "0 9 * * *";
    default:
      return `${m} ${h} * * *`;
  }
}

/** Best-effort parse for editing existing jobs. */
export function parseCronExpression(expr: string): ScheduleBuilderState {
  const raw = (expr || "").trim();
  const parts = raw.split(/\s+/);
  if (parts.length !== 5) {
    return { ...DEFAULT_SCHEDULE_STATE, frequency: "custom", customExpression: raw || "0 9 * * *" };
  }
  const [minS, hourS, domS, monS, dowS] = parts;
  const minute = Number.parseInt(minS, 10);
  const hour = Number.parseInt(hourS, 10);

  const everyMin = minS.startsWith("*/") ? Number.parseInt(minS.slice(2), 10) : NaN;
  if (hourS === "*" && domS === "*" && monS === "*" && dowS === "*" && Number.isFinite(everyMin)) {
    return {
      ...DEFAULT_SCHEDULE_STATE,
      frequency: "every_n_minutes",
      everyNMinutes: clampEveryNMinutes(everyMin),
    };
  }

  if (
    domS === "*" &&
    monS === "*" &&
    dowS === "*" &&
    hourS !== "*" &&
    Number.isFinite(minute) &&
    Number.isFinite(hour)
  ) {
    return {
      ...DEFAULT_SCHEDULE_STATE,
      frequency: "daily",
      minute,
      hour,
    };
  }

  if (
    domS === "*" &&
    monS === "*" &&
    dowS === "1-5" &&
    hourS !== "*" &&
    Number.isFinite(minute) &&
    Number.isFinite(hour)
  ) {
    return {
      ...DEFAULT_SCHEDULE_STATE,
      frequency: "weekdays",
      minute,
      hour,
    };
  }

  if (
    domS === "*" &&
    monS === "*" &&
    dowS !== "*" &&
    !dowS.includes("-") &&
    hourS !== "*" &&
    Number.isFinite(minute) &&
    Number.isFinite(hour)
  ) {
    const dow = Number.parseInt(dowS, 10);
    return {
      ...DEFAULT_SCHEDULE_STATE,
      frequency: "weekly",
      minute,
      hour,
      dayOfWeek: Number.isFinite(dow) ? dow : 1,
    };
  }

  if (
    domS !== "*" &&
    monS === "*" &&
    dowS === "*" &&
    hourS !== "*" &&
    Number.isFinite(minute) &&
    Number.isFinite(hour)
  ) {
    const dom = Number.parseInt(domS, 10);
    return {
      ...DEFAULT_SCHEDULE_STATE,
      frequency: "monthly",
      minute,
      hour,
      dayOfMonth: Number.isFinite(dom) ? dom : 1,
    };
  }

  if (hourS === "*" && domS === "*" && monS === "*" && dowS === "*" && Number.isFinite(minute)) {
    return {
      ...DEFAULT_SCHEDULE_STATE,
      frequency: "hourly",
      minute,
    };
  }

  return {
    ...DEFAULT_SCHEDULE_STATE,
    frequency: "custom",
    customExpression: raw,
  };
}

export function isValidCronShape(expr: string): boolean {
  const parts = (expr || "").trim().split(/\s+/);
  return parts.length === 5 && parts.every((p) => p.length > 0);
}

export function formatTime24(hour: number, minute: number): string {
  return `${String(clampHour(hour)).padStart(2, "0")}:${String(clampMinute(minute)).padStart(2, "0")}`;
}
