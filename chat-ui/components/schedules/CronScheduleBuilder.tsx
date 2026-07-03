"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { AppSelect } from "@/components/ui/radix-select";
import { cn } from "@/lib/cn";
import {
  buildCronExpression,
  clampDayOfMonth,
  clampEveryNMinutes,
  clampHour,
  clampMinute,
  formatTime24,
  isValidCronShape,
  parseCronExpression,
  type ScheduleBuilderState,
  type ScheduleFrequency,
} from "@/lib/cron/schedule-builder";
import { useT } from "@/lib/i18n/use-t";

const inputClass =
  "focus-ring w-full rounded-lg border border-input bg-background px-3 py-2 text-sm";

type Props = {
  /** Initial cron when the dialog opens; reset parent `key` to re-mount. */
  initialValue: string;
  onChange: (cronExpression: string) => void;
  timezone?: string;
  className?: string;
};

export function CronScheduleBuilder({ initialValue, onChange, timezone, className }: Props) {
  const t = useT();
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;

  const [state, setState] = useState<ScheduleBuilderState>(() => parseCronExpression(initialValue));
  const [mode, setMode] = useState<"simple" | "advanced">(() =>
    parseCronExpression(initialValue).frequency === "custom" ? "advanced" : "simple",
  );

  const expression = useMemo(() => buildCronExpression(state), [state]);
  const valid = isValidCronShape(expression);

  // In simple mode, if state.frequency is "custom" (e.g. after switching back from
  // Advanced), treat it as "daily" so the dropdown and the secondary controls are
  // always in sync. Without this, the dropdown would display "Every day" while the
  // hour/minute selects would be hidden because the raw state.frequency is "custom".
  const effectiveFrequency: ScheduleFrequency =
    mode === "simple" && state.frequency === "custom" ? "daily" : state.frequency;

  // Notify parent after state changes — never inside setState updaters (React 19).
  useEffect(() => {
    if (mode === "simple") {
      onChangeRef.current(buildCronExpression(state));
    }
  }, [state, mode]);

  function patch(partial: Partial<ScheduleBuilderState>) {
    setState((prev) => ({ ...prev, ...partial }));
  }

  function setFrequency(frequency: ScheduleFrequency) {
    setState((prev) => ({ ...prev, frequency }));
    if (frequency !== "custom") setMode("simple");
  }

  const summaryKey = `schedulesPage.cron.summary.${effectiveFrequency}` as const;
  const summaryVars: Record<string, string | number> = {
    time: formatTime24(state.hour, state.minute),
    day: t(`schedulesPage.cron.weekday.${state.dayOfWeek}`),
    dom: state.dayOfMonth,
    n: state.everyNMinutes,
    minute: state.minute,
  };
  const summary = t(summaryKey, summaryVars);

  const frequencyItems = [
    { value: "daily", label: t("schedulesPage.cron.freq.daily") },
    { value: "weekdays", label: t("schedulesPage.cron.freq.weekdays") },
    { value: "weekly", label: t("schedulesPage.cron.freq.weekly") },
    { value: "monthly", label: t("schedulesPage.cron.freq.monthly") },
    { value: "hourly", label: t("schedulesPage.cron.freq.hourly") },
    { value: "every_n_minutes", label: t("schedulesPage.cron.freq.every_n_minutes") },
  ];

  const weekdayItems = [0, 1, 2, 3, 4, 5, 6].map((d) => ({
    value: String(d),
    label: t(`schedulesPage.cron.weekday.${d}`),
  }));

  const minuteItems = Array.from({ length: 12 }, (_, i) => i * 5).map((m) => ({
    value: String(m),
    label: String(m).padStart(2, "0"),
  }));

  const hourItems = Array.from({ length: 24 }, (_, h) => ({
    value: String(h),
    label: `${String(h).padStart(2, "0")}:00`,
  }));

  const domItems = Array.from({ length: 28 }, (_, i) => i + 1).map((d) => ({
    value: String(d),
    label: String(d),
  }));

  const everyNItems = [5, 10, 15, 20, 30, 60].map((n) => ({
    value: String(n),
    label: t("schedulesPage.cron.every_n_label", { n }),
  }));

  return (
    <div className={cn("space-y-4", className)}>
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => {
            // If coming back from Advanced mode, reset state.frequency to "daily"
            // so the simple-mode controls are visible immediately without needing
            // to interact with the frequency dropdown first.
            if (state.frequency === "custom") {
              setState((prev) => ({ ...prev, frequency: "daily" }));
            }
            setMode("simple");
          }}
          className={cn(
            "focus-ring rounded-full px-3 py-1 text-xs font-medium transition-colors",
            mode === "simple"
              ? "bg-primary text-primary-foreground"
              : "bg-muted text-muted-foreground hover:text-foreground",
          )}
        >
          {t("schedulesPage.cron.mode_simple")}
        </button>
        <button
          type="button"
          onClick={() => {
            setMode("advanced");
            setState((prev) => ({
              ...prev,
              frequency: "custom",
              customExpression: expression,
            }));
            onChangeRef.current(expression);
          }}
          className={cn(
            "focus-ring rounded-full px-3 py-1 text-xs font-medium transition-colors",
            mode === "advanced"
              ? "bg-primary text-primary-foreground"
              : "bg-muted text-muted-foreground hover:text-foreground",
          )}
        >
          {t("schedulesPage.cron.mode_advanced")}
        </button>
      </div>

      {mode === "simple" ? (
        <div className="space-y-4 rounded-lg border border-border bg-muted/20 p-4">
          <div>
            <label className="mb-1 block text-sm font-medium">
              {t("schedulesPage.cron.freq_label")}
            </label>
            <AppSelect
              value={effectiveFrequency}
              onValueChange={(v) => setFrequency(v as ScheduleFrequency)}
              items={frequencyItems}
              triggerClassName="w-full max-w-none"
              aria-label={t("schedulesPage.cron.freq_label")}
            />
          </div>

          {(effectiveFrequency === "daily" ||
            effectiveFrequency === "weekdays" ||
            effectiveFrequency === "weekly" ||
            effectiveFrequency === "monthly") && (
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="mb-1 block text-sm font-medium">
                  {t("schedulesPage.cron.hour_label")}
                </label>
                <AppSelect
                  value={String(clampHour(state.hour))}
                  onValueChange={(v) => patch({ hour: clampHour(Number(v)) })}
                  items={hourItems}
                  triggerClassName="w-full max-w-none"
                />
              </div>
              <div>
                <label className="mb-1 block text-sm font-medium">
                  {t("schedulesPage.cron.minute_label")}
                </label>
                <AppSelect
                  value={String(clampMinute(state.minute))}
                  onValueChange={(v) => patch({ minute: clampMinute(Number(v)) })}
                  items={minuteItems}
                  triggerClassName="w-full max-w-none"
                />
              </div>
            </div>
          )}

          {effectiveFrequency === "weekly" && (
            <div>
              <label className="mb-1 block text-sm font-medium">
                {t("schedulesPage.cron.weekday_label")}
              </label>
              <AppSelect
                value={String(state.dayOfWeek)}
                onValueChange={(v) => patch({ dayOfWeek: Number(v) })}
                items={weekdayItems}
                triggerClassName="w-full max-w-none"
              />
            </div>
          )}

          {effectiveFrequency === "monthly" && (
            <div>
              <label className="mb-1 block text-sm font-medium">
                {t("schedulesPage.cron.dom_label")}
              </label>
              <AppSelect
                value={String(clampDayOfMonth(state.dayOfMonth))}
                onValueChange={(v) => patch({ dayOfMonth: clampDayOfMonth(Number(v)) })}
                items={domItems}
                triggerClassName="w-full max-w-none"
              />
            </div>
          )}

          {effectiveFrequency === "hourly" && (
            <div>
              <label className="mb-1 block text-sm font-medium">
                {t("schedulesPage.cron.minute_label")}
              </label>
              <AppSelect
                value={String(clampMinute(state.minute))}
                onValueChange={(v) => patch({ minute: clampMinute(Number(v)) })}
                items={minuteItems}
                triggerClassName="w-full max-w-none"
              />
            </div>
          )}

          {effectiveFrequency === "every_n_minutes" && (
            <div>
              <label className="mb-1 block text-sm font-medium">
                {t("schedulesPage.cron.interval_label")}
              </label>
              <AppSelect
                value={String(clampEveryNMinutes(state.everyNMinutes))}
                onValueChange={(v) => patch({ everyNMinutes: clampEveryNMinutes(Number(v)) })}
                items={everyNItems}
                triggerClassName="w-full max-w-none"
              />
            </div>
          )}
        </div>
      ) : (
        <div className="space-y-2">
          <label className="block text-sm font-medium">{t("schedulesPage.cron.advanced_label")}</label>
          <input
            className={cn(inputClass, "font-mono")}
            value={state.customExpression}
            onChange={(e) => {
              const v = e.target.value;
              setState((prev) => ({ ...prev, frequency: "custom", customExpression: v }));
              onChangeRef.current(v);
            }}
            placeholder="0 9 * * *"
            spellCheck={false}
          />
          <p className="text-xs text-muted-foreground">{t("schedulesPage.cron.advanced_hint")}</p>
        </div>
      )}

      <div
        className={cn(
          "rounded-lg border px-3 py-2 text-sm",
          valid ? "border-border bg-muted/30" : "border-destructive/40 bg-destructive/10",
        )}
      >
        <p className="font-medium text-foreground">
          {valid ? summary : t("schedulesPage.cron.invalid")}
        </p>
        {timezone && (
          <p className="mt-0.5 text-xs text-muted-foreground">
            {t("schedulesPage.cron.timezone_note", { tz: timezone } as Record<string, string>)}
          </p>
        )}
        <p className="mt-1 font-mono text-xs text-muted-foreground">{expression}</p>
      </div>
    </div>
  );
}

export function describeCronHuman(
  cronExpression: string,
  tr: (key: string, vars?: Record<string, string | number>) => string,
): string {
  const st = parseCronExpression(cronExpression);
  if (st.frequency === "custom") {
    return cronExpression;
  }
  const key = `schedulesPage.cron.summary.${st.frequency}`;
  return tr(key, {
    time: formatTime24(st.hour, st.minute),
    day: tr(`schedulesPage.cron.weekday.${st.dayOfWeek}`),
    dom: st.dayOfMonth,
    n: st.everyNMinutes,
  });
}
