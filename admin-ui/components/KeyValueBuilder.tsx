"use client";

import React, { useState } from "react";
import { Plus, Trash2, Lock, Eye, EyeOff, KeyRound, Sparkles } from "lucide-react";

export interface KeyValueBuilderProps {
  env: Record<string, string>;
  onChange: (nextEnv: Record<string, string>) => void;
  disabled?: boolean;
}

const SECRET_KEY_REGEX = /(KEY|SECRET|TOKEN|PASSWORD|PASS|AUTH|PRIVATE|CREDENTIAL|APIKEY|API_KEY)/i;

export function isSecretKey(key: string): boolean {
  if (!key) return false;
  return SECRET_KEY_REGEX.test(key);
}

export function KeyValueBuilder({
  env,
  onChange,
  disabled = false,
}: KeyValueBuilderProps) {
  // Convert env object to array of entries for deterministic editing
  const entries = Object.entries(env || {}).map(([k, v]) => ({
    key: k,
    value: String(v ?? ""),
  }));

  // Track which secret keys are currently in "replace/edit" mode
  const [editingSecrets, setEditingSecrets] = useState<Record<string, boolean>>({});
  // Track visibility toggles for inputs
  const [visibleSecrets, setVisibleSecrets] = useState<Record<string, boolean>>({});

  const handleKeyChange = (index: number, newKey: string) => {
    const updatedEntries = [...entries];
    const oldKey = updatedEntries[index].key;
    const val = updatedEntries[index].value;
    updatedEntries[index] = { key: newKey, value: val };

    // Rebuild object
    const nextEnv: Record<string, string> = {};
    for (const item of updatedEntries) {
      if (item.key) {
        nextEnv[item.key] = item.value;
      }
    }
    onChange(nextEnv);

    // Transfer editing secret state if key changed
    if (editingSecrets[oldKey]) {
      const nextEditing = { ...editingSecrets };
      delete nextEditing[oldKey];
      nextEditing[newKey] = true;
      setEditingSecrets(nextEditing);
    }
  };

  const handleValueChange = (index: number, newValue: string) => {
    const updatedEntries = [...entries];
    updatedEntries[index] = { ...updatedEntries[index], value: newValue };

    const nextEnv: Record<string, string> = {};
    for (const item of updatedEntries) {
      if (item.key) {
        nextEnv[item.key] = item.value;
      }
    }
    onChange(nextEnv);
  };

  const handleAddRow = () => {
    const nextEnv = { ...(env || {}) };
    let newKeyName = "NEW_VAR";
    let counter = 1;
    while (newKeyName in nextEnv) {
      newKeyName = `NEW_VAR_${counter++}`;
    }
    nextEnv[newKeyName] = "";
    onChange(nextEnv);
  };

  const handleRemoveRow = (keyToRemove: string) => {
    const nextEnv = { ...(env || {}) };
    delete nextEnv[keyToRemove];
    onChange(nextEnv);

    if (editingSecrets[keyToRemove]) {
      const next = { ...editingSecrets };
      delete next[keyToRemove];
      setEditingSecrets(next);
    }
  };

  const toggleEditSecret = (key: string) => {
    setEditingSecrets((prev) => ({
      ...prev,
      [key]: !prev[key],
    }));
  };

  const toggleVisibility = (key: string) => {
    setVisibleSecrets((prev) => ({
      ...prev,
      [key]: !prev[key],
    }));
  };

  return (
    <div className="space-y-3.5">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <KeyRound className="w-4 h-4 text-emerald-400" />
          <span className="text-xs font-bold uppercase tracking-wider text-gray-200">
            Environment Variables ({entries.length})
          </span>
        </div>
        <button
          type="button"
          onClick={handleAddRow}
          disabled={disabled}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-bold text-emerald-400 bg-emerald-500/10 border border-emerald-500/20 hover:bg-emerald-500/20 rounded-xl transition cursor-pointer disabled:opacity-50 shadow-sm"
        >
          <Plus className="w-3.5 h-3.5" />
          Add Variable
        </button>
      </div>

      {entries.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-white/10 bg-black/20 p-6 text-center text-xs text-gray-400 space-y-2">
          <p>No environment variables configured.</p>
          <button
            type="button"
            onClick={handleAddRow}
            className="text-emerald-400 font-bold hover:underline inline-flex items-center gap-1 text-xs cursor-pointer"
          >
            <Plus className="w-3.5 h-3.5" /> Add a variable
          </button>
        </div>
      ) : (
        <div className="space-y-2.5 max-h-[360px] overflow-y-auto pr-1 custom-scrollbar">
          {entries.map((entry, index) => {
            const isSecret = isSecretKey(entry.key);
            const isDynamicUser =
              entry.value.startsWith("${AION_USER_") ||
              entry.value.startsWith("AION_USER_");
            const isEditingThisSecret = Boolean(editingSecrets[entry.key]);
            const isVisible = Boolean(visibleSecrets[entry.key]);
            const hasExistingValue = entry.value.trim().length > 0;

            return (
              <div
                key={`${entry.key}-${index}`}
                className="group flex flex-col gap-1.5 p-3.5 rounded-2xl border border-white/10 bg-[#121212] hover:border-white/20 transition-colors shadow-sm"
              >
                <div className="flex items-center gap-2.5">
                  {/* Key input */}
                  <div className="flex-1 min-w-0">
                    <input
                      type="text"
                      value={entry.key}
                      disabled={disabled}
                      onChange={(e) => handleKeyChange(index, e.target.value)}
                      placeholder="VARIABLE_NAME"
                      className="w-full bg-black/50 border border-white/10 focus:border-emerald-500 rounded-xl px-3.5 py-2 text-xs font-mono font-bold text-emerald-200 placeholder:text-gray-600 outline-none transition"
                    />
                  </div>

                  {/* Value input / Masked Secret */}
                  <div className="flex-1 min-w-0 relative">
                    {isSecret && hasExistingValue && !isEditingThisSecret && !isDynamicUser ? (
                      <div className="flex items-center justify-between bg-black/50 border border-amber-500/25 rounded-xl px-3.5 py-2 text-xs font-mono text-amber-200">
                        <span className="flex items-center gap-1.5 text-gray-400">
                          <Lock className="w-3.5 h-3.5 text-amber-400 shrink-0" />
                          ••••••••••••
                        </span>
                        <button
                          type="button"
                          onClick={() => toggleEditSecret(entry.key)}
                          className="text-[11px] font-bold text-amber-300 hover:text-amber-200 underline ml-2 cursor-pointer"
                        >
                          Edit
                        </button>
                      </div>
                    ) : (
                      <div className="relative">
                        <input
                          type={isSecret && !isVisible ? "password" : "text"}
                          value={entry.value}
                          disabled={disabled}
                          onChange={(e) => handleValueChange(index, e.target.value)}
                          placeholder={
                            isSecret
                              ? "Secret value..."
                              : isDynamicUser
                              ? "${AION_USER_...}"
                              : "Value..."
                          }
                          className={`w-full bg-black/50 border rounded-xl px-3.5 py-2 text-xs font-mono text-white placeholder:text-gray-600 outline-none transition ${
                            isSecret
                              ? "border-amber-500/30 focus:border-amber-400 pr-16"
                              : isDynamicUser
                              ? "border-purple-500/30 text-purple-300 focus:border-purple-400"
                              : "border-white/10 focus:border-emerald-500"
                          }`}
                        />
                        {isSecret && (
                          <div className="absolute right-2.5 top-1/2 -translate-y-1/2 flex items-center gap-1">
                            <button
                              type="button"
                              onClick={() => toggleVisibility(entry.key)}
                              className="text-gray-400 hover:text-white p-1 rounded transition"
                              title={isVisible ? "Hide" : "Show"}
                            >
                              {isVisible ? (
                                <EyeOff className="w-3.5 h-3.5" />
                              ) : (
                                <Eye className="w-3.5 h-3.5" />
                              )}
                            </button>
                            {hasExistingValue && (
                              <button
                                type="button"
                                onClick={() => toggleEditSecret(entry.key)}
                                className="text-[10px] text-gray-500 hover:text-gray-300 font-mono px-1"
                                title="Cancel edit"
                              >
                                ✕
                              </button>
                            )}
                          </div>
                        )}
                      </div>
                    )}
                  </div>

                  {/* Remove Button */}
                  <button
                    type="button"
                    onClick={() => handleRemoveRow(entry.key)}
                    disabled={disabled}
                    className="p-2 text-gray-500 hover:text-red-400 hover:bg-red-500/10 rounded-xl transition cursor-pointer shrink-0"
                    title="Remove variable"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>

                {/* Sub-label badges */}
                {(isSecret || isDynamicUser) && (
                  <div className="flex items-center gap-2 text-[10px] px-1 text-gray-400 pt-0.5">
                    {isSecret && (
                      <span className="inline-flex items-center gap-1 text-amber-400/90 font-medium">
                        <Lock className="w-3 h-3" /> Encrypted secret
                      </span>
                    )}
                    {isDynamicUser && (
                      <span className="inline-flex items-center gap-1 text-purple-300 font-medium">
                        <Sparkles className="w-3 h-3" /> Dynamic user variable
                      </span>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
