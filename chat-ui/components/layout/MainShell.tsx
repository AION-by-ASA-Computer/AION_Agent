"use client";

import { useEffect, type ReactNode } from "react";

import { AppShell } from "@/components/layout/AppShell";
import { ThreadSidebar } from "@/components/layout/ThreadSidebar";
import { ShellProvider, useShellActions, useShellChrome, useSidebarOpen } from "@/lib/shell/shell-context";
import { useIsLgUp } from "@/lib/hooks/use-breakpoint";

function MainShellInner({ children }: { children: ReactNode }) {
  const actions = useShellActions();
  const chrome = useShellChrome();
  const sidebarOpen = useSidebarOpen();
  const isLgUp = useIsLgUp();

  useEffect(() => {
    try {
      const v = localStorage.getItem("aion-chat-sidebar-open");
      if (v === "1") actions.setSidebarOpen(true);
      else if (v === "0") actions.setSidebarOpen(false);
      else if (typeof window !== "undefined" && window.matchMedia("(min-width: 1024px)").matches) {
        actions.setSidebarOpen(true);
      }
    } catch {
      /* ignore */
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- bootstrap once
  }, []);

  const sidebarCollapsed = !sidebarOpen && isLgUp;

  return (
    <AppShell
      sidebar={
        <ThreadSidebar
          currentId={actions.currentId}
          userId={actions.userId}
          items={actions.threads}
          onRefresh={actions.refreshThreads}
          onSelectConversation={(id) => {
            actions.handleSelectConversation(id);
            if (!isLgUp) actions.closeSidebar();
          }}
          onDeleteConversation={actions.handleDeleteConversation}
          onRenameConversation={actions.handleRenameConversation}
          onToggleFavorite={actions.handleToggleFavorite}
          activeSection={actions.activeSection}
          chatHomeHref={actions.chatHomeHref}
          isCollapsed={sidebarCollapsed}
          onToggleCollapse={actions.toggleSidebar}
        />
      }
      header={chrome.header}
      dock={chrome.dock}
      isDockOpen={chrome.dockOpen}
      isSidebarOpen={sidebarOpen}
      onCloseSidebar={actions.closeSidebar}
      onCloseDock={() => {
        actions.setDockOpen(false);
        actions.invokeDockClose();
      }}
    >
      <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">{children}</div>
    </AppShell>
  );
}

export function MainShell({ children }: { children: ReactNode }) {
  return (
    <ShellProvider>
      <MainShellInner>{children}</MainShellInner>
    </ShellProvider>
  );
}
