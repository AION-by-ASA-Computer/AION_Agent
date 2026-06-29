"use client";

import React, { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  Plus,
  Settings,
  LogIn,
  Edit3,
  Trash2,
  Check,
  X,
  Plug,
  Clock,
  Search,
  Star,
  MoreHorizontal,
  PanelLeftClose,
  PanelLeftOpen,
  Sparkles,
} from "lucide-react";
import { type ConversationSummary } from "@/lib/api/aion";
import { cn } from "@/lib/cn";
import { ChatBrand } from "../brand/ChatBrand";
import { useStoredToken } from "@/lib/auth/use-stored-auth";
import { useT } from "@/lib/i18n/use-t";
import { AGENT_VERSION } from "@/lib/version";

export function ThreadSidebar({
  currentId,
  userId,
  items,
  onRefresh,
  onSelectConversation,
  onDeleteConversation,
  onRenameConversation,
  onToggleFavorite,
  isCollapsed = false,
  onToggleCollapse,
}: {
  currentId: string;
  userId: string;
  items: ConversationSummary[];
  onRefresh: () => void;
  onSelectConversation?: (id: string) => void;
  onDeleteConversation?: (id: string) => void;
  onRenameConversation?: (id: string, newTitle: string) => void;
  onToggleFavorite?: (id: string, isFav: boolean) => void;
  isCollapsed?: boolean;
  onToggleCollapse?: () => void;
}) {
  const router = useRouter();
  const token = useStoredToken();
  const isLoggedIn = Boolean(token);
  const t = useT();

  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [activeMenuId, setActiveMenuId] = useState<string | null>(null);



  const getInitials = (title: string) => {
    if (!title) return "CH";
    const cleaned = title.trim().replace(/[★\*]/g, "");
    const words = cleaned.split(/\s+/).filter(Boolean);
    if (words.length >= 2) {
      return (words[0][0] + words[1][0]).toUpperCase().slice(0, 2);
    }
    return cleaned.slice(0, 2).toUpperCase() || "CH";
  };

  const filteredItems = items.filter((c) => {
    const title = (c.title || "").toLowerCase();
    const query = searchQuery.toLowerCase();
    return title.includes(query) || c.id.toLowerCase().includes(query);
  });

  const favoritedItems = filteredItems.filter(
    (c) => c.metadata?.favorite === true || c.metadata?.favorite === "true"
  );
  const normalItems = filteredItems.filter(
    (c) => c.metadata?.favorite !== true && c.metadata?.favorite !== "true"
  );

  const renderRow = (c: ConversationSummary, isFavorite: boolean) => {
    const isSelected = c.id === currentId;
    const isEditing = editingId === c.id;
    const isConfirmingDelete = confirmDeleteId === c.id;
    const displayTitle = c.title || c.id.slice(0, 16);

    if (isEditing) {
      return (
        <li key={c.id} className="list-none">
          <div className="flex items-center gap-1.5 rounded-lg bg-muted/40 px-2 py-1.5 border border-primary/30 shadow-[0_0_12px_rgba(var(--primary-rgb),0.08)]">
            <input
              type="text"
              value={editTitle}
              onChange={(e) => setEditTitle(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  e.stopPropagation();
                  if (editTitle.trim()) {
                    onRenameConversation?.(c.id, editTitle.trim());
                  }
                  setEditingId(null);
                } else if (e.key === "Escape") {
                  e.preventDefault();
                  e.stopPropagation();
                  setEditingId(null);
                }
              }}
              onClick={(e) => e.stopPropagation()}
              className="w-full bg-transparent text-[13px] text-foreground focus:outline-none placeholder-muted-foreground"
              autoFocus
            />
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                if (editTitle.trim()) {
                  onRenameConversation?.(c.id, editTitle.trim());
                }
                setEditingId(null);
              }}
              className="text-emerald-500 hover:text-emerald-400 p-0.5 rounded transition-colors"
              title={t("btn.save")}
            >
              <Check size={14} />
            </button>
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                setEditingId(null);
              }}
              className="text-muted-foreground hover:text-foreground p-0.5 rounded transition-colors"
              title={t("btn.cancel")}
            >
              <X size={14} />
            </button>
          </div>
        </li>
      );
    }

    if (isConfirmingDelete) {
      return (
        <li key={c.id} className="list-none">
          <div className="flex items-center justify-between rounded-lg bg-rose-500/10 border border-rose-500/20 px-3 py-2 text-rose-200 animate-in fade-in zoom-in-95 duration-150">
            <span className="truncate text-xs font-medium text-rose-400/90 pr-1">{t("sidebar.delete_confirm")}</span>
            <div className="flex items-center gap-1 shrink-0">
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  onDeleteConversation?.(c.id);
                  setConfirmDeleteId(null);
                }}
                className="bg-rose-500 hover:bg-rose-600 text-white rounded px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider shadow-sm transition-all duration-150"
              >
                {t("btn.yes")}
              </button>
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  setConfirmDeleteId(null);
                }}
                className="bg-muted hover:bg-muted/80 text-foreground rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider transition-all duration-150"
              >
                {t("btn.no")}
              </button>
            </div>
          </div>
        </li>
      );
    }

    return (
      <li key={c.id} className="group relative list-none animate-in fade-in duration-100">
        <div className="relative flex items-center group/row w-full">
          <Link
            href={`/c/${c.id}`}
            onClick={(e) => {
              if (onSelectConversation) {
                e.preventDefault();
                onSelectConversation(c.id);
              }
            }}
            className={cn(
              "focus-ring block w-full truncate rounded-lg pl-3 pr-10 py-2 transition-all duration-200 text-muted-foreground hover:bg-sidebar-accent/50 hover:text-sidebar-foreground",
              isSelected && "bg-sidebar-accent font-semibold text-sidebar-foreground shadow-sm border-l-2 border-primary pl-2.5 rounded-l-none"
            )}
            title={displayTitle}
          >
            {isFavorite && <Star size={11} className="inline-block fill-amber-400 text-amber-400 mr-1.5 -translate-y-[1px]" />}
            {displayTitle}
          </Link>

          <div className="absolute right-2 flex items-center opacity-0 group-hover/row:opacity-100 transition-opacity duration-200 z-10">
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                e.preventDefault();
                setActiveMenuId(activeMenuId === c.id ? null : c.id);
              }}
              className="text-muted-foreground hover:text-foreground hover:bg-muted/85 p-1 rounded-md transition-all duration-150"
              title="Opzioni chat"
            >
              <MoreHorizontal size={14} />
            </button>

            {activeMenuId === c.id && (
              <>
                <div
                  className="fixed inset-0 z-40 bg-transparent"
                  onClick={(e) => {
                    e.stopPropagation();
                    e.preventDefault();
                    setActiveMenuId(null);
                  }}
                />
                <div className="absolute right-0 top-full z-50 mt-1 w-40 rounded-xl border border-sidebar-border bg-popover/95 p-1.5 text-popover-foreground shadow-xl backdrop-blur-md animate-in fade-in-0 zoom-in-95 duration-100">
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      e.preventDefault();
                      onToggleFavorite?.(c.id, isFavorite);
                      setActiveMenuId(null);
                    }}
                    className="flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-xs text-muted-foreground hover:bg-muted/60 hover:text-foreground transition-all duration-150"
                  >
                    <Star size={12} className={cn(isFavorite ? "fill-amber-400 text-amber-400" : "text-muted-foreground")} />
                    <span>{isFavorite ? "Rimuovi preferito" : "Metti preferito"}</span>
                  </button>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      e.preventDefault();
                      setEditingId(c.id);
                      setEditTitle(c.title || "");
                      setActiveMenuId(null);
                    }}
                    className="flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-xs text-muted-foreground hover:bg-muted/60 hover:text-foreground transition-all duration-150"
                  >
                    <Edit3 size={12} />
                    <span>Rinomina</span>
                  </button>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      e.preventDefault();
                      setConfirmDeleteId(c.id);
                      setActiveMenuId(null);
                    }}
                    className="flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-xs text-rose-500 hover:bg-rose-500/10 hover:text-rose-400 transition-all duration-150"
                  >
                    <Trash2 size={12} />
                    <span>Elimina</span>
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      </li>
    );
  };

  const renderCollapsedRow = (c: ConversationSummary, isFavorite: boolean) => {
    const isSelected = c.id === currentId;
    const displayTitle = c.title || c.id.slice(0, 16);
    const initials = getInitials(displayTitle);

    return (
      <li key={c.id} className="relative group flex justify-center list-none py-1.5">
        <Link
          href={`/c/${c.id}`}
          onClick={(e) => {
            if (onSelectConversation) {
              e.preventDefault();
              onSelectConversation(c.id);
            }
          }}
          className={cn(
            "relative flex h-10 w-10 items-center justify-center rounded-xl text-[11px] font-bold uppercase tracking-wider transition-all duration-200",
            isSelected
              ? "bg-muted/80 text-foreground border border-primary/40 shadow-[0_0_10px_rgba(var(--primary-rgb),0.1)] scale-105"
              : "bg-muted/15 text-muted-foreground border border-border/10 hover:bg-muted/40 hover:text-foreground hover:scale-[1.02]"
          )}
        >
          {initials}
          {isFavorite && (
            <span className="absolute -bottom-0.5 -right-0.5 flex h-3.5 w-3.5 items-center justify-center rounded-full bg-amber-500 text-white shadow-sm border border-sidebar-background">
              <Star size={7} className="fill-white text-white" />
            </span>
          )}
        </Link>
        
        {/* Sleek Tooltip */}
        <div className="absolute left-full top-1/2 -translate-y-1/2 ml-3 pointer-events-none z-50 opacity-0 -translate-x-2 group-hover:opacity-100 group-hover:translate-x-0 transition-all duration-200 bg-popover/95 backdrop-blur-md text-popover-foreground text-xs rounded-lg px-2.5 py-1.5 border border-border shadow-md whitespace-nowrap">
          {displayTitle}
        </div>
      </li>
    );
  };

  if (isCollapsed) {
    return (
      <aside className="flex h-full w-full flex-col bg-transparent">
        {/* Spacer to align with header */}
        <div className="h-[60px] shrink-0 border-b border-border/20" />

        {/* Collapsed Actions Stack */}
        <div className="flex flex-col items-center gap-3 px-2 py-5 flex-1">
          <button
            type="button"
            onClick={() => {
              const id = crypto.randomUUID();
              if (onSelectConversation) {
                onSelectConversation(id);
              } else {
                router.push(`/c/${id}`);
              }
            }}
            className="relative group flex h-10 w-10 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-sm transition-all duration-200 hover:bg-primary/95 hover:shadow-md hover:scale-105 active:scale-95"
          >
            <Plus size={18} />
            <div className="absolute left-full top-1/2 -translate-y-1/2 ml-3 pointer-events-none z-50 opacity-0 -translate-x-2 group-hover:opacity-100 group-hover:translate-x-0 transition-all duration-200 bg-popover/95 backdrop-blur-md text-popover-foreground text-xs rounded-lg px-2.5 py-1.5 border border-border shadow-md whitespace-nowrap">
              Nuova Chat
            </div>
          </button>

          <Link
            href="/integrations"
            className="relative group flex h-10 w-10 items-center justify-center rounded-xl border border-border/70 bg-muted/40 text-muted-foreground shadow-sm transition-all duration-200 hover:bg-muted/75 hover:text-foreground hover:scale-105 active:scale-95"
          >
            <Plug size={16} />
            <div className="absolute left-full top-1/2 -translate-y-1/2 ml-3 pointer-events-none z-50 opacity-0 -translate-x-2 group-hover:opacity-100 group-hover:translate-x-0 transition-all duration-200 bg-popover/95 backdrop-blur-md text-popover-foreground text-xs rounded-lg px-2.5 py-1.5 border border-border shadow-md whitespace-nowrap">
              Le mie Integrazioni
            </div>
          </Link>

          <Link
            href="/schedules"
            className="relative group flex h-10 w-10 items-center justify-center rounded-xl border border-border/70 bg-muted/40 text-muted-foreground shadow-sm transition-all duration-200 hover:bg-muted/75 hover:text-foreground hover:scale-105 active:scale-95"
          >
            <Clock size={16} />
            <div className="absolute left-full top-1/2 -translate-y-1/2 ml-3 pointer-events-none z-50 opacity-0 -translate-x-2 group-hover:opacity-100 group-hover:translate-x-0 transition-all duration-200 bg-popover/95 backdrop-blur-md text-popover-foreground text-xs rounded-lg px-2.5 py-1.5 border border-border shadow-md whitespace-nowrap">
              {t("sidebar.schedules")}
            </div>
          </Link>
        </div>

        {/* Collapsed Footer */}
        <div className="shrink-0 border-t border-border/40 px-2 py-4 flex flex-col items-center gap-3 bg-muted/10">
          {!isLoggedIn ? (
            <Link
              href="/login"
              className="relative group flex h-9 w-9 items-center justify-center rounded-xl text-red-500 hover:bg-red-500/10 hover:text-red-400 transition-colors"
            >
              <LogIn size={15} />
              <div className="absolute left-full top-1/2 -translate-y-1/2 ml-3 pointer-events-none z-50 opacity-0 -translate-x-2 group-hover:opacity-100 group-hover:translate-x-0 transition-all duration-200 bg-popover/95 backdrop-blur-md text-popover-foreground text-xs rounded-lg px-2.5 py-1.5 border border-border shadow-md whitespace-nowrap">
                {t("sidebar.login")}
              </div>
            </Link>
          ) : (
            <Link
              href="/settings"
              className="relative group flex h-9 w-9 items-center justify-center rounded-xl border border-border/50 bg-muted/20 text-muted-foreground transition-all hover:bg-muted/50 hover:text-foreground"
            >
              <Settings size={15} className="group-hover:rotate-45 transition-transform duration-300" />
              <div className="absolute left-full top-1/2 -translate-y-1/2 ml-3 pointer-events-none z-50 opacity-0 -translate-x-2 group-hover:opacity-100 group-hover:translate-x-0 transition-all duration-200 bg-popover/95 backdrop-blur-md text-popover-foreground text-xs rounded-lg px-2.5 py-1.5 border border-border shadow-md whitespace-nowrap">
                {t("sidebar.settings")}
              </div>
            </Link>
          )}
        </div>
      </aside>
    );
  }

  // Expanded View
  return (
    <aside className="flex h-full w-full flex-col bg-transparent">
      {/* Top Header Section styled Claude/Gemini */}
      <div className="flex flex-col gap-3 px-3.5 pt-5 pb-3 border-b border-border/20">
        <div className="flex items-center px-1">
          <ChatBrand />
        </div>

        {/* Action Stack Buttons */}
        <div className="flex flex-col gap-2 mt-1">
          <button
            type="button"
            title={t("sidebar.new_conversation")}
            className="flex items-center gap-3 w-full rounded-xl bg-primary px-3.5 py-2.5 text-xs font-semibold text-primary-foreground shadow-sm transition-all duration-200 hover:bg-primary/90 hover:shadow-md hover:scale-[1.01] active:scale-[0.98]"
            onClick={() => {
              const id = crypto.randomUUID();
              if (onSelectConversation) {
                onSelectConversation(id);
              } else {
                router.push(`/c/${id}`);
              }
            }}
          >
            <Plus size={15} aria-hidden />
            <span className="truncate">{t("sidebar.new_conversation")}</span>
          </button>

          <Link
            href="/integrations"
            className="flex items-center gap-3 w-full rounded-xl border border-sidebar-border bg-sidebar-accent/40 px-3.5 py-2.5 text-xs font-semibold text-sidebar-foreground shadow-sm transition-all duration-200 hover:bg-sidebar-accent hover:scale-[1.01] active:scale-[0.98]"
          >
            <Plug size={15} aria-hidden />
            <span className="truncate">{t("sidebar.integrations")}</span>
          </Link>

          <Link
            href="/schedules"
            className="flex items-center gap-3 w-full rounded-xl border border-sidebar-border bg-sidebar-accent/40 px-3.5 py-2.5 text-xs font-semibold text-sidebar-foreground shadow-sm transition-all duration-200 hover:bg-sidebar-accent hover:scale-[1.01] active:scale-[0.98]"
          >
            <Clock size={15} aria-hidden />
            <span className="truncate">{t("sidebar.schedules")}</span>
          </Link>
        </div>

        {/* Dynamic Search Box */}
        <div className="relative mt-1">
          <input
            type="text"
            placeholder="Cerca conversazione..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full rounded-xl border border-sidebar-border bg-sidebar-accent/30 pl-8 pr-7 py-1.5 text-xs text-sidebar-foreground focus:border-primary/50 focus:outline-none placeholder-muted-foreground/65 transition-all duration-200 focus:bg-sidebar-accent/50"
          />
          <Search size={12} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground/50" />
          {searchQuery && (
            <button
              type="button"
              onClick={() => setSearchQuery("")}
              className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground/50 hover:text-foreground transition-colors p-0.5 rounded"
            >
              <X size={12} />
            </button>
          )}
        </div>
      </div>

      <nav className="flex-1 overflow-y-auto px-3.5 py-3 text-[13px]">
        {/* User Info / Refresh Header */}
        <div className="mb-4 flex items-center justify-between px-1">
          <span className="text-[11px] font-medium tracking-wide text-muted-foreground/70">ID: {userId.slice(0, 8)}...</span>
          <button
            type="button"
            className="focus-ring text-[11px] text-muted-foreground hover:text-foreground transition-colors"
            onClick={() => {
              onRefresh();
            }}
          >
            {t("sidebar.refresh")}
          </button>
        </div>

        {filteredItems.length === 0 ? (
          <p className="text-[12px] text-muted-foreground/60 text-center mt-4">{t("sidebar.no_conversations")}</p>
        ) : (
          <div className="flex flex-col gap-4">
            {/* FAVORITES SECTION */}
            {favoritedItems.length > 0 && (
              <div className="animate-in fade-in slide-in-from-top-1 duration-150">
                <div className="flex items-center gap-1.5 px-1 py-1 text-[10px] font-bold uppercase tracking-wider text-amber-500/80">
                  <Star size={11} className="fill-amber-500 text-amber-500" />
                  <span>Preferiti</span>
                </div>
                <ul className="space-y-1 mt-1">
                  {favoritedItems.map((c) => renderRow(c, true))}
                </ul>
              </div>
            )}

            {/* RECENT CHATS SECTION */}
            <div>
              {favoritedItems.length > 0 && (
                <div className="flex items-center gap-1.5 px-1 py-1 text-[10px] font-bold uppercase tracking-wider text-muted-foreground/55 border-t border-border/10 pt-3.5 mt-1.5">
                  <span>Recenti</span>
                </div>
              )}
              {normalItems.length === 0 && favoritedItems.length === 0 ? (
                <p className="text-[12px] text-muted-foreground/60 text-center mt-4">{t("sidebar.no_conversations")}</p>
              ) : (
                <ul className="space-y-1 mt-1">
                  {normalItems.map((c) => renderRow(c, false))}
                </ul>
              )}
            </div>
          </div>
        )}

      </nav>

      {/* Footer Settings Area */}
      <div className="shrink-0 border-t border-border/40 px-3.5 py-3 flex flex-col gap-2 bg-muted/10">
        {!isLoggedIn ? (
          <Link
            href="/login"
            className="focus-ring flex items-center justify-center gap-1.5 rounded-lg px-3 py-2 text-xs font-semibold text-red-500 hover:bg-red-500/10 hover:text-red-400 transition-colors border border-transparent hover:border-red-500/15"
          >
            <LogIn size={13} aria-hidden />
            <span>{t("sidebar.login")}</span>
          </Link>
        ) : (
          <Link
            href="/settings"
            className="focus-ring group flex items-center justify-center gap-1.5 rounded-lg border border-border/50 bg-muted/20 px-3 py-2 text-xs text-muted-foreground transition-all hover:bg-muted/50 hover:text-foreground"
            title={t("sidebar.settings")}
          >
            <Settings size={13} className="group-hover:rotate-45 transition-transform duration-300" aria-hidden />
            <span>{t("sidebar.settings")}</span>
          </Link>
        )}
        {/* Version identifier in bottom-left */}
        <div className="flex justify-between items-center px-1 mt-0.5 select-none">
          <span className="text-[10px] font-mono text-muted-foreground/45 select-none">
            AION Agent {AGENT_VERSION}
          </span>
        </div>
      </div>
    </aside>
  );
}
