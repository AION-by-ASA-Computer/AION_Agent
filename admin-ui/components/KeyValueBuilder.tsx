"use client";

import { useState } from "react";
import { Eye, EyeOff, Lock, Plus, Sparkles, Trash2 } from "lucide-react";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";
import { ghostBtn, inputCls, outlineBtn } from "@/components/ui/classes";

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

const monoInput = cn(inputCls, "font-mono text-[13px]");
const iconBtn =
  "focus-ring inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground disabled:opacity-50";

export function KeyValueBuilder({ env, onChange, disabled = false }: KeyValueBuilderProps) {
  const t = useT();
  const k = "admin_hub.editors.kv";
  const entries = Object.entries(env || {}).map(([key, v]) => ({ key, value: String(v ?? "") }));

  // Secrets currently in "replace" mode, and inputs whose value is revealed.
  const [editingSecrets, setEditingSecrets] = useState<Record<string, boolean>>({});
  const [visibleSecrets, setVisibleSecrets] = useState<Record<string, boolean>>({});

  const emit = (list: { key: string; value: string }[]) => {
    const next: Record<string, string> = {};
    for (const item of list) if (item.key) next[item.key] = item.value;
    onChange(next);
  };

  const handleKeyChange = (index: number, newKey: string) => {
    const list = [...entries];
    const oldKey = list[index].key;
    list[index] = { key: newKey, value: list[index].value };
    emit(list);
    if (editingSecrets[oldKey]) {
      const next = { ...editingSecrets };
      delete next[oldKey];
      next[newKey] = true;
      setEditingSecrets(next);
    }
  };

  const handleValueChange = (index: number, value: string) => {
    const list = [...entries];
    list[index] = { ...list[index], value };
    emit(list);
  };

  const handleAddRow = () => {
    const next = { ...(env || {}) };
    let name = "NEW_VAR";
    let n = 1;
    while (name in next) name = `NEW_VAR_${n++}`;
    next[name] = "";
    onChange(next);
  };

  const handleRemoveRow = (key: string) => {
    const next = { ...(env || {}) };
    delete next[key];
    onChange(next);
    if (editingSecrets[key]) {
      const e = { ...editingSecrets };
      delete e[key];
      setEditingSecrets(e);
    }
  };

  const toggleEdit = (key: string) => setEditingSecrets((p) => ({ ...p, [key]: !p[key] }));
  const toggleVisible = (key: string) => setVisibleSecrets((p) => ({ ...p, [key]: !p[key] }));

  return (
    <section className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-sm font-semibold">
          {t(`${k}.title`)} <span className="tabular-nums text-muted-foreground">{entries.length}</span>
        </h3>
        <button type="button" onClick={handleAddRow} disabled={disabled} className={outlineBtn}>
          <Plus className="h-3.5 w-3.5" aria-hidden />
          {t(`${k}.add`)}
        </button>
      </div>

      {entries.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-border px-4 py-8 text-center">
          <p className="text-sm text-muted-foreground">{t(`${k}.empty`)}</p>
          <button type="button" onClick={handleAddRow} disabled={disabled} className={cn(ghostBtn, "mt-2")}>
            <Plus className="h-3.5 w-3.5" aria-hidden />
            {t(`${k}.empty_add`)}
          </button>
        </div>
      ) : (
        <ul className="flex max-h-[22rem] flex-col gap-2.5 overflow-y-auto pr-0.5">
          {entries.map((entry, index) => {
            const isSecret = isSecretKey(entry.key);
            const isDynamicUser = entry.value.startsWith("${AION_USER_") || entry.value.startsWith("AION_USER_");
            const editingThis = Boolean(editingSecrets[entry.key]);
            const visible = Boolean(visibleSecrets[entry.key]);
            const hasValue = entry.value.trim().length > 0;
            const masked = isSecret && hasValue && !editingThis && !isDynamicUser;

            return (
              <li key={`${entry.key}-${index}`} className="rounded-2xl border border-border/70 p-3">
                <div className="flex items-center gap-2">
                  <input
                    type="text"
                    value={entry.key}
                    disabled={disabled}
                    onChange={(e) => handleKeyChange(index, e.target.value)}
                    placeholder={t(`${k}.key_ph`)}
                    aria-label={t(`${k}.key_ph`)}
                    className={cn(monoInput, "min-w-0 flex-1 font-semibold")}
                  />

                  <div className="relative min-w-0 flex-1">
                    {masked ? (
                      <div className={cn(inputCls, "flex items-center justify-between gap-2 h-[2.625rem] py-0 pr-1.5 font-mono text-[13px]")}>
                        <span className="flex items-center gap-2 text-muted-foreground">
                          <Lock className="h-3.5 w-3.5 shrink-0 text-warning" aria-hidden />
                          ••••••••••••
                        </span>
                        <button type="button" onClick={() => toggleEdit(entry.key)} className={cn(ghostBtn, "h-7 px-2 text-xs")}>
                          {t(`${k}.edit`)}
                        </button>
                      </div>
                    ) : (
                      <>
                        <input
                          type={isSecret && !visible ? "password" : "text"}
                          value={entry.value}
                          disabled={disabled}
                          onChange={(e) => handleValueChange(index, e.target.value)}
                          placeholder={isSecret ? t(`${k}.secret_ph`) : isDynamicUser ? "${AION_USER_…}" : t(`${k}.value_ph`)}
                          aria-label={t(`${k}.value_ph`)}
                          className={cn(monoInput, isSecret && "pr-20")}
                        />
                        {isSecret && (
                          <div className="absolute right-1.5 top-1/2 flex -translate-y-1/2 items-center">
                            <button
                              type="button"
                              onClick={() => toggleVisible(entry.key)}
                              className={iconBtn}
                              aria-label={visible ? t(`${k}.hide`) : t(`${k}.show`)}
                              aria-pressed={visible}
                            >
                              {visible ? <EyeOff className="h-3.5 w-3.5" aria-hidden /> : <Eye className="h-3.5 w-3.5" aria-hidden />}
                            </button>
                            {hasValue && (
                              <button type="button" onClick={() => toggleEdit(entry.key)} className={iconBtn} aria-label={t(`${k}.cancel_edit`)}>
                                <span aria-hidden>✕</span>
                              </button>
                            )}
                          </div>
                        )}
                      </>
                    )}
                  </div>

                  <button
                    type="button"
                    onClick={() => handleRemoveRow(entry.key)}
                    disabled={disabled}
                    className={cn(iconBtn, "h-9 w-9 rounded-xl hover:bg-destructive/10 hover:text-destructive")}
                    aria-label={t(`${k}.remove`)}
                  >
                    <Trash2 className="h-4 w-4" aria-hidden />
                  </button>
                </div>

                {(isSecret || isDynamicUser) && (
                  <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 px-1 text-xs text-muted-foreground">
                    {isSecret && (
                      <span className="inline-flex items-center gap-1.5">
                        <Lock className="h-3 w-3 text-warning" aria-hidden />
                        {t(`${k}.secret_tag`)}
                      </span>
                    )}
                    {isDynamicUser && (
                      <span className="inline-flex items-center gap-1.5">
                        <Sparkles className="h-3 w-3" aria-hidden />
                        {t(`${k}.dynamic_tag`)}
                      </span>
                    )}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
