"use client";

import type { ReactNode } from "react";

import { cn } from "@/lib/cn";
import { useShellActions, useSidebarOpen } from "@/lib/shell/shell-context";
import { PanelLeft } from "lucide-react";

type Props = {
  title: string;
  subtitle?: string;
  icon?: ReactNode;
  action?: ReactNode;
  className?: string;
};

/** Compact header for non-chat sections inside the unified shell. */
export function ShellSectionHeader({ title, subtitle, icon, action, className }: Props) {
  const { toggleSidebar } = useShellActions();
  const sidebarOpen = useSidebarOpen();

  return (
    <header
      className={cn(
        "flex h-14 shrink-0 items-center gap-3 border-b border-border/40 bg-background/80 px-3 backdrop-blur-sm sm:px-4",
        className,
      )}
    >
      <button
        type="button"
        onClick={toggleSidebar}
        className="focus-ring inline-flex h-9 w-9 items-center justify-center rounded-lg text-muted-foreground hover:bg-muted hover:text-foreground lg:hidden"
        aria-label={sidebarOpen ? "Chiudi menu" : "Apri menu"}
      >
        <PanelLeft className="h-4 w-4" aria-hidden />
      </button>
      {icon ? (
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-primary/20 bg-primary/10 text-primary">
          {icon}
        </div>
      ) : null}
      <div className="min-w-0 flex-1">
        <h1 className="truncate text-sm font-semibold tracking-tight sm:text-base">{title}</h1>
        {subtitle ? (
          <p className="truncate text-xs text-muted-foreground">{subtitle}</p>
        ) : null}
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </header>
  );
}
