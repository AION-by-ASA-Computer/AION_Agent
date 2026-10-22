"use client";

import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState, useSyncExternalStore } from "react";
import { createPortal } from "react-dom";
import { Bookmark, Check, ChevronDown, Loader2, Pencil, Plus, Save, Trash2, X } from "lucide-react";

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
import { Badge, iconBtn, inputCls, outlineBtn, solidBtn } from "./ui";

const GAP = 6;
/** Panel width at the default 14px root; scaled with the chat text size like the rest of settings. */
const PANEL_WIDTH = 340;

type Pos = { top?: number; bottom?: number; left: number; width: number; maxHeight: number };

/**
 * Preset switcher for the Tunings header: the trigger names the active preset, the panel
 * activates, renames, deletes, overwrites the active one and saves the current values as new.
 */
export function RuntimePresetMenu({ defaultOpen = false }: { defaultOpen?: boolean }) {
  const t = useT();
  const uid = useId();
  const snap = useSyncExternalStore(
    subscribeRuntimeSettings,
    getRuntimeSettingsSnapshot,
    getRuntimeSettingsSnapshot,
  );
  const btn = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(defaultOpen);
  const [pos, setPos] = useState<Pos | null>(null);
  const [newName, setNewName] = useState("");
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [busy, setBusy] = useState(false);

  const keys = sidebarRuntimeSchema().map((f) => f.key);
  const active = snap.presets.find((p) => p.id === snap.activePresetId);
  const dirty = Boolean(active) && !valuesEqual(snap.values, active?.values || {}, keys);

  const place = useCallback(() => {
    const el = btn.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const scale = parseFloat(getComputedStyle(document.documentElement).fontSize) / 14 || 1;
    const width = Math.min(window.innerWidth - 16, PANEL_WIDTH * scale);
    const left = Math.max(8, Math.min(window.innerWidth - width - 8, r.right - width));
    const below = window.innerHeight - r.bottom - GAP - 8;
    const above = r.top - GAP - 8;
    const up = below < 280 && above > below;
    const maxHeight = Math.max(200, up ? above : below);
    setPos(
      up
        ? { bottom: window.innerHeight - r.top + GAP, left, width, maxHeight }
        : { top: r.bottom + GAP, left, width, maxHeight },
    );
  }, []);

  const close = useCallback((refocus = true) => {
    setOpen(false);
    setRenamingId(null);
    if (refocus) btn.current?.focus();
  }, []);

  useLayoutEffect(() => {
    if (open) place();
  }, [open, place]);

  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => {
      const n = e.target as Node;
      if (!panel.current?.contains(n) && !btn.current?.contains(n)) close(false);
    };
    const onScroll = (e: Event) => {
      if (panel.current?.contains(e.target as Node)) return;
      place();
    };
    document.addEventListener("mousedown", away);
    window.addEventListener("scroll", onScroll, true);
    window.addEventListener("resize", place);
    return () => {
      document.removeEventListener("mousedown", away);
      window.removeEventListener("scroll", onScroll, true);
      window.removeEventListener("resize", place);
    };
  }, [open, place, close]);

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

  const panelId = `${uid}-presets`;
  const triggerName = active ? active.name : t("settings.presets.none");

  return (
    <div className="flex max-w-full flex-wrap items-center gap-2">
      {dirty && active ? (
        <button
          type="button"
          disabled={busy}
          onClick={() => void handleSaveActive()}
          title={t("settings.presets.save_to", { name: active.name })}
          className={solidBtn}
        >
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <Save className="h-3.5 w-3.5" aria-hidden />}
          {t("btn.save")}
        </button>
      ) : null}
      <button
        ref={btn}
        type="button"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
        disabled={!snap.loaded}
        onClick={() => (open ? close(false) : setOpen(true))}
        className={cn(outlineBtn, "max-w-full pr-2.5", open && "border-foreground/40 bg-secondary/60")}
      >
        <Bookmark className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
        <span className="text-muted-foreground">{t("settings.tab.presets")}</span>
        <span className={cn("min-w-0 max-w-[14rem] truncate", !active && "text-muted-foreground")}>{triggerName}</span>
        {dirty ? (
          <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-warning" title={t("settings.presets.unsaved")}>
            <span className="sr-only">{t("settings.presets.unsaved")}</span>
          </span>
        ) : null}
        <ChevronDown
          className={cn("h-4 w-4 shrink-0 text-muted-foreground transition-transform duration-150", open && "rotate-180")}
          aria-hidden
        />
      </button>

      {open &&
        pos &&
        createPortal(
          <div
            ref={panel}
            id={panelId}
            role="dialog"
            aria-label={t("settings.tab.presets")}
            onKeyDown={(e) => {
              if (e.key === "Escape" && !renamingId) {
                e.preventDefault();
                close();
              }
            }}
            style={{ position: "fixed", top: pos.top, bottom: pos.bottom, left: pos.left, width: pos.width, maxHeight: pos.maxHeight }}
            className="settings-scope z-[100] flex flex-col overflow-hidden rounded-2xl border border-border bg-popover text-sm text-popover-foreground shadow-[0_18px_40px_-16px_rgba(0,0,0,0.5)]"
          >
            <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain p-1.5">
              {snap.presets.length === 0 ? (
                <p className="px-3 py-6 text-center text-muted-foreground">{t("settings.presets.empty")}</p>
              ) : (
                <ul className="flex flex-col gap-0.5">
                  {snap.presets.map((preset) => {
                    const isActive = preset.id === snap.activePresetId;
                    if (renamingId === preset.id) {
                      return (
                        <li key={preset.id}>
                          <form
                            className="flex items-center gap-1 px-1 py-1"
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
                                if (e.key === "Escape") {
                                  e.preventDefault();
                                  setRenamingId(null);
                                }
                              }}
                              maxLength={40}
                              aria-label={t("btn.rename")}
                              className={cn(inputCls, "h-8 rounded-lg px-2.5 py-0")}
                            />
                            <button type="submit" aria-label={t("btn.save")} className={iconBtn}>
                              <Check className="h-4 w-4" aria-hidden />
                            </button>
                            <button
                              type="button"
                              aria-label={t("btn.cancel")}
                              onClick={() => setRenamingId(null)}
                              className={iconBtn}
                            >
                              <X className="h-4 w-4" aria-hidden />
                            </button>
                          </form>
                        </li>
                      );
                    }
                    return (
                      <li
                        key={preset.id}
                        className={cn(
                          "group/preset flex items-center gap-0.5 rounded-lg pr-1 transition-colors",
                          isActive ? "bg-secondary" : "hover:bg-secondary/60",
                        )}
                      >
                        <button
                          type="button"
                          aria-current={isActive ? "true" : undefined}
                          onClick={() => {
                            if (!isActive) void activateRuntimePreset(preset.id);
                            close();
                          }}
                          className="focus-ring flex min-h-9 min-w-0 flex-1 items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-left"
                        >
                          <Check
                            className={cn("h-4 w-4 shrink-0", isActive ? "text-foreground" : "invisible")}
                            aria-hidden
                          />
                          <span className={cn("min-w-0 truncate", isActive && "font-medium")}>{preset.name}</span>
                          {isActive && dirty ? <Badge tone="warning">{t("settings.presets.unsaved")}</Badge> : null}
                        </button>
                        <button
                          type="button"
                          onClick={() => {
                            setRenamingId(preset.id);
                            setRenameValue(preset.name);
                          }}
                          aria-label={`${t("btn.rename")}: ${preset.name}`}
                          title={t("btn.rename")}
                          className={cn(
                            iconBtn,
                            "h-7 w-7 hover:bg-background [@media(hover:hover)]:opacity-0 [@media(hover:hover)]:group-hover/preset:opacity-100 [@media(hover:hover)]:focus-visible:opacity-100",
                          )}
                        >
                          <Pencil className="h-3.5 w-3.5" aria-hidden />
                        </button>
                        <button
                          type="button"
                          onClick={() => void deleteRuntimePreset(preset.id)}
                          aria-label={`${t("btn.delete")}: ${preset.name}`}
                          title={t("btn.delete")}
                          className={cn(
                            iconBtn,
                            "h-7 w-7 hover:bg-destructive/10 hover:text-destructive [@media(hover:hover)]:opacity-0 [@media(hover:hover)]:group-hover/preset:opacity-100 [@media(hover:hover)]:focus-visible:opacity-100",
                          )}
                        >
                          <Trash2 className="h-3.5 w-3.5" aria-hidden />
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>

            <form
              className="flex flex-col gap-2 border-t border-border/60 bg-secondary/40 px-3 py-3"
              onSubmit={(e) => {
                e.preventDefault();
                void handleCreate();
              }}
            >
              <label htmlFor={`${uid}-new`} className="text-xs font-medium text-muted-foreground">
                {t("settings.presets.new_title")}
              </label>
              <div className="flex gap-2">
                <input
                  id={`${uid}-new`}
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  placeholder={t("settings.presets.name_placeholder")}
                  maxLength={40}
                  className={cn(inputCls, "h-9 min-w-0 flex-1 py-0")}
                />
                <button type="submit" disabled={busy || !newName.trim()} className={cn(solidBtn, "shrink-0")}>
                  {busy ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
                  ) : (
                    <Plus className="h-3.5 w-3.5" aria-hidden />
                  )}
                  {t("settings.presets.save_as")}
                </button>
              </div>
              <p className="text-xs text-muted-foreground">{t("settings.presets.hint")}</p>
            </form>
          </div>,
          document.body,
        )}
    </div>
  );
}
