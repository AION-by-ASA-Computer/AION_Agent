"use client";

import { useRef } from "react";
import { Plus, Trash2 } from "lucide-react";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";
import { ghostBtn, inputCls, outlineBtn } from "@/components/ui/classes";
import { Select } from "@/components/ui/Select";
import type { CredentialSchemaField } from "@/lib/mcpIntegrationPolicy";

export type { CredentialSchemaField };

type Props = {
  value: CredentialSchemaField[];
  onChange: (fields: CredentialSchemaField[]) => void;
  className?: string;
  showEnvPlaceholders?: boolean;
};

const FIELD_TYPES = ["password", "text", "boolean", "oauth"] as const;
const labelCls = "mb-1.5 block text-xs font-medium text-muted-foreground";

export function CredentialSchemaEditor({ value, onChange, className, showEnvPlaceholders = true }: Props) {
  const t = useT();
  const k = "admin_hub.editors.schema";
  const idMapRef = useRef<WeakMap<CredentialSchemaField, string>>(new WeakMap());

  function getFieldId(field: CredentialSchemaField, index: number): string {
    if (field._id) return field._id;
    let cached = idMapRef.current.get(field);
    if (!cached) {
      cached = `cred_field_${index}_${Math.random().toString(36).slice(2, 9)}`;
      idMapRef.current.set(field, cached);
      try {
        field._id = cached;
      } catch {
        /* ignore */
      }
    }
    return cached;
  }

  function updateAt(index: number, patch: Partial<CredentialSchemaField>) {
    onChange(value.map((f, i) => (i === index ? { ...f, ...patch } : f)));
  }

  function removeAt(index: number) {
    onChange(value.filter((_, i) => i !== index));
  }

  function addField() {
    const newId = `cred_field_${Date.now()}_${Math.random().toString(36).slice(2, 9)}`;
    onChange([
      ...value,
      { _id: newId, key: `FIELD_${value.length + 1}`, label: t(`${k}.new_label`), type: "password", required: true },
    ]);
  }

  return (
    <section className={cn("flex flex-col gap-3", className)}>
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-sm font-semibold">
          {t(`${k}.title`)} <span className="tabular-nums text-muted-foreground">{value.length}</span>
        </h3>
        <button type="button" onClick={addField} className={outlineBtn}>
          <Plus className="h-3.5 w-3.5" aria-hidden />
          {t(`${k}.add`)}
        </button>
      </div>

      {value.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-border px-4 py-8 text-center">
          <p className="text-sm text-muted-foreground">{t(`${k}.empty`)}</p>
          <button type="button" onClick={addField} className={cn(ghostBtn, "mt-2")}>
            <Plus className="h-3.5 w-3.5" aria-hidden />
            {t(`${k}.empty_add`)}
          </button>
        </div>
      ) : (
        <ul className="flex flex-col gap-2.5">
          {value.map((field, index) => {
            const rowKey = getFieldId(field, index);
            return (
              <li key={rowKey} className="rounded-2xl border border-border/70 p-3.5">
                <div className="grid gap-3 sm:grid-cols-2">
                  <label className="block">
                    <span className={labelCls}>{t(`${k}.var_name`)}</span>
                    <input
                      className={cn(inputCls, "font-mono text-[13px] font-semibold")}
                      value={field.key}
                      onChange={(e) => updateAt(index, { key: e.target.value.replace(/\s/g, "_").toUpperCase() })}
                      placeholder={t(`${k}.var_ph`)}
                    />
                  </label>
                  <label className="block">
                    <span className={labelCls}>{t(`${k}.label`)}</span>
                    <input
                      className={inputCls}
                      value={field.label}
                      onChange={(e) => updateAt(index, { label: e.target.value })}
                      placeholder={t(`${k}.label_ph`)}
                    />
                  </label>
                </div>

                <div className="mt-3 flex flex-wrap items-center gap-3 border-t border-border/50 pt-3">
                  <div className="w-52 max-w-full">
                    <Select
                      size="sm"
                      value={field.type}
                      onChange={(type) => updateAt(index, { type: type as CredentialSchemaField["type"] })}
                      aria-label={t(`${k}.type`)}
                      options={FIELD_TYPES.map((id) => ({ value: id, label: t(`${k}.type_${id}`) }))}
                    />
                  </div>
                  <label className="inline-flex cursor-pointer items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={field.required}
                      onChange={(e) => updateAt(index, { required: e.target.checked })}
                      className="h-4 w-4 cursor-pointer accent-[hsl(var(--primary))]"
                    />
                    {t(`${k}.required`)}
                  </label>
                  <button
                    type="button"
                    onClick={() => removeAt(index)}
                    className="focus-ring ml-auto inline-flex h-9 w-9 items-center justify-center rounded-xl text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive"
                    aria-label={t(`${k}.remove`)}
                  >
                    <Trash2 className="h-4 w-4" aria-hidden />
                  </button>
                </div>

                {showEnvPlaceholders && field.env_placeholder ? (
                  <p className="mt-3 truncate rounded-lg bg-secondary/60 px-3 py-1.5 font-mono text-xs text-muted-foreground">
                    env: <span className="text-foreground">{field.registry_env_key || field.key}</span> = &quot;{field.env_placeholder}&quot;
                  </p>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
