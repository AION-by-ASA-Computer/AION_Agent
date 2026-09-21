"use client";

import { useState, useSyncExternalStore } from "react";
import { Check, Pencil, Plus, Trash2 } from "lucide-react";

import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";
import {
  activateRuntimePreset,
  createRuntimePreset,
  deleteRuntimePreset,
  getRuntimeSettingsSnapshot,
  renameRuntimePreset,
  saveActiveRuntimePreset,
  sidebarRuntimeSchema,
  subscribeRuntimeSettings,
  valuesEqual,
} from "@/lib/runtime/runtime-settings-store";

export function RuntimePresetsPanel() {
  const t = useT();
  const snap = useSyncExternalStore(
    subscribeRuntimeSettings,
    getRuntimeSettingsSnapshot,
    getRuntimeSettingsSnapshot,
  );
  const [newName, setNewName] = useState("");
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [busy, setBusy] = useState(false);

  const keys = sidebarRuntimeSchema().map((f) => f.key);
  const active = snap.presets.find((p) => p.id === snap.activePresetId);
  const dirty =
    Boolean(active) && !valuesEqual(snap.values, active?.values || {}, keys);

  async function handleCreate() {
    const name = newName.trim();
    if (!name) return;
    setBusy(true);
    const ok = await createRuntimePreset(name);
    setBusy(false);
    if (ok) setNewName("");
  }

  return (
    <div className="space-y-3 px-2 pb-4">
      <p className="text-[0.7rem] leading-snug text-muted-foreground">{t("settings.presets.hint")}</p>
      <div className="flex gap-1.5">
        <input
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          placeholder={t("settings.presets.name_placeholder")}
          maxLength={40}
          className="h-8 min-w-0 flex-1 rounded-md border border-border/50 bg-background px-2 text-xs"
        />
        <button
          type="button"
          disabled={busy || !newName.trim()}
          onClick={() => void handleCreate()}
          className="inline-flex h-8 items-center gap-1 rounded-md bg-primary px-2 text-[0.7rem] font-semibold text-primary-foreground disabled:opacity-50"
        >
          <Plus className="h-3.5 w-3.5" aria-hidden />
          {t("settings.presets.save_as")}
        </button>
      </div>
      {dirty ? (
        <button
          type="button"
          disabled={busy}
          onClick={() => void saveActiveRuntimePreset()}
          className="w-full rounded-md border border-primary/30 bg-primary/10 px-2 py-1.5 text-[0.7rem] font-medium text-foreground"
        >
          {t("settings.presets.save_active")}
        </button>
      ) : null}
      <ul className="space-y-1">
        {snap.presets.length === 0 ? (
          <li className="px-1 py-3 text-center text-[0.7rem] text-muted-foreground">
            {t("settings.presets.empty")}
          </li>
        ) : (
          snap.presets.map((preset) => {
            const isActive = preset.id === snap.activePresetId;
            return (
              <li
                key={preset.id}
                className={cn(
                  "flex items-center gap-1 rounded-lg border px-2 py-1.5",
                  isActive ? "border-primary/40 bg-primary/8" : "border-border/40",
                )}
              >
                {renamingId === preset.id ? (
                  <input
                    value={renameValue}
                    onChange={(e) => setRenameValue(e.target.value)}
                    className="h-7 min-w-0 flex-1 rounded border border-border bg-background px-1.5 text-xs"
                  />
                ) : (
                  <button
                    type="button"
                    onClick={() => void activateRuntimePreset(preset.id)}
                    className="min-w-0 flex-1 truncate text-left text-xs font-medium"
                  >
                    {preset.name}
                    {isActive && dirty ? (
                      <span className="ml-1 inline-block h-1.5 w-1.5 rounded-full bg-amber-500" />
                    ) : null}
                  </button>
                )}
                {renamingId === preset.id ? (
                  <button
                    type="button"
                    onClick={() => {
                      void renameRuntimePreset(preset.id, renameValue);
                      setRenamingId(null);
                    }}
                    className="rounded p-1 text-foreground hover:bg-muted/60"
                  >
                    <Check className="h-3.5 w-3.5" aria-hidden />
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={() => {
                      setRenamingId(preset.id);
                      setRenameValue(preset.name);
                    }}
                    className="rounded p-1 text-muted-foreground hover:bg-muted/60"
                  >
                    <Pencil className="h-3.5 w-3.5" aria-hidden />
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => void deleteRuntimePreset(preset.id)}
                  className="rounded p-1 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
                >
                  <Trash2 className="h-3.5 w-3.5" aria-hidden />
                </button>
              </li>
            );
          })
        )}
      </ul>
    </div>
  );
}
