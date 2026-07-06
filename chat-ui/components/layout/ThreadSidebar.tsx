"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  Check,
  Clock,
  Edit3,
  MessageSquare,
  MessageSquarePlus,
  MoreHorizontal,
  PanelLeftClose,
  PanelLeftOpen,
  Plug,
  Search,
  Star,
  Trash2,
  X,
} from "lucide-react";

import { type ConversationSummary } from "@/lib/api/aion";
import { apiBase } from "@/lib/config";
import { BUCKET_ORDER, groupByBucket, type DateBucket } from "@/lib/date-groups";
import type { ShellSection } from "@/lib/shell/use-conversation-threads";
import { cn } from "@/lib/cn";
import { ChatBrand } from "../brand/ChatBrand";
import { SidebarProfileMenu } from "./SidebarProfileMenu";
import { useStoredToken } from "@/lib/auth/use-stored-auth";
import { useT } from "@/lib/i18n/use-t";

function isFavorite(c: ConversationSummary) {
  return c.metadata?.favorite === true || c.metadata?.favorite === "true";
}

function bucketLabelKey(bucket: DateBucket) {
  return `sidebar.bucket_${bucket}` as const;
}

export function ThreadSidebar({
  currentId,
  userId,
  items,
  onRefresh,
  onSelectConversation,
  onDeleteConversation,
  onRenameConversation,
  onToggleFavorite,
  activeSection = "chat",
  chatHomeHref = "/",
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
  activeSection?: ShellSection;
  chatHomeHref?: string;
  isCollapsed?: boolean;
  onToggleCollapse?: () => void;
}) {
  const router = useRouter();
  const token = useStoredToken();
  const isLoggedIn = Boolean(token);
  const t = useT();

  const [searchQuery, setSearchQuery] = useState("");
  const [profileLabel, setProfileLabel] = useState(userId);
  const [profileSubtitle, setProfileSubtitle] = useState("");
  const [avatarUrl, setAvatarUrl] = useState("");
  const [profileColor, setProfileColor] = useState("violet");

  const loadProfile = useCallback(() => {
    if (!token) return;
    void fetch(`${apiBase()}/auth/me`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((res) => (res.ok ? res.json() : null))
      .then(
        (
          data: {
            display_name?: string;
            identifier?: string;
            email?: string;
            metadata?: { avatar_url?: string; profile_color?: string };
          } | null,
        ) => {
          if (!data) return;
          setProfileLabel(data.display_name || data.identifier || userId);
          setProfileSubtitle(data.email || data.identifier || "");
          setAvatarUrl(data.metadata?.avatar_url || "");
          setProfileColor(data.metadata?.profile_color || "violet");
        },
      )
      .catch(() => {
        /* ignore */
      });
  }, [token, userId]);

  useEffect(() => {
    loadProfile();
  }, [loadProfile]);

  useEffect(() => {
    const onProfileUpdated = () => loadProfile();
    window.addEventListener("aion-profile-updated", onProfileUpdated);
    return () => window.removeEventListener("aion-profile-updated", onProfileUpdated);
  }, [loadProfile]);

  const filteredItems = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    if (!q) return items;
    return items.filter(
      (c) =>
        (c.title || "").toLowerCase().includes(q) ||
        c.id.toLowerCase().includes(q),
    );
  }, [items, searchQuery]);

  const favoritedItems = useMemo(
    () => filteredItems.filter(isFavorite),
    [filteredItems],
  );
  const normalItems = useMemo(
    () => filteredItems.filter((c) => !isFavorite(c)),
    [filteredItems],
  );
  const dateGroups = useMemo(() => groupByBucket(normalItems), [normalItems]);

  const startNewChat = () => {
    const id = crypto.randomUUID();
    if (onSelectConversation) {
      onSelectConversation(id);
    } else {
      router.push(`/c/${id}`);
    }
  };

  const navItems: Array<{
    section: ShellSection;
    href: string;
    icon: typeof MessageSquare;
    label: string;
  }> = [
    { section: "chat", href: chatHomeHref, icon: MessageSquare, label: t("sidebar.chat") },
    { section: "integrations", href: "/integrations", icon: Plug, label: t("sidebar.integrations") },
    { section: "schedules", href: "/schedules", icon: Clock, label: t("sidebar.schedules") },
  ];

  const conversationList = (
    <>
      {favoritedItems.length > 0 ? (
        <>
          <SectionHeader>
            <Star className="h-3 w-3 fill-current" />
            {t("sidebar.favorites")}
          </SectionHeader>
          {favoritedItems.map((c) => (
            <ConversationRow
              key={c.id}
              conv={c}
              currentId={currentId}
              isFavorite
              onSelectConversation={onSelectConversation}
              onDeleteConversation={onDeleteConversation}
              onRenameConversation={onRenameConversation}
              onToggleFavorite={onToggleFavorite}
              onRefresh={onRefresh}
            />
          ))}
        </>
      ) : null}

      {BUCKET_ORDER.map((bucket) => {
        const bucketItems = dateGroups.get(bucket);
        if (!bucketItems?.length) return null;
        return (
          <div key={bucket} className="mt-2">
            <SectionHeader>{t(bucketLabelKey(bucket))}</SectionHeader>
            {bucketItems.map((c) => (
              <ConversationRow
                key={c.id}
                conv={c}
                currentId={currentId}
                isFavorite={false}
                onSelectConversation={onSelectConversation}
                onDeleteConversation={onDeleteConversation}
                onRenameConversation={onRenameConversation}
                onToggleFavorite={onToggleFavorite}
                onRefresh={onRefresh}
              />
            ))}
          </div>
        );
      })}

      {filteredItems.length === 0 ? (
        <p className="mt-4 px-2 text-xs text-muted-foreground">{t("sidebar.no_conversations")}</p>
      ) : null}
    </>
  );

  const profileFooter = (
    <div className="border-t border-sidebar-border/60 p-3">
      <SidebarProfileMenu
        profileLabel={profileLabel}
        profileSubtitle={profileSubtitle}
        avatarUrl={avatarUrl}
        profileColor={profileColor}
        isLoggedIn={isLoggedIn}
        variant="expanded"
      />
    </div>
  );

  if (isCollapsed) {
    return (
      <aside className="flex h-full w-full flex-col items-center py-3">
        <button
          type="button"
          onClick={onToggleCollapse}
          className="mb-3 inline-flex h-9 w-9 items-center justify-center rounded-full text-muted-foreground transition hover:bg-muted/60"
          aria-label={t("sidebar.expand")}
          title={t("sidebar.expand")}
        >
          <PanelLeftOpen className="h-4 w-4" aria-hidden />
        </button>

        <button
          type="button"
          onClick={startNewChat}
          className="mb-3 inline-flex h-9 w-9 items-center justify-center rounded-full bg-primary text-primary-foreground transition hover:bg-primary/90"
          aria-label={t("sidebar.new_conversation")}
          title={t("sidebar.new_conversation")}
        >
          <MessageSquarePlus className="h-4 w-4" aria-hidden />
        </button>

        <nav className="flex flex-col items-center gap-1">
          {navItems.map((item) => {
            const Icon = item.icon;
            const active = activeSection === item.section;
            return (
              <Link
                key={item.section}
                href={item.href}
                title={item.label}
                aria-label={item.label}
                className={cn(
                  "inline-flex h-9 w-9 items-center justify-center rounded-md transition",
                  active
                    ? "bg-primary/10 text-foreground"
                    : "text-muted-foreground hover:bg-muted/60 hover:text-foreground",
                )}
              >
                <Icon className="h-4 w-4" aria-hidden />
              </Link>
            );
          })}
        </nav>

        <div className="mt-auto flex flex-col items-center gap-2 border-t border-sidebar-border/60 pt-3">
          <SidebarProfileMenu
            profileLabel={profileLabel}
            profileSubtitle={profileSubtitle}
            avatarUrl={avatarUrl}
            profileColor={profileColor}
            isLoggedIn={isLoggedIn}
            variant="collapsed"
          />
        </div>
      </aside>
    );
  }

  return (
    <aside className="flex h-full w-full flex-col">
      <div className="shrink-0">
        <div className="flex items-center justify-between px-4 pb-3 pt-4">
          <div className="min-w-0 flex-1">
            <ChatBrand className="max-w-[120px]" />
          </div>
          <button
            type="button"
            onClick={onToggleCollapse}
            className="rounded-md p-1.5 text-muted-foreground transition hover:bg-muted/60 hover:text-foreground"
            aria-label={t("sidebar.collapse")}
            title={t("sidebar.collapse")}
          >
            <PanelLeftClose className="h-4 w-4" aria-hidden />
          </button>
        </div>

        <div className="px-3">
          <button
            type="button"
            onClick={startNewChat}
            className="flex w-full items-center justify-center gap-2 rounded-lg bg-primary px-3 py-2 text-sm font-medium text-primary-foreground transition hover:bg-primary/90"
          >
            <MessageSquarePlus className="h-4 w-4" aria-hidden />
            {t("sidebar.new_conversation")}
          </button>
        </div>

        <nav className="mt-4 flex flex-col gap-0.5 px-2">
          {navItems.map((item) => {
            const Icon = item.icon;
            const active = activeSection === item.section;
            return (
              <Link
                key={item.section}
                href={item.href}
                className={cn(
                  "flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm transition",
                  active
                    ? "bg-primary/10 font-medium text-foreground"
                    : "text-muted-foreground hover:bg-muted/60 hover:text-foreground",
                )}
              >
                <Icon className="h-4 w-4 shrink-0" aria-hidden />
                <span className="truncate">{item.label}</span>
              </Link>
            );
          })}
        </nav>
      </div>

      <div className="mt-3 shrink-0 px-3 pb-2">
        <div className="flex items-center gap-2 rounded-lg border border-sidebar-border bg-background/40 px-2 py-1.5 focus-within:border-primary/50">
          <Search className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder={t("sidebar.search_placeholder")}
            className="min-w-0 flex-1 bg-transparent text-xs text-foreground placeholder:text-muted-foreground focus:outline-none"
            aria-label={t("sidebar.search_placeholder")}
          />
          {searchQuery ? (
            <button
              type="button"
              onClick={() => setSearchQuery("")}
              className="rounded p-0.5 text-muted-foreground transition hover:bg-muted/60 hover:text-foreground"
              aria-label={t("btn.cancel")}
            >
              <X className="h-3 w-3" aria-hidden />
            </button>
          ) : null}
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-2">{conversationList}</div>

      <div className="shrink-0">{profileFooter}</div>
    </aside>
  );
}

