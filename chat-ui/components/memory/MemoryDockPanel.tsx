"use client";

import { useEffect, useMemo, useState } from "react";
import { Bug, Layers, Map, SearchCode, User } from "lucide-react";
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

  const segmentBtn = (id: MemorySubTab, label: string, Icon: typeof SearchCode) => (
    <button
      key={id}
      type="button"
      onClick={() => setSubTab(id)}
      className={cn(
        "focus-ring flex flex-1 items-center justify-center gap-1.5 rounded-md px-2 py-2 text-xs font-medium transition-all",
        subTab === id
          ? "bg-background text-foreground shadow-sm"
          : "text-muted-foreground hover:text-foreground"
      )}
    >
      <Icon size={14} className="shrink-0" aria-hidden />
      {label}
    </button>
  );

  const activeHint = useMemo(() => {
    if (subTab === "query") return t("memory_dock.hint_query");
    if (subTab === "user") return t("memory_dock.hint_user");
    if (subTab === "debug") return t("memory_dock.hint_debug");
    return t("memory_dock.hint_notes");
  }, [subTab, t]);

  const sectionTitle = useMemo(() => {
    if (subTab === "query") return t("memory_dock.tab_query");
    if (subTab === "user") return t("memory_dock.tab_user");
    if (subTab === "debug") return t("memory_dock.tab_debug");
    return t("memory_dock.tab_notes");
  }, [subTab, t]);

  const showProjectToolbar = subTab === "query" || subTab === "notes" || subTab === "debug";

  return (
    <div className="flex h-full min-h-0 flex-col bg-background">
      <header className="shrink-0 border-b border-border/80 bg-gradient-to-b from-primary/[0.06] to-transparent px-4 py-3">
        <div className="mb-3 flex items-start gap-3">
          <div
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-primary/20 bg-primary/10 text-primary"
            aria-hidden
          >
            <Layers size={18} />
          </div>
          <div className="min-w-0 flex-1">
            <h2 className="text-sm font-semibold tracking-tight text-foreground">
              {t("memory_dock.title")}
            </h2>
            <p className="mt-0.5 text-[0.786em] leading-relaxed text-muted-foreground">
              {t("memory_dock.subtitle")}
            </p>
          </div>
        </div>

        {showProjectToolbar ? (
          <ProjectMemoryToolbar
            variant="panel"
            userId={userId}
            token={token}
            profileSlug={profileSlug}
            value={projectSlug}
            onChange={onProjectChange}
          />
        ) : (
          <p className="mt-1 text-xs text-muted-foreground">{t("memory_dock.user_scope_hint")}</p>
        )}

        {showSegments ? (
          <div
            className="mt-3 flex rounded-lg border border-border/60 bg-muted/40 p-1"
            role="tablist"
            aria-label={t("memory_dock.title")}
          >
            {showSqlQueryMemory
              ? segmentBtn("query", t("memory_dock.tab_query"), SearchCode)
              : null}
            {showNavigationMemory
              ? segmentBtn("notes", t("memory_dock.tab_notes"), Map)
              : null}
            {showNavigationMemory
              ? segmentBtn("user", t("memory_dock.tab_user"), User)
              : null}
            {showNavigationMemory
              ? segmentBtn("debug", t("memory_dock.tab_debug"), Bug)
              : null}
          </div>
        ) : (
          <p className="mt-3 text-xs font-medium text-foreground">{sectionTitle}</p>
        )}

        <p className="mt-2 text-[0.786em] leading-snug text-muted-foreground">{activeHint}</p>
      </header>

      <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
        {subTab === "query" && showSqlQueryMemory ? (
          <QueryMemoryPanel
            embedded
            userId={userId}
            token={token}
            projectSlug={projectSlug}
            profileSlug={profileSlug}
            onProjectChange={onProjectChange}
          />
        ) : null}
        {subTab === "notes" && showNavigationMemory ? (
          <ProjectMemoryNotesPanel
            embedded
            userId={userId}
            sessionId={sessionId}
            token={token}
            projectSlug={projectSlug}
            memoryScope="project"
          />
        ) : null}
        {subTab === "user" && showNavigationMemory ? (
          <UserMemoryNotesPanel
            embedded
            userId={userId}
            sessionId={sessionId}
            token={token}
          />
        ) : null}
        {subTab === "debug" && showNavigationMemory ? (
          <ProjectMemoryDebugPanel
            embedded
            userId={userId}
            token={token}
            projectSlug={projectSlug}
          />
        ) : null}
        {!showSqlQueryMemory && !showNavigationMemory ? (
          <p className="p-4 text-xs text-muted-foreground">{t("memory_dock.no_capabilities")}</p>
        ) : null}
      </div>
    </div>
  );
}
