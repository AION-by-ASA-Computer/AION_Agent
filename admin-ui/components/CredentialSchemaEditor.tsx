"use client";

import { Plus, Trash2 } from "lucide-react";
import type { CredentialSchemaField } from "@/lib/mcpIntegrationPolicy";

export type { CredentialSchemaField };

type Props = {
  value: CredentialSchemaField[];
  onChange: (fields: CredentialSchemaField[]) => void;
  className?: string;
};

const inputClass =
  "w-full bg-black/40 border border-white/10 rounded-lg px-3 py-2 text-sm text-white placeholder:text-gray-600 focus:border-indigo-500/70 outline-none";

export function CredentialSchemaEditor({ value, onChange, className }: Props) {
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
      <div className="mb-2 flex items-center justify-between gap-2">
        <p className="text-[10px] font-bold uppercase tracking-wider text-gray-500">
          Campi credenziali utente ({value.length})
        </p>
        <button
          type="button"
          onClick={addField}
          className="flex items-center gap-1 text-xs font-semibold text-indigo-300 hover:text-indigo-200"
        >
          <Plus className="h-3.5 w-3.5" />
          Aggiungi campo
        </button>
      </div>
      {value.length === 0 ? (
        <p className="text-xs text-gray-500 rounded-lg border border-dashed border-white/10 p-3">
          Nessun campo definito. Aggiungi le credenziali che ogni utente dovrà compilare in chat.
        </p>
      ) : (
        <div className="space-y-2">
          {value.map((field, index) => (
            <div
              key={`${field.key}-${index}`}
              className="grid gap-2 rounded-lg border border-white/10 bg-black/30 p-3 sm:grid-cols-[1fr_1fr_auto_auto_auto]"
            >
              <div>
                <label className="mb-0.5 block text-[10px] text-gray-500">Chiave</label>
                <input
                  className={`${inputClass} font-mono text-xs`}
                  value={field.key}
                  onChange={(e) =>
                    updateAt(index, { key: e.target.value.replace(/\s/g, "_").toUpperCase() })
                  }
                  placeholder="API_KEY"
                />
              </div>
              <div>
                <label className="mb-0.5 block text-[10px] text-gray-500">Etichetta</label>
                <input
                  className={inputClass}
                  value={field.label}
                  onChange={(e) => updateAt(index, { label: e.target.value })}
                  placeholder="Etichetta visibile"
                />
              </div>
              <div>
                <label className="mb-0.5 block text-[10px] text-gray-500">Tipo</label>
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
              <label className="flex items-end gap-2 pb-2 text-xs text-gray-300 cursor-pointer">
                <input
                  type="checkbox"
                  checked={field.required}
                  onChange={(e) => updateAt(index, { required: e.target.checked })}
                />
                Obbl.
              </label>
              <button
                type="button"
                onClick={() => removeAt(index)}
                className="flex items-center justify-center pb-1 text-red-400 hover:text-red-300"
                title="Rimuovi campo"
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
