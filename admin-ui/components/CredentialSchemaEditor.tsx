"use client";

import { useRef } from "react";
import { Plus, Trash2, Key, Lock, FileText, ToggleLeft, Shield } from "lucide-react";
import type { CredentialSchemaField } from "@/lib/mcpIntegrationPolicy";

export type { CredentialSchemaField };

type Props = {
  value: CredentialSchemaField[];
  onChange: (fields: CredentialSchemaField[]) => void;
  className?: string;
  showEnvPlaceholders?: boolean;
};

export function CredentialSchemaEditor({
  value,
  onChange,
  className,
  showEnvPlaceholders = true,
}: Props) {
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
    const next = value.map((f, i) => (i === index ? { ...f, ...patch } : f));
    onChange(next);
  }

  function removeAt(index: number) {
    onChange(value.filter((_, i) => i !== index));
  }

  function addField() {
    const newId = `cred_field_${Date.now()}_${Math.random().toString(36).slice(2, 9)}`;
    onChange([
      ...value,
      {
        _id: newId,
        key: `FIELD_${value.length + 1}`,
        label: "New Field",
        type: "password",
        required: true,
      },
    ]);
  }

  return (
    <div className={className}>
      <div className="mb-3.5 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Key className="w-4 h-4 text-blue-400" />
          <span className="text-xs font-bold uppercase tracking-wider text-gray-200">
            User Requested Fields ({value.length})
          </span>
        </div>
        <button
          type="button"
          onClick={addField}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl border border-blue-500/30 bg-blue-500/10 text-xs font-bold text-blue-400 hover:bg-blue-500/20 transition cursor-pointer shadow-sm"
        >
          <Plus className="h-3.5 w-3.5" aria-hidden />
          Add field
        </button>
      </div>

      {value.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-white/10 bg-black/20 px-4 py-6 text-center">
          <p className="text-xs text-gray-400">
            No fields configured for users.
          </p>
          <button
            type="button"
            onClick={addField}
            className="mt-2 text-xs font-bold text-blue-400 hover:underline inline-flex items-center gap-1"
          >
            <Plus className="w-3.5 h-3.5" /> Define the first field
          </button>
        </div>
      ) : (
        <div className="space-y-3">
          {value.map((field, index) => {
            const rowKey = getFieldId(field, index);
            return (
              <div
                key={rowKey}
                className="rounded-2xl border border-white/10 bg-[#121212] p-4 hover:border-white/20 transition-colors shadow-sm space-y-3"
              >
                {/* Inputs Row */}
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <div>
                    <label className="mb-1.5 block text-xs font-semibold text-gray-400">
                      Variable Name (ENV)
                    </label>
                    <input
                      className="w-full bg-black/50 border border-white/10 focus:border-blue-500 rounded-xl px-3.5 py-2 text-xs font-mono font-bold text-blue-200 placeholder:text-gray-600 outline-none transition"
                      value={field.key}
                      onChange={(e) =>
                        updateAt(index, { key: e.target.value.replace(/\s/g, "_").toUpperCase() })
                      }
                      placeholder="E.G. API_KEY"
                    />
                  </div>
                  <div>
                    <label className="mb-1.5 block text-xs font-semibold text-gray-400">
                      User Label
                    </label>
                    <input
                      className="w-full bg-black/50 border border-white/10 focus:border-blue-500 rounded-xl px-3.5 py-2 text-xs font-medium text-white placeholder:text-gray-600 outline-none transition"
                      value={field.label}
                      onChange={(e) => updateAt(index, { label: e.target.value })}
                      placeholder="E.G. Personal API Key"
                    />
                  </div>
                </div>

                {/* Controls & Options Bar */}
                <div className="flex flex-wrap items-center justify-between gap-3 pt-2.5 border-t border-white/5">
                  <div className="flex items-center gap-3">
                    <select
                      className="bg-black/50 border border-white/10 focus:border-blue-500 rounded-xl px-3 py-1.5 text-xs font-medium text-gray-200 outline-none cursor-pointer"
                      value={field.type}
                      onChange={(e) =>
                        updateAt(index, { type: e.target.value as CredentialSchemaField["type"] })
                      }
                    >
                      <option value="password">Password / Secret</option>
                      <option value="text">Text</option>
                      <option value="boolean">Toggle (Yes/No)</option>
                      <option value="oauth">OAuth Token</option>
                    </select>

                    <label className="flex items-center gap-2 text-xs font-medium text-gray-300 cursor-pointer bg-white/5 hover:bg-white/10 px-3 py-1.5 rounded-xl border border-white/5 transition">
                      <input
                        type="checkbox"
                        checked={field.required}
                        onChange={(e) => updateAt(index, { required: e.target.checked })}
                        className="rounded border-white/20 text-blue-500 focus:ring-0"
                      />
                      <span>Required</span>
                    </label>
                  </div>

                  <button
                    type="button"
                    onClick={() => removeAt(index)}
                    className="p-1.5 text-gray-500 hover:text-red-400 hover:bg-red-500/10 rounded-xl transition cursor-pointer"
                    title="Delete field"
                  >
                    <Trash2 className="h-4 w-4" aria-hidden />
                  </button>
                </div>

                {showEnvPlaceholders && field.env_placeholder ? (
                  <div className="text-[11px] font-mono text-gray-500 bg-black/40 px-3 py-1.5 rounded-lg border border-white/5 truncate">
                    env: <span className="text-indigo-300">{field.registry_env_key || field.key}</span> = &quot;{field.env_placeholder}&quot;
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
