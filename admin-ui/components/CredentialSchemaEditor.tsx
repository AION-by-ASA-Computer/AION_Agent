"use client";

import { Plus, Trash2 } from "lucide-react";
import type { CredentialSchemaField } from "@/lib/mcpIntegrationPolicy";
import { cn } from "@/lib/cn";

export type { CredentialSchemaField };

type Props = {
  value: CredentialSchemaField[];
  onChange: (fields: CredentialSchemaField[]) => void;
  className?: string;
  showEnvPlaceholders?: boolean;
};

const inputClass =
  "focus-ring w-full rounded-xl border border-border/70 bg-background/60 px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground/60";

export function CredentialSchemaEditor({ value, onChange, className, showEnvPlaceholders = true }: Props) {
  function updateAt(index: number, patch: Partial<CredentialSchemaField>) {
    const next = value.map((f, i) => (i === index ? { ...f, ...patch } : f));
    onChange(next);
  }

  function removeAt(index: number) {
    onChange(value.filter((_, i) => i !== index));
  }

  function addField() {
    onChange([
      ...value,
      {
        key: `FIELD_${value.length + 1}`,
        label: "Nuovo campo",
        type: "password",
        required: false,
      },
    ]);
  }

  return (
    <div className={className}>
      <div className="mb-3 flex items-center justify-between gap-2">
        <p className="aion-section-label">Campi credenziali utente ({value.length})</p>
        <button
          type="button"
          onClick={addField}
          className="focus-ring inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs font-semibold text-foreground transition hover:bg-muted"
        >
          <Plus className="h-3.5 w-3.5" aria-hidden />
          Aggiungi campo
        </button>
      </div>
      {value.length === 0 ? (
        <p className="rounded-2xl border border-dashed border-border/70 bg-muted/30 px-4 py-3 text-xs text-muted-foreground">
          Nessun campo definito. Aggiungi le credenziali che ogni utente dovrà compilare in chat.
        </p>
      ) : (
        <div className="space-y-2">
          {value.map((field, index) => (
            <div
              key={`${field.key}-${index}`}
              className="space-y-2 rounded-2xl border border-border/70 bg-muted/20 p-3"
            >
              <div className="grid gap-2 sm:grid-cols-[1fr_1fr_auto_auto_auto]">
                <div>
                  <label className="mb-1 block text-[0.714em] font-medium text-muted-foreground">Chiave</label>
                  <input
                    className={cn(inputClass, "font-mono text-xs")}
                    value={field.key}
                    onChange={(e) =>
                      updateAt(index, { key: e.target.value.replace(/\s/g, "_").toUpperCase() })
                    }
                    placeholder="API_KEY"
                  />
                </div>
                <div>
                  <label className="mb-1 block text-[0.714em] font-medium text-muted-foreground">Etichetta</label>
                  <input
                    className={inputClass}
                    value={field.label}
                    onChange={(e) => updateAt(index, { label: e.target.value })}
                    placeholder="Etichetta visibile"
                  />
                </div>
                <div>
                  <label className="mb-1 block text-[0.714em] font-medium text-muted-foreground">Tipo</label>
                  <select
                    className={inputClass}
                    value={field.type}
                    onChange={(e) =>
                      updateAt(index, { type: e.target.value as CredentialSchemaField["type"] })
                    }
                  >
                    <option value="password">password</option>
                    <option value="text">text</option>
                    <option value="oauth">oauth</option>
                  </select>
                </div>
                <label className="flex cursor-pointer items-end gap-2 pb-2 text-xs text-muted-foreground">
                  <input
                    type="checkbox"
                    checked={field.required}
                    onChange={(e) => updateAt(index, { required: e.target.checked })}
                    className="rounded border-border"
                  />
                  Obbl.
                </label>
                <button
                  type="button"
                  onClick={() => removeAt(index)}
                  className="focus-ring flex items-center justify-center pb-1 text-destructive transition hover:text-destructive/80"
                  title="Rimuovi campo"
                >
                  <Trash2 className="h-4 w-4" aria-hidden />
                </button>
              </div>
              {showEnvPlaceholders && field.env_placeholder ? (
                <p className="rounded-lg border border-border/60 bg-background/50 px-2 py-1 font-mono text-[0.714em] text-muted-foreground">
                  env: {field.registry_env_key || field.key}: &quot;{field.env_placeholder}&quot;
                </p>
              ) : null}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
