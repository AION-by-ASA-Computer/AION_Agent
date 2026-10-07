"use client";

import { PanelLeft, PanelRight } from "lucide-react";
import { useCallback, useState, useRef, useEffect } from "react";
import { CapabilitiesChip, type UsedTool } from "@/components/layout/CapabilitiesChip";
import type { SkillStatus } from "@/components/chat/ChatWorkspace";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";
import type { DockTab } from "@/lib/layout/dock-tab";

export type AgentMode = "normal" | "plan" | "ask" | "debug" | "deep_research";

export function ChatHeader({
  dockTab,
  onToggleDock,
  isSidebarOpen,
  onToggleSidebar,
  title,
  onTitleChange,
  usedTools,
  skillStatuses,
}: {
  conversationId?: string;
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
  llmProviders?: unknown[];
  selectedProvider?: string | null;
  providersLoading?: boolean;
  onProviderChange?: (slug: string | null) => void;
  /** Tool MCP effettivamente invocati nella conversazione corrente (dai segmenti SSE). */
  usedTools?: UsedTool[];
  /** Skill con stato di caricamento reale derivato dai segmenti skill_view. */
  skillStatuses?: SkillStatus[];
}) {
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
        "grid shrink-0 gap-3 border-b border-black/[0.06] dark:border-white/[0.08] bg-background/70 dark:bg-background/50 px-4 py-2 backdrop-blur-xl z-30 transition-all duration-300",
        "grid-cols-1 items-start sm:grid-cols-[minmax(0,auto)_minmax(0,1fr)_minmax(0,auto)] sm:items-center"
      )}
    >
      {/* Left: Pill-style badge for Sidebar Toggle and Title */}
      <div className="flex items-center gap-2 min-w-0">
        <div className="flex items-center gap-1.5 rounded-full border border-black/[0.08] dark:border-white/[0.08] bg-card/60 dark:bg-card/40 px-2 py-1 backdrop-blur-md shadow-2xs">
          {onToggleSidebar && (
            <button
              type="button"
              onClick={onToggleSidebar}
              className={cn(
                "focus-ring shrink-0 rounded-full p-1 transition-all duration-200 hover:bg-muted text-muted-foreground hover:text-foreground",
                isSidebarOpen && "bg-muted/80 text-foreground"
              )}
              title={isSidebarOpen ? t("header.toggle_sidebar.hide") : t("header.toggle_sidebar.show")}
            >
              <PanelLeft size={15} aria-hidden />
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
              className="w-36 sm:w-56 px-2.5 py-0.5 text-xs font-semibold text-foreground bg-muted/50 border border-primary/40 rounded-full focus:outline-none focus:ring-2 focus:ring-primary/20 transition-all"
            />
          ) : (
            <div
              onDoubleClick={handleDoubleClick}
              className="group flex items-center gap-1.5 min-w-0 cursor-pointer px-1.5 py-0.5 rounded-full hover:bg-muted/40 transition-colors"
              title={t("header.edit_title")}
            >
              <span className="truncate text-xs sm:text-sm font-semibold text-foreground select-none max-w-[12rem] sm:max-w-[18rem]">
                {title || t("header.new_conversation")}
              </span>
            </div>
          )}
        </div>
      </div>

      {/* Right: Dock Toggle Button */}
      <div className="flex items-center gap-2 sm:justify-end">
        {onToggleDock && (
          <div className="flex items-center rounded-full border border-black/[0.08] dark:border-white/[0.08] bg-card/60 dark:bg-card/40 p-1 backdrop-blur-xl shadow-2xs">
            <button
              type="button"
              onClick={onToggleDock}
              className={cn(
                "focus-ring shrink-0 rounded-full p-1.5 transition-all duration-200 text-muted-foreground hover:text-foreground hover:bg-muted/60",
                dockTab !== "none" && "bg-muted text-foreground"
              )}
              title={dockTab !== "none" ? t("header.toggle_dock.hide") : t("header.toggle_dock.show")}
            >
              <PanelRight size={15} aria-hidden />
            </button>
          </div>
        )}
      </div>
    </header >
  );
}
