"use client";

import { useEffect, useState } from "react";
import {
  ArrowLeft,
  ChevronRight,
  Database,
  Layers,
  Map,
  Plus,
  SearchCode,
  Settings2,
  Sparkles,
  User,
} from "lucide-react";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";
import { ProjectMemoryNotesPanel } from "@/components/project-memory/ProjectMemoryNotesPanel";
import { UserMemoryNotesPanel } from "@/components/user-memory/UserMemoryNotesPanel";
import { QueryMemoryPanel } from "@/components/query-memory/QueryMemoryPanel";
import { ProjectMemoryToolbar } from "@/components/memory/ProjectMemoryToolbar";
import { ProjectCreateModal } from "@/components/memory/ProjectCreateModal";
import { ProjectSettingsModal } from "@/components/memory/ProjectSettingsModal";

export type MemoryView = "overview" | "query" | "notes" | "user";

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
  const [view, setView] = useState<MemoryView>("overview");
  const [createOpen, setCreateOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);

  useEffect(() => {
    if (!showSqlQueryMemory && !showNavigationMemory) {
      setView("overview");
    }
  }, [showSqlQueryMemory, showNavigationMemory]);

  return (
    <div className="flex h-full min-h-0 flex-col bg-background/50 text-sm">
      {/* 1. Subpage Navigation Header (Visible ONLY inside subpages, NOT duplicated in Overview) */}
      {view !== "overview" && (
        <header className="relative z-30 shrink-0 space-y-2.5 border-b border-black/[0.06] dark:border-white/[0.08] bg-gradient-to-b from-rose-500/[0.04] via-card/40 to-transparent p-3.5 backdrop-blur-xl animate-in fade-in-0 duration-150">
          <div className="flex items-center justify-between gap-2">
            <button
              type="button"
              onClick={() => setView("overview")}
              className="group flex items-center gap-1.5 rounded-xl px-2.5 py-1 text-xs font-semibold text-muted-foreground transition-all hover:bg-card hover:text-foreground active:scale-95 cursor-pointer"
            >
              <ArrowLeft size={14} className="transition-transform group-hover:-translate-x-0.5 text-rose-500" />
              <span>Panoramica</span>
            </button>

          </div>

          {/* Quick Pill Switcher */}
          <div
            className="flex rounded-2xl border border-black/[0.08] dark:border-white/[0.08] bg-muted/40 p-1 backdrop-blur-md"
            role="tablist"
            aria-label="Categorie Memoria"
          >
            {showSqlQueryMemory && (
              <button
                type="button"
                onClick={() => setView("query")}
                className={cn(
                  "focus-ring flex flex-1 items-center justify-center gap-1.5 rounded-xl px-2.5 py-1.5 text-xs font-semibold transition-all duration-200 cursor-pointer",
                  view === "query"
                    ? "bg-card text-foreground shadow-xs ring-1 ring-black/[0.08] dark:ring-white/[0.08] font-bold"
                    : "text-muted-foreground hover:bg-card/40 hover:text-foreground"
                )}
              >
                <SearchCode size={13} className={cn(view === "query" ? "text-foreground" : "opacity-70")} />
                <span>Query SQL</span>
              </button>
            )}

            {showNavigationMemory && (
              <button
                type="button"
                onClick={() => setView("notes")}
                className={cn(
                  "focus-ring flex flex-1 items-center justify-center gap-1.5 rounded-xl px-2.5 py-1.5 text-xs font-semibold transition-all duration-200 cursor-pointer",
                  view === "notes"
                    ? "bg-card text-foreground shadow-xs ring-1 ring-black/[0.08] dark:ring-white/[0.08] font-bold"
                    : "text-muted-foreground hover:bg-card/40 hover:text-foreground"
                )}
              >
                <Map size={13} className={cn(view === "notes" ? "text-foreground" : "opacity-70")} />
                <span>Progetto</span>
              </button>
            )}

            {showNavigationMemory && (
              <button
                type="button"
                onClick={() => setView("user")}
                className={cn(
                  "focus-ring flex flex-1 items-center justify-center gap-1.5 rounded-xl px-2.5 py-1.5 text-xs font-semibold transition-all duration-200 cursor-pointer",
                  view === "user"
                    ? "bg-card text-foreground shadow-xs ring-1 ring-black/[0.08] dark:ring-white/[0.08] font-bold"
                    : "text-muted-foreground hover:bg-card/40 hover:text-foreground"
                )}
              >
                <User size={13} className={cn(view === "user" ? "text-foreground" : "opacity-70")} />
                <span>Tu</span>
              </button>
            )}
          </div>

          {/* Central & Prominent Project Selector in Subpages */}
          {(view === "query" || view === "notes") && (
            <div className="pt-1">
              <ProjectMemoryToolbar
                variant="hero"
                userId={userId}
                token={token}
                profileSlug={profileSlug}
                value={projectSlug}
                onChange={onProjectChange}
              />
            </div>
          )}
        </header>
      )}

      {/* 2. Main Content Body */}
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
        {/* OVERVIEW VIEW (Centered layout exactly like Plan and Research) */}
        {view === "overview" && (
          <div className="flex-1 overflow-y-auto p-4 flex flex-col custom-scrollbar animate-in fade-in-0 duration-200">
            <div className="w-full my-auto py-2 space-y-5">
              {/* Centered Hero Section (Like Plan & Deep Research) */}
              <div className="flex flex-col items-center text-center">
                {/* Large Centered Red Icon Container */}
                <div className="relative mb-3 flex size-14 items-center justify-center rounded-2xl bg-gradient-to-br from-rose-500 to-red-600 text-white shadow-lg shadow-rose-500/25 ring-4 ring-rose-500/10">
                  <Database size={28} />
                </div>

                {/* Title & Mnemos Badge */}
                <div className="flex items-center gap-2">
                  <h3 className="text-base font-bold text-foreground">Modalità Memoria</h3>
                  <span className="rounded-full border border-rose-500/30 bg-rose-500/15 px-2.5 py-0.5 text-[10.5px] font-bold uppercase tracking-wider text-rose-600 dark:text-rose-400">
                    Mnemos
                  </span>
                </div>

                {/* Description */}
                <p className="mt-2 text-sm leading-relaxed text-muted-foreground max-w-sm">
                  L&apos;agente memorizza query SQL verificate, note di business e preferenze personali per risposte contestualizzate e precise.
                </p>
              </div>

              {/* Prominent Large Project Selector */}
              {(showSqlQueryMemory || showNavigationMemory) && (
                <div className="space-y-1.5 w-full relative z-20">
                  <span className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground/80 px-1">
                    Progetto Selezionato
                  </span>
                  <ProjectMemoryToolbar
                    variant="hero"
                    userId={userId}
                    token={token}
                    profileSlug={profileSlug}
                    value={projectSlug}
                    onChange={onProjectChange}
                  />
                </div>
              )}

            {/* 3 Memory Navigation Cards */}
            <div className="space-y-2 w-full">
              <span className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground/80 px-1">
                Aree di Memoria
              </span>

              {/* Card 1: Query SQL */}
              {showSqlQueryMemory && (
                <button
                  type="button"
                  onClick={() => setView("query")}
                  className="group flex w-full items-center justify-between rounded-2xl border border-black/[0.06] dark:border-white/[0.08] bg-card/70 dark:bg-card/40 p-3.5 text-left transition-all duration-200 hover:-translate-y-0.5 hover:border-sky-500/40 hover:bg-card/90 hover:shadow-md cursor-pointer"
                >
                  <div className="flex items-center gap-3">
                    <div className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-sky-500/20 to-blue-600/20 text-sky-600 dark:text-sky-400 group-hover:bg-sky-500 group-hover:text-white transition-colors shadow-xs border border-sky-500/30">
                      <SearchCode size={18} />
                    </div>
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-bold text-foreground group-hover:text-sky-500 transition-colors">
                          Query SQL
                        </span>
                        <span className="rounded-full bg-sky-500/15 text-sky-600 dark:text-sky-400 px-2 py-0.2 text-[9px] font-bold uppercase">
                          Database
                        </span>
                      </div>
                      <p className="text-[11px] text-muted-foreground mt-0.5">
                        Query SQL verificate e indicizzate per il database del progetto
                      </p>
                    </div>
                  </div>
                  <ChevronRight size={15} className="shrink-0 text-muted-foreground group-hover:text-sky-500 group-hover:translate-x-0.5 transition-all" />
                </button>
              )}

              {/* Card 2: Note di Progetto */}
              {showNavigationMemory && (
                <button
                  type="button"
                  onClick={() => setView("notes")}
                  className="group flex w-full items-center justify-between rounded-2xl border border-black/[0.06] dark:border-white/[0.08] bg-card/70 dark:bg-card/40 p-3.5 text-left transition-all duration-200 hover:-translate-y-0.5 hover:border-violet-500/40 hover:bg-card/90 hover:shadow-md cursor-pointer"
                >
                  <div className="flex items-center gap-3">
                    <div className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-violet-500/20 to-purple-600/20 text-violet-600 dark:text-violet-400 group-hover:bg-violet-500 group-hover:text-white transition-colors shadow-xs border border-violet-500/30">
                      <Map size={18} />
                    </div>
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-bold text-foreground group-hover:text-violet-500 transition-colors">
                          Memoria Progetto
                        </span>
                        <span className="rounded-full bg-violet-500/15 text-violet-600 dark:text-violet-400 px-2 py-0.2 text-[9px] font-bold uppercase">
                          Contesto
                        </span>
                      </div>
                      <p className="text-[11px] text-muted-foreground mt-0.5">
                        Fatti, regole operative, pitfall e decisioni condivise
                      </p>
                    </div>
                  </div>
                  <ChevronRight size={15} className="shrink-0 text-muted-foreground group-hover:text-violet-500 group-hover:translate-x-0.5 transition-all" />
                </button>
              )}

              {/* Card 3: Memoria Personale */}
              {showNavigationMemory && (
                <button
                  type="button"
                  onClick={() => setView("user")}
                  className="group flex w-full items-center justify-between rounded-2xl border border-black/[0.06] dark:border-white/[0.08] bg-card/70 dark:bg-card/40 p-3.5 text-left transition-all duration-200 hover:-translate-y-0.5 hover:border-emerald-500/40 hover:bg-card/90 hover:shadow-md cursor-pointer"
                >
                  <div className="flex items-center gap-3">
                    <div className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-emerald-500/20 to-teal-600/20 text-emerald-600 dark:text-emerald-400 group-hover:bg-emerald-500 group-hover:text-white transition-colors shadow-xs border border-emerald-500/30">
                      <User size={18} />
                    </div>
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-bold text-foreground group-hover:text-emerald-500 transition-colors">
                          Memoria Personale (Tu)
                        </span>
                        <span className="rounded-full bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 px-2 py-0.2 text-[9px] font-bold uppercase">
                          Profilo
                        </span>
                      </div>
                      <p className="text-[11px] text-muted-foreground mt-0.5">
                        Preferenze utente, stile di interazione e istruzioni personali
                      </p>
                    </div>
                  </div>
                  <ChevronRight size={15} className="shrink-0 text-muted-foreground group-hover:text-emerald-500 group-hover:translate-x-0.5 transition-all" />
                </button>
              )}

              {!showSqlQueryMemory && !showNavigationMemory && (
                <p className="p-4 text-xs text-muted-foreground text-center">
                  {t("memory_dock.no_capabilities") || "Nessuna capacità di memoria abilitata per questo profilo."}
                </p>
              )}
            </div>
          </div>
        </div>
      )}

        {/* DETAIL VIEW: QUERY SQL */}
        {view === "query" && showSqlQueryMemory && (
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
        )}

        {/* DETAIL VIEW: PROJECT NOTES */}
        {view === "notes" && showNavigationMemory && (
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
        )}

        {/* DETAIL VIEW: USER NOTES */}
        {view === "user" && showNavigationMemory && (
          <div className="h-full min-h-0 animate-in fade-in-0 duration-200">
            <UserMemoryNotesPanel
              embedded
              userId={userId}
              sessionId={sessionId}
              token={token}
            />
          </div>
        )}
      </div>

      {/* 3. Bottom Action Footer: Detached, Glass & Vibrant Red Button */}
      <footer className="shrink-0 p-3 pb-3.5 border-t border-black/[0.06] dark:border-white/[0.08] bg-card/60 dark:bg-card/40 backdrop-blur-2xl">
        <div className="flex items-center gap-2.5">
          {/* Button: Nuovo Progetto (Red Glassmorphic Button) */}
          <button
            type="button"
            onClick={() => setCreateOpen(true)}
            className="focus-ring flex flex-1 items-center justify-center gap-2 rounded-2xl bg-gradient-to-r from-rose-500 to-red-600 hover:from-rose-600 hover:to-red-700 py-2.5 px-4 text-xs font-bold text-white shadow-lg shadow-rose-500/25 border border-rose-400/30 backdrop-blur-xl transition-all duration-200 hover:scale-[1.01] active:scale-[0.98] cursor-pointer"
          >
            <Plus size={15} className="shrink-0" />
            <span>{t("memory_project.new_project") || "Nuovo progetto"}</span>
          </button>

          {/* Button: Impostazioni Progetto (Sleek Glass Button) */}
          <button
            type="button"
            onClick={() => setSettingsOpen(true)}
            disabled={!projectSlug}
            className="focus-ring flex items-center justify-center gap-1.5 rounded-2xl border border-black/[0.08] dark:border-white/[0.08] bg-card/80 hover:bg-card py-2.5 px-3.5 text-xs font-semibold text-muted-foreground hover:text-foreground transition-all hover:border-primary/40 hover:shadow-xs active:scale-[0.98] disabled:opacity-40 cursor-pointer shadow-2xs backdrop-blur-xl"
            title="Impostazioni e gestione completa del progetto"
          >
            <Settings2 size={15} className="shrink-0 text-muted-foreground" />
            <span className="hidden sm:inline">Impostazioni</span>
          </button>
        </div>
      </footer>

      {/* Modals for Create and Settings */}
      <ProjectCreateModal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        userId={userId}
        token={token}
        profileSlug={profileSlug}
        onCreated={(slug) => {
          onProjectChange(slug);
        }}
      />
      <ProjectSettingsModal
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        userId={userId}
        token={token}
        profileSlug={profileSlug}
        projectSlug={projectSlug}
      />
    </div>
  );
}
