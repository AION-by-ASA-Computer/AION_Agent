"use client";

import { useMemo, useSyncExternalStore, type ReactNode } from "react";
import { ChevronRight, Loader2, RotateCcw } from "lucide-react";

import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";
import {
  getRuntimeSettingsSnapshot,
  isComposerThinkingKey,
  patchRuntimeValues,
  resetRuntimeField,
  resetRuntimeToDefaults,
  subscribeRuntimeSettings,
  valuesEqual,
  type RuntimeFieldSchema,
} from "@/lib/runtime/runtime-settings-store";
import { Group, Note, RowList, Segmented, Switch, ghostBtn, iconBtn } from "./ui";

const GROUPS = ["loop", "generation", "thinking", "advanced"] as const;

function FieldControl({ field, value, label }: { field: RuntimeFieldSchema; value: unknown; label: string }) {
  const t = useT();
  if (field.type === "bool") {
    return <Switch checked={Boolean(value)} onChange={(v) => patchRuntimeValues({ [field.key]: v })} label={label} />;
  }
  if (field.type === "enum") {
    return (
      <Segmented
        label={label}
        value={String(value ?? field.default ?? "")}
        onChange={(v) => patchRuntimeValues({ [field.key]: v })}
        options={(field.enum || []).map((opt) => ({ value: opt, label: t(`settings.runtime.enum.${opt}`) }))}
      />
    );
  }
  const num = typeof value === "number" ? value : Number(value);
  const min = field.min ?? 0;
  const max = field.max ?? 100;
  const step = field.step ?? 1;
  const parse = (raw: string) => (field.type === "int" ? parseInt(raw, 10) : parseFloat(raw));
  return (
    <div className="flex w-full items-center gap-3 sm:w-72">
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={Number.isFinite(num) ? num : min}
        onChange={(e) => patchRuntimeValues({ [field.key]: parse(e.target.value) })}
        aria-label={label}
        className="focus-ring min-w-0 flex-1 cursor-pointer accent-[hsl(var(--foreground))]"
      />
      <input
        type="number"
        min={min}
        max={max}
        step={step}
        value={Number.isFinite(num) ? num : ""}
        onChange={(e) => {
          const raw = e.target.value;
          if (raw === "" && field.nullable) {
            patchRuntimeValues({ [field.key]: null });
            return;
          }
          const n = parse(raw);
          if (Number.isFinite(n)) patchRuntimeValues({ [field.key]: n });
        }}
        aria-label={label}
        className="focus-ring h-9 w-22 shrink-0 rounded-xl border border-border bg-background px-2.5 text-right font-mono text-[0.893rem] tabular-nums transition-colors hover:border-foreground/25 focus:border-foreground/40"
      />
    </div>
  );
}

/** Runtime parameters. Each change applies to the next turn and is persisted by the store. */
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
    return (
      <p className="flex items-center gap-2 py-8 text-sm text-muted-foreground" role="status">
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
        {t("settings.runtime.loading")}
      </p>
    );
  }

  const rows = (fields: RuntimeFieldSchema[]) => (
    <RowList>
      {fields.map((field) => {
        const label = t(`settings.runtime.fields.${field.key}`);
        const fallback = field.default ?? snap.defaults[field.key];
        const atDefault = valuesEqual(snap.values, snap.defaults, [field.key]);
        return (
          <li key={field.key} className="flex flex-col gap-x-6 gap-y-3 px-5 py-3.5 sm:flex-row sm:items-center">
            <div className="min-w-0 flex-1">
              <div className="text-sm font-medium">{label}</div>
              <p className="mt-0.5 text-xs text-muted-foreground">
                {t("settings.runtime.server_default", { value: String(fallback ?? "—") })}
              </p>
            </div>
            <div className="flex items-center gap-2">
              <FieldControl field={field} value={snap.values[field.key]} label={label} />
              <button
                type="button"
                onClick={() => resetRuntimeField(field.key)}
                disabled={atDefault}
                aria-label={`${t("settings.runtime.reset_field")}: ${label}`}
                title={t("settings.runtime.reset_field")}
                className={cn(iconBtn, "disabled:invisible")}
              >
                <RotateCcw className="h-3.5 w-3.5" aria-hidden />
              </button>
            </div>
          </li>
        );
      })}
    </RowList>
  );

  const extra = (group: string): ReactNode => {
    if (group === "loop" && typeof snap.profileMaxAgentSteps === "number") {
      return (
        <div className="px-5 pt-4">
          <Note tone="warn">{t("settings.runtime.profile_cap", { value: snap.profileMaxAgentSteps })}</Note>
        </div>
      );
    }
    return null;
  };

  return (
    <>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <p className="min-w-0 flex-1 text-sm text-muted-foreground">{t("settings.runtime.hint")}</p>
        <button type="button" onClick={() => resetRuntimeToDefaults()} className={ghostBtn}>
          <RotateCcw className="h-3.5 w-3.5" aria-hidden />
          {t("settings.runtime.reset_all")}
        </button>
      </div>

      {GROUPS.map((group) => {
        const fields = byGroup.get(group);
        if (!fields?.length) return null;
        const title = t(`settings.runtime.group.${group}`);

        if (group === "advanced") {
          return (
            <details key={group} className="group/adv overflow-hidden rounded-2xl border border-border bg-card/60">
              <summary className="focus-ring flex cursor-pointer list-none items-center gap-2 bg-secondary/60 px-5 py-3.5 [&::-webkit-details-marker]:hidden">
                <ChevronRight
                  className="h-4 w-4 shrink-0 text-muted-foreground transition-transform group-open/adv:rotate-90"
                  aria-hidden
                />
                <h3 className="text-[1.0714rem] font-semibold tracking-[-0.01em]">{title}</h3>
                <span className="ml-auto text-xs tabular-nums text-muted-foreground">{fields.length}</span>
              </summary>
              <div className="border-t border-border">{rows(fields)}</div>
            </details>
          );
        }

        return (
          <Group
            key={group}
            title={title}
            description={group === "thinking" ? t("settings.runtime.composer_thinking_hint") : undefined}
          >
            {extra(group)}
            {rows(fields)}
          </Group>
        );
      })}
    </>
  );
}
