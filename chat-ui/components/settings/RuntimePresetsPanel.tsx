"use client";

import { useState, useSyncExternalStore } from "react";
import { Check, Loader2, Pencil, Plus, Save, Trash2, X } from "lucide-react";

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
import { Badge, Group, iconBtn, inputCls, outlineBtn, solidBtn } from "./ui";

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
  const dirty = Boolean(active) && !valuesEqual(snap.values, active?.values || {}, keys);

  async function handleCreate() {
    const name = newName.trim();
    if (!name) return;
    setBusy(true);
    const ok = await createRuntimePreset(name);
    setBusy(false);
    if (ok) setNewName("");
  }

  async function handleSaveActive() {
    setBusy(true);
    await saveActiveRuntimePreset();
    setBusy(false);
  }

  function commitRename(id: string) {
    const name = renameValue.trim();
    if (name) void renameRuntimePreset(id, name);
    setRenamingId(null);
  }

  return (
    <>
      <Group title={t("settings.presets.new_title")} description={t("settings.presets.hint")}>
        <form
          className="flex flex-col gap-2 px-5 py-4 sm:flex-row"
          onSubmit={(e) => {
            e.preventDefault();
            void handleCreate();
          }}
        >
          <input
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder={t("settings.presets.name_placeholder")}
            aria-label={t("settings.presets.name_placeholder")}
            maxLength={40}
            className={cn(inputCls, "py-0 sm:max-w-sm h-9")}
          />
          <button type="submit" disabled={busy || !newName.trim()} className={solidBtn}>
            {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <Plus className="h-3.5 w-3.5" aria-hidden />}
            {t("settings.presets.save_as")}
          </button>
        </form>
      </Group>

      <Group
        title={t("settings.presets.list_title")}
        action={
          dirty ? (
            <button type="button" disabled={busy} onClick={() => void handleSaveActive()} className={outlineBtn}>
              <Save className="h-3.5 w-3.5" aria-hidden />
              {t("settings.presets.save_active")}
            </button>
          ) : null
        }
      >
        {snap.presets.length === 0 ? (
          <p className="px-5 py-8 text-center text-sm text-muted-foreground">{t("settings.presets.empty")}</p>
        ) : (
          <ul className="divide-y divide-border/40">
            {snap.presets.map((preset) => {
              const isActive = preset.id === snap.activePresetId;
              const renaming = renamingId === preset.id;
              return (
                <li key={preset.id} className="flex min-h-14 items-center gap-3 px-5 py-2.5">
                  {renaming ? (
                    <form
                      className="flex min-w-0 flex-1 items-center gap-1"
                      onSubmit={(e) => {
                        e.preventDefault();
                        commitRename(preset.id);
                      }}
                    >
                      <input
                        autoFocus
                        value={renameValue}
                        onChange={(e) => setRenameValue(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Escape") setRenamingId(null);
                        }}
                        maxLength={40}
                        aria-label={t("btn.rename")}
                        className={cn(inputCls, "h-9 py-0 sm:max-w-sm")}
                      />
                      <button type="submit" aria-label={t("btn.save")} className={iconBtn}>
                        <Check className="h-4 w-4" aria-hidden />
                      </button>
                      <button type="button" aria-label={t("btn.cancel")} onClick={() => setRenamingId(null)} className={iconBtn}>
                        <X className="h-4 w-4" aria-hidden />
                      </button>
                    </form>
                  ) : (
                    <>
                      <div className="flex min-w-0 flex-1 items-center gap-2">
                        <span className="truncate text-sm font-medium">{preset.name}</span>
                        {isActive ? <Badge tone="success">{t("settings.presets.active")}</Badge> : null}
                        {isActive && dirty ? <Badge tone="warning">{t("settings.presets.unsaved")}</Badge> : null}
                      </div>
                      {!isActive ? (
                        <button type="button" onClick={() => void activateRuntimePreset(preset.id)} className={cn(outlineBtn, "h-8")}>
                          {t("settings.presets.activate")}
                        </button>
                      ) : null}
                      <button
                        type="button"
                        onClick={() => {
                          setRenamingId(preset.id);
                          setRenameValue(preset.name);
                        }}
                        aria-label={`${t("btn.rename")}: ${preset.name}`}
                        title={t("btn.rename")}
                        className={iconBtn}
                      >
                        <Pencil className="h-3.5 w-3.5" aria-hidden />
                      </button>
                      <button
                        type="button"
                        onClick={() => void deleteRuntimePreset(preset.id)}
                        aria-label={`${t("btn.delete")}: ${preset.name}`}
                        title={t("btn.delete")}
                        className={cn(iconBtn, "hover:bg-destructive/10 hover:text-destructive")}
                      >
                        <Trash2 className="h-3.5 w-3.5" aria-hidden />
                      </button>
                    </>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </Group>
    </>
  );
}
