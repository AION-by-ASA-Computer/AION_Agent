"use client";

import { useMemo, useSyncExternalStore } from "react";
import { RotateCcw } from "lucide-react";

import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";
import {
  getRuntimeSettingsSnapshot,
  isComposerThinkingKey,
  patchRuntimeValues,
  resetRuntimeField,
  resetRuntimeToDefaults,
  subscribeRuntimeSettings,
  type RuntimeFieldSchema,
} from "@/lib/runtime/runtime-settings-store";

const GROUPS = ["loop", "generation", "thinking", "advanced"] as const;

function FieldControl({ field, value }: { field: RuntimeFieldSchema; value: unknown }) {
  const t = useT();
  if (field.type === "bool") {
    const on = Boolean(value);
    return (
      <button
        type="button"
        role="switch"
        aria-checked={on}
        onClick={() => patchRuntimeValues({ [field.key]: !on })}
        className={cn(
          "relative h-6 w-10 rounded-full transition",
          on ? "bg-primary" : "bg-muted",
        )}
      >
        <span
          className={cn(
            "absolute top-0.5 h-5 w-5 rounded-full bg-background shadow transition",
            on ? "left-4.5 translate-x-0 left-[1.15rem]" : "left-0.5",
          )}
        />
      </button>
    );
  }
  if (field.type === "enum") {
    const current = String(value ?? field.default ?? "");
    return (
      <div className="flex flex-wrap gap-1">
        {(field.enum || []).map((opt) => (
          <button
            key={opt}
            type="button"
            onClick={() => patchRuntimeValues({ [field.key]: opt })}
            className={cn(
              "rounded-md border px-2 py-1 text-[0.7rem] font-medium",
              current === opt
                ? "border-primary/40 bg-primary/10 text-foreground"
                : "border-border/50 text-muted-foreground hover:bg-muted/50",
            )}
          >
            {t(`settings.runtime.enum.${opt}`)}
          </button>
        ))}
      </div>
    );
  }
  const num = typeof value === "number" ? value : Number(value);
  const min = field.min ?? 0;
  const max = field.max ?? 100;
  const step = field.step ?? 1;
  const display = Number.isFinite(num) ? num : "";
  return (
    <div className="flex items-center gap-2">
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={Number.isFinite(num) ? num : min}
        onChange={(e) => {
          const n = field.type === "int" ? parseInt(e.target.value, 10) : parseFloat(e.target.value);
          patchRuntimeValues({ [field.key]: n });
        }}
        className="min-w-0 flex-1 accent-primary"
      />
      <input
        type="number"
        min={min}
        max={max}
        step={step}
        value={display}
        onChange={(e) => {
          const raw = e.target.value;
          if (raw === "" && field.nullable) {
            patchRuntimeValues({ [field.key]: null });
            return;
          }
          const n = field.type === "int" ? parseInt(raw, 10) : parseFloat(raw);
          if (Number.isFinite(n)) patchRuntimeValues({ [field.key]: n });
        }}
        className="h-7 w-16 shrink-0 rounded-md border border-border/50 bg-background px-1.5 text-right text-[0.7rem]"
      />
    </div>
  );
}

export function RuntimeSettingsForm() {
  const t = useT();
  const snap = useSyncExternalStore(
    subscribeRuntimeSettings,
    getRuntimeSettingsSnapshot,
    getRuntimeSettingsSnapshot,
  );

  const byGroup = useMemo(() => {
    const map = new Map<string, RuntimeFieldSchema[]>();
    for (const field of snap.schema) {
      if (isComposerThinkingKey(field.key)) continue;
      const list = map.get(field.group) || [];
      list.push(field);
      map.set(field.group, list);
    }
    return map;
  }, [snap.schema]);

  if (!snap.loaded) {
    return <p className="px-3 py-4 text-xs text-muted-foreground">{t("settings.runtime.loading")}</p>;
  }

  return (
    <div className="space-y-4 px-1 pb-4">
      <div className="flex items-center justify-between gap-2 px-2">
        <p className="text-[0.7rem] leading-snug text-muted-foreground">{t("settings.runtime.hint")}</p>
        <button
          type="button"
          onClick={() => resetRuntimeToDefaults()}
          className="shrink-0 rounded-md px-2 py-1 text-[0.7rem] font-medium text-muted-foreground hover:bg-muted/60 hover:text-foreground"
        >
          {t("settings.runtime.reset_all")}
        </button>
      </div>
      {GROUPS.map((group) => {
        const fields = byGroup.get(group);
        if (!fields?.length) return null;
        const body = (
          <>
            {group === "loop" && typeof snap.profileMaxAgentSteps === "number" ? (
              <p className="px-2 text-[0.65rem] text-amber-600 dark:text-amber-400">
                {t("settings.runtime.profile_cap", { value: snap.profileMaxAgentSteps })}
              </p>
            ) : null}
            {fields.map((field) => (
              <div key={field.key} className="rounded-lg border border-border/40 bg-background/30 px-2.5 py-2">
                <div className="mb-1.5 flex items-start justify-between gap-2">
                  <div>
                    <div className="text-xs font-medium text-foreground">
                      {t(`settings.runtime.fields.${field.key}`)}
                    </div>
                    <p className="mt-0.5 text-[0.65rem] text-muted-foreground">
                      {t("settings.runtime.server_default", {
                        value: String(field.default ?? snap.defaults[field.key] ?? "—"),
                      })}
                    </p>
                  </div>
                  <button
                    type="button"
                    title={t("settings.runtime.reset_field")}
                    onClick={() => resetRuntimeField(field.key)}
                    className="rounded p-1 text-muted-foreground hover:bg-muted/60 hover:text-foreground"
                  >
                    <RotateCcw className="h-3 w-3" aria-hidden />
                  </button>
                </div>
                <FieldControl field={field} value={snap.values[field.key]} />
              </div>
            ))}
          </>
        );
        if (group === "advanced") {
          return (
            <details key={group} className="space-y-2">
              <summary className="cursor-pointer px-2 text-[0.65rem] font-semibold uppercase tracking-wider text-primary">
                {t(`settings.runtime.group.${group}`)}
              </summary>
              <div className="space-y-2">{body}</div>
            </details>
          );
        }
        return (
          <section key={group} className="space-y-2">
            <h3 className="px-2 text-[0.65rem] font-semibold uppercase tracking-wider text-primary">
              {t(`settings.runtime.group.${group}`)}
            </h3>
            {group === "thinking" ? (
              <p className="px-2 text-[0.65rem] leading-snug text-muted-foreground">
                {t("settings.runtime.composer_thinking_hint")}
              </p>
            ) : null}
            {body}
          </section>
        );
      })}
    </div>
  );
}