function SectionHeader({ children }: { children: React.ReactNode }) {
  return (
    <div className="mb-1 mt-3 flex items-center gap-1.5 px-2 text-[11px] font-semibold uppercase tracking-wider text-primary">
      {children}
    </div>
  );
}

function ConversationRow({
  conv,
  currentId,
  isFavorite: favorite,
  onSelectConversation,
  onDeleteConversation,
  onRenameConversation,
  onToggleFavorite,
  onRefresh,
}: {
  conv: ConversationSummary;
  currentId: string;
  isFavorite: boolean;
  onSelectConversation?: (id: string) => void;
  onDeleteConversation?: (id: string) => void;
  onRenameConversation?: (id: string, newTitle: string) => void;
  onToggleFavorite?: (id: string, isFav: boolean) => void;
  onRefresh: () => void;
}) {
  const t = useT();
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);

  const isActive = conv.id === currentId;
  const displayTitle = conv.title?.trim() || conv.id.slice(0, 16);
  const isEditing = editingId === conv.id;
  const isConfirmingDelete = confirmDeleteId === conv.id;

  if (isEditing) {
    return (
      <div className="flex items-center gap-1.5 rounded-lg border border-primary/30 bg-muted/40 px-2 py-1.5 shadow-[0_0_12px_rgba(var(--primary-rgb),0.08)]">
        <input
          type="text"
          value={editTitle}
          onChange={(e) => setEditTitle(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              if (editTitle.trim()) {
                onRenameConversation?.(conv.id, editTitle.trim());
                void onRefresh();
              }
              setEditingId(null);
            } else if (e.key === "Escape") {
              e.preventDefault();
              setEditingId(null);
            }
          }}
          className="min-w-0 flex-1 bg-transparent text-[13px] text-foreground focus:outline-none"
          autoFocus
        />
        <button
          type="button"
          onClick={() => {
            if (editTitle.trim()) {
              onRenameConversation?.(conv.id, editTitle.trim());
              void onRefresh();
            }
            setEditingId(null);
          }}
          className="rounded p-0.5 text-emerald-500 hover:text-emerald-400"
          title={t("btn.save")}
        >
          <Check size={14} />
        </button>
        <button
          type="button"
          onClick={() => setEditingId(null)}
          className="rounded p-0.5 text-muted-foreground hover:text-foreground"
          title={t("btn.cancel")}
        >
          <X size={14} />
        </button>
      </div>
    );
  }

  if (isConfirmingDelete) {
    return (
      <div className="flex items-center justify-between rounded-lg border border-rose-500/20 bg-rose-500/10 px-3 py-2 text-rose-200 animate-in fade-in zoom-in-95 duration-150">
        <span className="truncate pr-1 text-xs font-medium text-rose-400/90">
          {t("sidebar.delete_confirm")}
        </span>
        <div className="flex shrink-0 items-center gap-1">
          <button
            type="button"
            onClick={() => {
              onDeleteConversation?.(conv.id);
              setConfirmDeleteId(null);
              void onRefresh();
            }}
            className="rounded bg-rose-500 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-white shadow-sm transition-all duration-150 hover:bg-rose-600"
          >
            {t("btn.yes")}
          </button>
          <button
            type="button"
            onClick={() => setConfirmDeleteId(null)}
            className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-foreground transition-all duration-150 hover:bg-muted/80"
          >
            {t("btn.no")}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div
      className={cn(
        "group relative flex items-center gap-2 rounded-md px-2 py-1.5 text-sm transition",
        isActive
          ? "bg-sidebar-accent text-sidebar-foreground"
          : "text-muted-foreground hover:bg-muted/50 hover:text-foreground",
      )}
    >
      <Link
        href={`/c/${conv.id}`}
        onClick={(e) => {
          if (onSelectConversation) {
            e.preventDefault();
            onSelectConversation(conv.id);
          }
        }}
        className="flex min-w-0 flex-1 items-center gap-2 text-left"
        title={displayTitle}
      >
        {favorite ? (
          <Star className="h-3 w-3 shrink-0 fill-amber-400 text-amber-400" aria-hidden />
        ) : null}
        <span className="truncate">{displayTitle}</span>
      </Link>

      <div className="flex items-center gap-0.5 opacity-0 transition-opacity group-hover:opacity-100">
        <button
          type="button"
          onClick={() => {
            onToggleFavorite?.(conv.id, favorite);
            void onRefresh();
          }}
          className="rounded p-1 hover:bg-muted/80"
          title={favorite ? t("sidebar.remove_favorite") : t("sidebar.add_favorite")}
          aria-label={favorite ? t("sidebar.remove_favorite") : t("sidebar.add_favorite")}
        >
          <Star
            className={cn(
              "h-3 w-3",
              favorite ? "fill-amber-400 text-amber-400" : "text-muted-foreground",
            )}
          />
        </button>
        <button
          type="button"
          onClick={() => setMenuOpen((v) => !v)}
          className="rounded p-1 text-muted-foreground hover:bg-muted/80 hover:text-foreground"
          title={t("sidebar.chat_options")}
          aria-label={t("sidebar.chat_options")}
        >
          <MoreHorizontal className="h-3.5 w-3.5" />
        </button>
      </div>

      {menuOpen ? (
        <>
          <button
            type="button"
            className="fixed inset-0 z-40"
            aria-label={t("btn.cancel")}
            onClick={() => setMenuOpen(false)}
          />
          <div className="absolute right-0 top-full z-50 mt-1 w-40 rounded-xl border border-border bg-popover/95 p-1.5 text-popover-foreground shadow-xl backdrop-blur-md">
            <button
              type="button"
              onClick={() => {
                setEditingId(conv.id);
                setEditTitle(conv.title || "");
                setMenuOpen(false);
              }}
              className="flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-xs text-muted-foreground hover:bg-muted/60 hover:text-foreground"
            >
              <Edit3 size={12} />
              {t("sidebar.rename")}
            </button>
            <button
              type="button"
              onClick={() => {
                setConfirmDeleteId(conv.id);
                setMenuOpen(false);
              }}
              className="flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-xs text-rose-500 hover:bg-rose-500/10 hover:text-rose-400"
            >
              <Trash2 size={12} />
              {t("sidebar.delete")}
            </button>
          </div>
        </>
      ) : null}
    </div>
  );
}
