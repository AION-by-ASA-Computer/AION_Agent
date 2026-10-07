"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Loader2, Pencil, Plus, RefreshCw, Search, Trash2, X } from "lucide-react";
import {
  createProjectNote,
  deleteProjectNote,
  fetchProjectMemoryStatus,
  fetchProjectNotes,
  NOTE_CATEGORIES,
  searchProjectNotes,
  updateProjectNote,
  type ProjectNote,
} from "@/lib/api/project-memory";
import {
  createUserNote,
  deleteUserNote,
  fetchUserMemoryStatus,
  fetchUserNotes,
  searchUserNotes,
  updateUserNote,
} from "@/lib/api/user-memory";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";

type Props = {
  userId: string;
  sessionId: string;
  token?: string | null;
  projectSlug?: string;
  memoryScope?: "project" | "user";
  embedded?: boolean;
};

type StatusFilter = "active" | "superseded" | "all";

function formatWhen(iso?: string | null) {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

export function ProjectMemoryNotesPanel({
  userId,
  sessionId,
  token,
  projectSlug = "",
  memoryScope = "project",
  embedded = false,
}: Props) {
  const t = useT();
  const [notes, setNotes] = useState<ProjectNote[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [category, setCategory] = useState<string>("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("active");
  const [searchQ, setSearchQ] = useState("");
  const [searchMode, setSearchMode] = useState<"current" | "historical">("current");
  const [activeCount, setActiveCount] = useState<number | null>(null);
  const [totalCount, setTotalCount] = useState<number | null>(null);
  const [editing, setEditing] = useState<ProjectNote | null>(null);
  const [draft, setDraft] = useState("");
  const [draftCategory, setDraftCategory] = useState("fact");
  const [draftImportance, setDraftImportance] = useState(3);
  const [creating, setCreating] = useState(false);
  const [deletingNote, setDeletingNote] = useState<ProjectNote | null>(null);

  const categoryLabel = useCallback(
    (c: string) => t(`project_memory.categories.${c}` as "project_memory.categories.fact") || c,
    [t]
  );

  const load = useCallback(async () => {
    if (memoryScope === "project" && !projectSlug.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const [st, list] =
        memoryScope === "user"
          ? await Promise.all([
            fetchUserMemoryStatus(userId, token),
            searchQ.trim()
              ? searchUserNotes(userId, searchQ.trim(), token, { mode: searchMode })
              : fetchUserNotes(userId, token, {
                category: category || undefined,
                status: statusFilter,
                limit: 200,
              }),
          ])
          : await Promise.all([
            fetchProjectMemoryStatus(userId, projectSlug, token),
            searchQ.trim()
              ? searchProjectNotes(userId, projectSlug, searchQ.trim(), token, {
                mode: searchMode,
              })
              : fetchProjectNotes(userId, projectSlug, token, {
                category: category || undefined,
                status: statusFilter,
                limit: 200,
              }),
          ]);
      setActiveCount(st.notes_active);
      setTotalCount(st.notes_total);
      setNotes(list);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [
    userId,
    projectSlug,
    token,
    category,
    statusFilter,
    searchQ,
    searchMode,
    memoryScope,
  ]);

  useEffect(() => {
    void load();
  }, [load]);

  const sorted = useMemo(
    () => [...notes].sort((a, b) => b.seq - a.seq),
    [notes]
  );

  const startCreate = () => {
    setCreating(true);
    setEditing(null);
    setDraft("");
    setDraftCategory("fact");
    setDraftImportance(3);
  };

  const startEdit = (n: ProjectNote) => {
    setEditing(n);
    setCreating(false);
    setDraft(n.content);
    setDraftCategory(n.category);
    setDraftImportance(n.importance ?? 3);
  };

  const cancelForm = () => {
    setCreating(false);
    setEditing(null);
    setDraft("");
  };

  const saveForm = async () => {
    const text = draft.trim();
    if (!text) return;
    setLoading(true);
    setError(null);
    try {
      if (editing) {
        if (memoryScope === "user") {
          await updateUserNote(userId, token, editing.id, {
            session_id: sessionId,
            content: text,
            category: draftCategory,
            importance: draftImportance,
          });
        } else {
          await updateProjectNote(userId, token, editing.id, {
            session_id: sessionId,
            project: projectSlug,
            content: text,
            category: draftCategory,
            importance: draftImportance,
          });
        }
      } else {
        if (memoryScope === "user") {
          await createUserNote(userId, token, {
            session_id: sessionId,
            content: text,
            category: draftCategory,
            importance: draftImportance,
          });
        } else {
          await createProjectNote(userId, token, {
            session_id: sessionId,
            project: projectSlug,
            content: text,
            category: draftCategory,
            importance: draftImportance,
          });
        }
      }
      cancelForm();
      void load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  const executeDelete = async (note: ProjectNote, hard: boolean) => {
    setLoading(true);
    setError(null);
    try {
      if (memoryScope === "user") {
        await deleteUserNote(userId, token, note.id, sessionId, hard);
      } else {
        await deleteProjectNote(userId, token, note.id, sessionId, hard);
      }
      setDeletingNote(null);
      void load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className={cn("flex flex-col text-sm h-full min-h-0 p-3.5 gap-2.5", embedded ? "" : "p-4")}>
      {/* 1. Unified Search, Refresh & Primary "+ Nuova Nota" Row */}
      <div className="flex items-center gap-1.5">
        <div className="relative min-w-0 flex-1">
          <Search size={13} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground/60" />
          <input
            className="focus-ring w-full rounded-xl border border-black/[0.08] dark:border-white/[0.08] bg-card/60 dark:bg-card/40 py-2 pl-8 pr-7 text-xs text-foreground placeholder:text-muted-foreground/60 transition-all focus:border-primary/40 focus:ring-2 focus:ring-primary/20"
            placeholder={
              memoryScope === "user"
                ? "Cerca nella memoria personale..."
                : (t("project_memory.search_placeholder") || "Cerca nelle note...")
            }
            value={searchQ}
            onChange={(e) => setSearchQ(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && void load()}
          />
          {searchQ && (
            <button
              type="button"
              onClick={() => setSearchQ("")}
              className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground text-xs p-0.5 rounded-full"
            >
              ✕
            </button>
          )}
        </div>

        <button
          type="button"
          onClick={() => void load()}
          className="focus-ring shrink-0 rounded-xl border border-black/[0.06] dark:border-white/[0.08] bg-card/60 dark:bg-card/40 p-2 text-muted-foreground hover:bg-card/90 hover:text-foreground transition-all"
          title={t("query_memory.refresh")}
        >
          <RefreshCw size={14} className={cn(loading && "animate-spin text-primary")} />
        </button>

        <button
          type="button"
          onClick={startCreate}
          className="focus-ring inline-flex shrink-0 items-center gap-1.5 rounded-2xl bg-gradient-to-r from-rose-500 to-red-600 hover:from-rose-600 hover:to-red-700 py-2 px-3 text-xs font-bold text-white shadow-md shadow-rose-500/25 border border-rose-400/30 backdrop-blur-xl transition-all duration-200 hover:scale-[1.02] active:scale-[0.98] cursor-pointer"
        >
          <Plus size={14} className="shrink-0" />
          <span className="hidden sm:inline">Nuova Nota</span>
        </button>
      </div>
      {/* 2. Scrollable Category Micro-Pills & Discreet Stats */}
      <div className="flex items-center justify-between gap-2 border-b border-black/[0.04] dark:border-white/[0.04] pb-2">
        <div className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto no-scrollbar py-0.5">
          <button
            type="button"
            className={cn(
              "rounded-full px-2.5 py-0.5 text-[11px] font-medium transition-all shrink-0 border cursor-pointer",
              !category
                ? "border-transparent bg-foreground text-background font-semibold shadow-xs"
                : "border-black/[0.06] dark:border-white/[0.08] bg-card/40 text-muted-foreground hover:bg-card/80 hover:text-foreground"
            )}
            onClick={() => setCategory("")}
          >
            Tutte
          </button>
          {NOTE_CATEGORIES.map((c) => {
            const isSelected = category === c;
            return (
              <button
                key={c}
                type="button"
                className={cn(
                  "rounded-full px-2.5 py-0.5 text-[11px] font-medium transition-all shrink-0 border cursor-pointer",
                  isSelected
                    ? "border-transparent bg-foreground text-background font-semibold shadow-xs"
                    : "border-black/[0.06] dark:border-white/[0.08] bg-card/40 text-muted-foreground hover:bg-card/80 hover:text-foreground"
                )}
                onClick={() => setCategory(c)}
              >
                {categoryLabel(c)}
              </button>
            );
          })}
        </div>

        {/* Discreet Stats + Active filter */}
        <div className="flex items-center gap-2 shrink-0">
          <button
            type="button"
            onClick={() => setStatusFilter((prev) => (prev === "active" ? "all" : "active"))}
            className={cn(
              "rounded-full border px-2 py-0.5 text-[10px] font-semibold transition-colors cursor-pointer",
              statusFilter === "active"
                ? "border-transparent bg-foreground text-background shadow-2xs"
                : "border-black/[0.06] dark:border-white/[0.08] bg-card/30 text-muted-foreground hover:text-foreground"
            )}
          >
            {statusFilter === "active" ? "Attive" : "Tutte"}
          </button>

          {activeCount != null && (
            <span className="text-[10px] font-mono text-muted-foreground/60 hidden sm:inline">
              {activeCount}/{totalCount}
            </span>
          )}
        </div>
      </div>

      {error && (
        <p className="rounded-xl border border-destructive/30 bg-destructive/10 p-2.5 text-xs text-destructive">
          {error}
        </p>
      )}

      {/* 3. Note Creation / Editing Card */}
      {(creating || editing) && (
        <div className="rounded-2xl border border-primary/30 bg-card/95 dark:bg-card/85 p-3.5 shadow-xl backdrop-blur-2xl animate-in fade-in-0 zoom-in-95 duration-200">
          <div className="mb-2.5 flex items-center justify-between">
            <span className="text-xs font-bold uppercase tracking-wider text-foreground">
              {editing ? (t("project_memory.edit_note") || "Modifica Nota") : (t("project_memory.new_note") || "Nuova Nota")}
            </span>
            <button
              type="button"
              onClick={cancelForm}
              className="focus-ring rounded-full p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
            >
              <X size={14} />
            </button>
          </div>

          <div className="mb-2 flex flex-wrap gap-1">
            {NOTE_CATEGORIES.map((c) => (
              <button
                key={c}
                type="button"
                className={cn(
                  "rounded-full px-2.5 py-0.5 text-[11px] font-medium transition-all border",
                  draftCategory === c
                    ? "border-primary bg-primary/15 text-primary font-semibold"
                    : "border-border/60 bg-muted/30 text-muted-foreground hover:text-foreground"
                )}
                onClick={() => setDraftCategory(c)}
              >
                {categoryLabel(c)}
              </button>
            ))}
          </div>

          <div className="mb-2.5 flex items-center justify-between rounded-xl border border-black/[0.06] dark:border-white/[0.08] bg-muted/20 px-3 py-1.5 text-xs text-muted-foreground">
            <span>Importanza:</span>
            <div className="flex items-center gap-1">
              {[1, 2, 3, 4, 5].map((lvl) => (
                <button
                  key={lvl}
                  type="button"
                  onClick={() => setDraftImportance(lvl)}
                  className={cn(
                    "h-5 w-5 rounded-md text-xs font-bold transition-all",
                    draftImportance >= lvl
                      ? "bg-amber-500/20 text-amber-500 font-bold"
                      : "bg-muted/40 text-muted-foreground/40"
                  )}
                >
                  ★
                </button>
              ))}
            </div>
          </div>

          <textarea
            className="focus-ring mb-3 min-h-[90px] w-full resize-none rounded-xl border border-black/[0.08] dark:border-white/[0.08] bg-background/80 p-2.5 text-xs text-foreground placeholder:text-muted-foreground/60 transition-all focus:border-primary/40 focus:ring-2 focus:ring-primary/20"
            maxLength={500}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder={t("project_memory.note_placeholder") || "Scrivi una nota o una regola..."}
          />

          <div className="flex items-center justify-end gap-2">
            <button
              type="button"
              onClick={cancelForm}
              className="focus-ring rounded-xl px-3 py-1.5 text-xs font-medium text-muted-foreground hover:bg-muted/60 hover:text-foreground transition-all"
            >
              {t("btn.cancel")}
            </button>
            <button
              type="button"
              className="focus-ring rounded-2xl bg-gradient-to-r from-rose-500 to-red-600 hover:from-rose-600 hover:to-red-700 px-4 py-1.5 text-xs font-bold text-white shadow-md shadow-rose-500/25 border border-rose-400/30 backdrop-blur-xl transition-all duration-200 hover:scale-[1.01] active:scale-[0.98] disabled:opacity-50 cursor-pointer"
              onClick={() => void saveForm()}
              disabled={loading || !draft.trim()}
            >
              {t("project_memory.save") || "Salva"}
            </button>
          </div>
        </div>
      )}

      {/* 4. Notes List with Floating Glassmorphic Cards */}
      <div className="min-h-0 flex-1 overflow-y-auto custom-scrollbar">
        {loading && notes.length === 0 ? (
          <div className="flex justify-center py-12 text-muted-foreground">
            <Loader2 className="h-6 w-6 animate-spin text-primary" />
          </div>
        ) : sorted.length === 0 ? (
          <div className="space-y-3 py-4">
            <div className="rounded-2xl border border-dashed border-border/80 bg-muted/20 p-6 text-center">
              <p className="text-xs font-medium text-muted-foreground">
                {memoryScope === "user"
                  ? (t("user_memory.empty") || "Nessuna nota personale.")
                  : (t("project_memory.empty") || "Nessuna nota nel progetto.")}
              </p>
              <p className="mt-1 text-[11px] text-muted-foreground/70">
                Aggiungi fatti, regole o preferenze che l&apos;agente deve ricordare.
              </p>
            </div>

          </div>
        ) : (
          <ul className="space-y-2.5">
            {sorted.map((note) => {
              const catClass =
                note.category === "decision"
                  ? "bg-indigo-500/10 text-indigo-500 dark:text-indigo-400 border-indigo-500/20"
                  : note.category === "constraint"
                    ? "bg-amber-500/10 text-amber-500 dark:text-amber-400 border-amber-500/20"
                    : note.category === "preference"
                      ? "bg-purple-500/10 text-purple-500 dark:text-purple-400 border-purple-500/20"
                      : "bg-blue-500/10 text-blue-500 dark:text-blue-400 border-blue-500/20";

              return (
                <li
                  key={note.id}
                  className={cn(
                    "group relative flex flex-col rounded-2xl border p-3.5 shadow-2xs backdrop-blur-xl transition-all duration-200 animate-in fade-in-0 slide-in-from-bottom-1",
                    note.status === "superseded"
                      ? "border-black/[0.04] dark:border-white/[0.04] bg-muted/20 opacity-70"
                      : "border-black/[0.06] dark:border-white/[0.08] bg-card/60 dark:bg-card/35 hover:bg-card/90 hover:shadow-md hover:-translate-y-0.5"
                  )}
                >
                  {/* Card Header: Soft Badge, Importance & Actions */}
                  <div className="mb-2 flex items-center justify-between gap-2">
                    <div className="flex items-center gap-1.5">
                      <span className={cn("rounded-full border px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide", catClass)}>
                        {categoryLabel(note.category)}
                      </span>
                      <span className="text-[10px] font-mono text-muted-foreground/60">
                        #{note.seq}
                      </span>
                      {note.importance ? (
                        <span className="text-[10px] text-amber-500 font-semibold tracking-tight">
                          {"★".repeat(note.importance)}
                        </span>
                      ) : null}
                    </div>

                    {/* Actions */}
                    <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                      {note.status === "active" ? (
                        <>
                          <button
                            type="button"
                            className="focus-ring rounded-lg p-1 text-muted-foreground/60 hover:bg-muted/80 hover:text-foreground transition-colors"
                            onClick={() => startEdit(note)}
                            title={t("project_memory.edit_note")}
                          >
                            <Pencil size={13} />
                          </button>
                          <button
                            type="button"
                            className="focus-ring rounded-lg p-1 text-muted-foreground/60 hover:bg-destructive/10 hover:text-destructive transition-colors"
                            onClick={() => setDeletingNote(note)}
                            title={t("project_memory.delete_title_active")}
                          >
                            <Trash2 size={13} />
                          </button>
                        </>
                      ) : (
                        <button
                          type="button"
                          className="focus-ring rounded-lg p-1 text-muted-foreground/60 hover:bg-destructive/10 hover:text-destructive transition-colors"
                          onClick={() => setDeletingNote(note)}
                          title={t("project_memory.delete_title_superseded")}
                        >
                          <Trash2 size={13} />
                        </button>
                      )}
                    </div>
                  </div>

                  {/* Note Content */}
                  <p className="text-xs leading-relaxed text-foreground whitespace-pre-wrap break-words font-normal">
                    {note.content}
                  </p>

                  {/* Card Footer: Timestamp and Session */}
                  <div className="mt-2.5 flex items-center justify-between gap-2 border-t border-black/[0.04] dark:border-white/[0.04] pt-2 text-[10px] text-muted-foreground/60">
                    <span>{note.created_at ? formatWhen(note.created_at) : ""}</span>
                    {note.source_session_id ? (
                      <span className="font-mono truncate max-w-[8rem]">
                        Session · {note.source_session_id.slice(0, 8)}
                      </span>
                    ) : null}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      {/* Delete Confirmation Modal */}
      {deletingNote ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-xs">
          <div className="w-full max-w-md rounded-2xl border border-border bg-card p-5 shadow-2xl animate-in fade-in zoom-in-95 duration-150">
            <div className="mb-3 flex items-start justify-between gap-2">
              <div className="flex items-center gap-2">
                <div className="rounded-full bg-destructive/10 p-2 text-destructive">
                  <Trash2 className="h-5 w-5" />
                </div>
                <h3 className="text-base font-semibold text-foreground">
                  {deletingNote.status === "active"
                    ? t("project_memory.delete_title_active")
                    : t("project_memory.delete_title_superseded")}
                </h3>
              </div>
              <button
                type="button"
                onClick={() => setDeletingNote(null)}
                className="rounded p-1 text-muted-foreground hover:bg-muted"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <p className="mb-3 text-xs text-muted-foreground">
              {deletingNote.status === "active"
                ? t("project_memory.delete_desc_active")
                : t("project_memory.delete_desc_superseded")}
            </p>

            <div className="mb-4 max-h-24 overflow-y-auto rounded-xl border border-border bg-muted/40 p-2.5 text-xs italic text-foreground">
              "{deletingNote.content}"
            </div>

            {deletingNote.status === "active" ? (
              <div className="space-y-2">
                <button
                  type="button"
                  className="flex w-full flex-col items-start rounded-xl border border-border bg-background p-3 text-left transition-colors hover:bg-muted"
                  onClick={() => void executeDelete(deletingNote, false)}
                >
                  <span className="text-sm font-medium text-foreground">
                    {t("project_memory.delete_soft_btn")}
                  </span>
                  <span className="text-[11px] text-muted-foreground">
                    {t("project_memory.delete_soft_desc")}
                  </span>
                </button>

                <button
                  type="button"
                  className="flex w-full flex-col items-start rounded-xl border border-destructive/30 bg-destructive/5 p-3 text-left transition-colors hover:border-destructive hover:bg-destructive/10"
                  onClick={() => void executeDelete(deletingNote, true)}
                >
                  <span className="text-sm font-medium text-destructive">
                    {t("project_memory.delete_hard_btn")}
                  </span>
                  <span className="text-[11px] text-muted-foreground">
                    {t("project_memory.delete_hard_desc")}
                  </span>
                </button>

                <div className="mt-2 flex justify-end">
                  <button
                    type="button"
                    className="rounded-xl border border-border px-4 py-1.5 text-xs text-muted-foreground hover:bg-muted"
                    onClick={() => setDeletingNote(null)}
                  >
                    {t("project_memory.cancel")}
                  </button>
                </div>
              </div>
            ) : (
              <div className="flex justify-end gap-2">
                <button
                  type="button"
                  className="rounded-xl border border-border px-4 py-1.5 text-xs text-muted-foreground hover:bg-muted"
                  onClick={() => setDeletingNote(null)}
                >
                  {t("project_memory.cancel")}
                </button>
                <button
                  type="button"
                  className="rounded-xl bg-destructive px-4 py-1.5 text-xs font-medium text-destructive-foreground hover:bg-destructive/90"
                  onClick={() => void executeDelete(deletingNote, true)}
                >
                  {t("project_memory.delete_confirm")}
                </button>
              </div>
            )}
          </div>
        </div>
      ) : null}
    </div>
  );
}

export function UserMemoryNotesPanel(
  props: Omit<Props, "memoryScope" | "projectSlug">
) {
  return <ProjectMemoryNotesPanel {...props} memoryScope="user" />;
}
