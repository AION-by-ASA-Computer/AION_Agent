"use client";

import { Copy, PanelLeft, PanelRight } from "lucide-react";
import { useCallback, useState, useRef, useEffect } from "react";
import { ThemeToggle } from "@/components/theme/ThemeToggle";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";
import type { DockTab } from "@/lib/layout/dock-tab";

export type AgentMode = "normal" | "plan" | "ask" | "debug" | "deep_research";

export function ChatHeader({
  conversationId,
  dockTab,
  onToggleDock,
  isSidebarOpen,
  onToggleSidebar,
  title,
  onTitleChange,
}: {
  conversationId: string;
  profiles?: unknown[];
  profile?: string;
  onProfileChange?: (name: string) => void;
  agentMode?: AgentMode;
  onAgentModeChange?: (mode: AgentMode) => void;
  dockTab?: DockTab;
  onToggleDock?: () => void;
  isSidebarOpen?: boolean;
  onToggleSidebar?: () => void;
  title: string | null;
  onTitleChange?: (newTitle: string) => void;
}) {
  const [copied, setCopied] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [editValue, setEditValue] = useState(title || "");
  const inputRef = useRef<HTMLInputElement>(null);
  const t = useT();



  useEffect(() => {
    if (!isEditing) {
      const val = title || "";
      const handle = requestAnimationFrame(() => {
        setEditValue(val);
      });
      return () => cancelAnimationFrame(handle);
    }
  }, [title, isEditing]);

  useEffect(() => {
    if (isEditing) {
      inputRef.current?.focus();
      inputRef.current?.select();
    }
  }, [isEditing]);

  const copySession = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(conversationId);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      /* ignore */
    }
  }, [conversationId]);

  const handleSave = useCallback(() => {
    const trimmed = editValue.trim();
    if (trimmed && trimmed !== title) {
      onTitleChange?.(trimmed);
    }
    setIsEditing(false);
  }, [editValue, title, onTitleChange]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      handleSave();
    } else if (e.key === "Escape") {
      setEditValue(title || "");
      setIsEditing(false);
    }
  }, [handleSave, title]);

  const handleDoubleClick = useCallback(() => {
    setIsEditing(true);
  }, []);

  return (
    <header
      className={cn(
        "grid shrink-0 gap-3 border-b border-border bg-background/80 px-4 py-2.5 backdrop-blur-md z-30",
        "grid-cols-1 items-start sm:grid-cols-[minmax(0,auto)_minmax(0,1fr)_minmax(0,auto)] sm:items-center"
      )}
    >
      <div className="flex items-center justify-start gap-3 min-w-0">
        {onToggleSidebar && (
          <button
            type="button"
            onClick={onToggleSidebar}
            className={cn(
              "focus-ring shrink-0 rounded-lg p-1.5 transition-colors hover:bg-muted text-muted-foreground hover:text-foreground",
              isSidebarOpen && "bg-muted/50 text-foreground hover:text-foreground"
            )}
            title={isSidebarOpen ? t("header.toggle_sidebar.hide") : t("header.toggle_sidebar.show")}
          >
            <PanelLeft size={16} aria-hidden />
          </button>
        )}

        {isEditing ? (
          <input
            ref={inputRef}
            type="text"
            value={editValue}
            onChange={(e) => setEditValue(e.target.value)}
            onKeyDown={handleKeyDown}
            onBlur={handleSave}
            maxLength={100}
            className="w-40 sm:w-64 px-2.5 py-1 text-sm font-semibold text-foreground bg-muted/30 border border-border rounded-lg focus:outline-none focus:ring-1 focus:ring-primary/40 focus:border-primary/40 transition-all"
          />
        ) : (
          <div
            onDoubleClick={handleDoubleClick}
            className="group flex items-center gap-1.5 min-w-0 cursor-pointer"
            title={t("header.edit_title")}
          >
            <span className="truncate text-sm font-semibold text-foreground select-none px-1.5 py-0.5 rounded hover:bg-muted/50 transition-colors">
              {title || t("header.new_conversation")}
            </span>
            {/* <span className="opacity-0 group-hover:opacity-100 transition-opacity duration-150 text-muted-foreground/60 shrink-0">
              <Pencil size={11} aria-hidden />
            </span> */}
          </div>
        )}
      </div>

      <div className="flex min-w-0 flex-wrap items-center justify-center gap-2.5">
        {/* Center section reserved for future use */}
      </div>

      <div className="flex flex-wrap items-center gap-2 sm:justify-end">
        <button
          type="button"
          onClick={() => void copySession()}
          className="focus-ring inline-flex max-w-full items-center gap-1.5 rounded-full border border-border/80 bg-muted/30 px-2.5 py-1 font-mono text-[11px] text-muted-foreground hover:bg-muted/50 hover:text-foreground transition-all duration-200 sm:px-3"
          title={t("header.copy_session")}
        >
          <span className="hidden truncate sm:inline">Session · {conversationId.slice(0, 8)}</span>
          <Copy size={14} className="shrink-0 opacity-75 sm:hidden" aria-hidden />
          <Copy size={11} className="hidden shrink-0 opacity-75 sm:inline" aria-hidden />
          {copied ? <span className="sr-only">{t("header.copied")}</span> : null}
        </button>
        {copied ? (
          <span className="hidden text-[10px] font-medium text-emerald-500 animate-pulse sm:inline" aria-live="polite">
            {t("header.copied")}
          </span>
        ) : null}

        <ThemeToggle className="rounded-lg border border-border bg-muted/30" />
        {onToggleDock && (
          <button
            type="button"
            onClick={onToggleDock}
            className={cn(
              "focus-ring shrink-0 rounded-lg p-1.5 transition-colors hover:bg-muted text-muted-foreground hover:text-foreground border border-transparent",
              dockTab !== "none" && "bg-muted/50 text-foreground hover:text-foreground border-border"
            )}
            title={dockTab !== "none" ? t("header.toggle_dock.hide") : t("header.toggle_dock.show")}
          >
            <PanelRight size={16} aria-hidden />
          </button>
        )}
      </div>
    </header>
  );
}
