"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { usePathname, useRouter } from "next/navigation";

import {
  deleteConversation,
  listChatUiConversations,
  updateConversationMetadata,
  updateConversationTitle,
  type ConversationSummary,
} from "@/lib/api/aion";
import { useStoredToken, useStoredUserId } from "@/lib/auth/use-stored-auth";

export function useConversationIdFromPath(): string {
  const pathname = usePathname();
  return useMemo(() => {
    const match = pathname.match(/^\/c\/([^/]+)/);
    return match?.[1] ?? "";
  }, [pathname]);
}

export function useConversationThreads() {
  const router = useRouter();
  const pathname = usePathname();
  const userId = useStoredUserId();
  const token = useStoredToken();
  const currentId = useConversationIdFromPath();
  const [threads, setThreads] = useState<ConversationSummary[]>([]);

  const refreshThreads = useCallback(async () => {
    const data = await listChatUiConversations(userId, token);
    setThreads(data);
  }, [userId, token]);

  useEffect(() => {
    void refreshThreads();
  }, [refreshThreads]);

  const handleSelectConversation = useCallback(
    (newId: string) => {
      router.push(`/c/${newId}`);
    },
    [router],
  );

  const handleDeleteConversation = useCallback(
    async (idToDelete: string) => {
      try {
        await deleteConversation(idToDelete, userId, token);
        await refreshThreads();
        if (currentId === idToDelete) {
          router.push(`/c/${crypto.randomUUID()}`);
        }
      } catch (err) {
        console.error("Error deleting conversation:", err);
      }
    },
    [currentId, userId, token, refreshThreads, router],
  );

  const handleRenameConversation = useCallback(
    async (idToRename: string, newTitle: string) => {
      try {
        await updateConversationTitle(idToRename, newTitle, userId, token);
        await refreshThreads();
      } catch (err) {
        console.error("Error renaming conversation:", err);
      }
    },
    [userId, token, refreshThreads],
  );

  const handleToggleFavorite = useCallback(
    async (idToToggle: string, isFav: boolean) => {
      try {
        await updateConversationMetadata(idToToggle, { favorite: !isFav }, userId, token);
        await refreshThreads();
      } catch (err) {
        console.error("Error toggling favorite:", err);
      }
    },
    [userId, token, refreshThreads],
  );

  const chatHomeHref = useMemo(() => {
    if (currentId) return `/c/${currentId}`;
    if (threads[0]?.id) return `/c/${threads[0].id}`;
    return "/";
  }, [currentId, threads]);

  const activeSection = useMemo(() => {
    if (pathname.startsWith("/integrations")) return "integrations" as const;
    if (pathname.startsWith("/schedules")) return "schedules" as const;
    if (pathname.startsWith("/settings")) return "settings" as const;
    return "chat" as const;
  }, [pathname]);

  return useMemo(
    () => ({
      userId,
      token,
      threads,
      currentId,
      activeSection,
      chatHomeHref,
      refreshThreads,
      handleSelectConversation,
      handleDeleteConversation,
      handleRenameConversation,
      handleToggleFavorite,
    }),
    [
      userId,
      token,
      threads,
      currentId,
      activeSection,
      chatHomeHref,
      refreshThreads,
      handleSelectConversation,
      handleDeleteConversation,
      handleRenameConversation,
      handleToggleFavorite,
    ],
  );
}

export type ShellSection = ReturnType<typeof useConversationThreads>["activeSection"];
