"use client";

import { useEffect, useMemo, useState } from "react";
import { Bug, Database, Layers, Map, SearchCode, User } from "lucide-react";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";
import { ProjectMemoryDebugPanel } from "@/components/project-memory/ProjectMemoryDebugPanel";
import { ProjectMemoryNotesPanel } from "@/components/project-memory/ProjectMemoryNotesPanel";
import { UserMemoryNotesPanel } from "@/components/user-memory/UserMemoryNotesPanel";
import { QueryMemoryPanel } from "@/components/query-memory/QueryMemoryPanel";
import { ProjectMemoryToolbar } from "@/components/memory/ProjectMemoryToolbar";

type MemorySubTab = "query" | "notes" | "user" | "debug";

type Props = {
  userId: string;
  sessionId: string;
  token?: string | null;
  profileSlug?: string;
  projectSlug: string;
  onProjectChange: (slug: string) => void;
  showSqlQueryMemory: boolean;
  showNavigationMemory: boolean;
};

export function MemoryDockPanel({
  userId,
  sessionId,
  token,
  profileSlug,
  projectSlug,
  onProjectChange,
  showSqlQueryMemory,
  showNavigationMemory,
}: Props) {
  const t = useT();
  const [subTab, setSubTab] = useState<MemorySubTab>("query");

  const mnemosTabCount = showNavigationMemory ? 3 : 0;
  const tabCount = (showSqlQueryMemory ? 1 : 0) + mnemosTabCount;
  const showSegments = tabCount > 1;

  useEffect(() => {
    if (showSqlQueryMemory && !showNavigationMemory) {
      setSubTab("query");
    } else if (!showSqlQueryMemory && showNavigationMemory) {
      setSubTab("notes");
    }
  }, [showSqlQueryMemory, showNavigationMemory]);

  const segmentBtn = (id: MemorySubTab, label: string, Icon: typeof SearchCode) => {
    const isSelected = subTab === id;
    return (
      <button
        key={id}
        type="button"
        onClick={() => setSubTab(id)}
        className={cn(
          "focus-ring flex flex-1 items-center justify-center gap-1.5 rounded-xl px-2.5 py-1.5 text-xs font-semibold transition-all duration-200",
          isSelected
            ? "bg-card text-foreground shadow-xs ring-1 ring-black/[0.08] dark:ring-white/[0.08] font-bold scale-[1.02]"
            : "text-muted-foreground hover:bg-card/40 hover:text-foreground active:scale-95"
        )}
      >
        <Icon
          size={13}
          className={cn("shrink-0 transition-colors", isSelected ? "text-primary" : "opacity-70")}
          aria-hidden
        />
        <span>{label}</span>
      </button>
    );
  };

  const showProjectToolbar = subTab === "query" || subTab === "notes" || subTab === "debug";

  return (
    <div className="flex h-full min-h-0 flex-col bg-background/50 text-sm">
      {/* Top Header: Title, Segmented Tabs & Dynamic Context */}
      <header className="shrink-0 space-y-3 border-b border-black/[0.06] dark:border-white/[0.08] bg-gradient-to-b from-primary/[0.05] via-card/40 to-transparent p-3.5 backdrop-blur-xl">
        {/* Header Hero Title */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div
              className="flex h-7 w-7 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-primary to-primary/80 text-primary-foreground shadow-sm shadow-primary/20"
              aria-hidden
            >
              <Layers size={14} />
            </div>
            <div>
              <h2 className="text-xs font-bold uppercase tracking-wider text-foreground">
                {t("memory_dock.title")}
              </h2>
            </div>
          </div>
          <span className="rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-primary">
            {subTab === "user" ? "Personale" : "Progetto"}
          </span>
        </div>

        {/* 1. Main Navigation Segmented Control */}
        {showSegments && (
          <div
            className="flex rounded-2xl border border-black/[0.08] dark:border-white/[0.08] bg-muted/40 p-1 backdrop-blur-md"
            role="tablist"
            aria-label={t("memory_dock.title")}
          >
            {showSqlQueryMemory
              ? segmentBtn("query", t("memory_dock.tab_query") || "Query SQL", SearchCode)
              : null}
            {showNavigationMemory
              ? segmentBtn("notes", t("memory_dock.tab_notes") || "Progetto", Map)
              : null}
            {showNavigationMemory
              ? segmentBtn("user", t("memory_dock.tab_user") || "Tu", User)
              : null}
            {showNavigationMemory
              ? segmentBtn("debug", t("memory_dock.tab_debug") || "Debug", Bug)
              : null}
          </div>
        )}

        {/* 2. Dynamic Project Context (Visible ONLY on Query, Project notes or Debug; Hidden on User) */}
        <div
          className={cn(
            "transition-all duration-300 ease-in-out overflow-hidden",
            showProjectToolbar
              ? "max-h-20 opacity-100 translate-y-0"
              : "max-h-0 opacity-0 -translate-y-2 pointer-events-none"
          )}
        >
          <ProjectMemoryToolbar
            variant="compact"
            userId={userId}
            token={token}
            profileSlug={profileSlug}
            value={projectSlug}
            onChange={onProjectChange}
          />
        </div>
      </header>

      {/* Main Tab Views with smooth cross-fade animation */}
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
        {subTab === "query" && showSqlQueryMemory ? (
          <div className="h-full min-h-0 animate-in fade-in-0 duration-200">
            <QueryMemoryPanel
              embedded
              userId={userId}
              token={token}
              projectSlug={projectSlug}
              profileSlug={profileSlug}
              onProjectChange={onProjectChange}
            />
          </div>
        ) : null}

        {subTab === "notes" && showNavigationMemory ? (
          <div className="h-full min-h-0 animate-in fade-in-0 duration-200">
            <ProjectMemoryNotesPanel
              embedded
              userId={userId}
              sessionId={sessionId}
              token={token}
              projectSlug={projectSlug}
              memoryScope="project"
            />
          </div>
        ) : null}

        {subTab === "user" && showNavigationMemory ? (
          <div className="h-full min-h-0 animate-in fade-in-0 duration-200">
            <UserMemoryNotesPanel
              embedded
              userId={userId}
              sessionId={sessionId}
              token={token}
            />
          </div>
        ) : null}

        {subTab === "debug" && showNavigationMemory ? (
          <div className="h-full min-h-0 animate-in fade-in-0 duration-200">
            <ProjectMemoryDebugPanel
              embedded
              userId={userId}
              token={token}
              projectSlug={projectSlug}
            />
          </div>
        ) : null}

        {!showSqlQueryMemory && !showNavigationMemory ? (
          <p className="p-4 text-xs text-muted-foreground">{t("memory_dock.no_capabilities")}</p>
        ) : null}
      </div>
    </div>
  );
}
