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
    return new Date(iso).toLocaleString();
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
  const [statusText, setStatusText] = useState("");
  const [editing, setEditing] = useState<ProjectNote | null>(null);
  const [draft, setDraft] = useState("");
  const [draftCategory, setDraftCategory] = useState("fact");
  const [draftImportance, setDraftImportance] = useState(3);
  const [creating, setCreating] = useState(false);

  const categoryLabel = useCallback(
    (c: string) => t(`project_memory.categories.${c}` as "project_memory.categories.fact"),
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
      setStatusText(
        memoryScope === "user"
          ? t("user_memory.status_line", {
              active: st.notes_active,
              total: st.notes_total,
              digests: st.digests_ready,
              stale: st.digests_stale ?? 0,
              scope: st.scope_key ?? userId,
            })
          : t("project_memory.status_line", {
              active: st.notes_active,
              total: st.notes_total,
              digests: st.digests_ready,
              stale: st.digests_stale ?? 0,
            })
      );
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
    t,
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

  const startEdit = (note: ProjectNote) => {
    setEditing(note);
    setCreating(false);
    setDraft(note.content);
    setDraftCategory(note.category);
    setDraftImportance(note.importance);
  };

  const cancelForm = () => {
    setEditing(null);
    setCreating(false);
    setDraft("");
  };

  const saveForm = async () => {
    const content = draft.trim();
    if (!content) return;
    setLoading(true);
    try {
      if (editing) {
        if (memoryScope === "user") {
          await updateUserNote(userId, token, editing.id, {
            session_id: sessionId,
            content,
            category: draftCategory,
            importance: draftImportance,
          });
        } else {
          await updateProjectNote(userId, token, editing.id, {
            session_id: sessionId,
            project: projectSlug,
            content,
            category: draftCategory,
            importance: draftImportance,
          });
        }
      } else if (memoryScope === "user") {
        await createUserNote(userId, token, {
          session_id: sessionId,
          content,
          category: draftCategory,
          importance: draftImportance,
        });
      } else {
        await createProjectNote(userId, token, {
          session_id: sessionId,
          project: projectSlug,
          content,
          category: draftCategory,
          importance: draftImportance,
        });
      }
      cancelForm();
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  const onDelete = async (note: ProjectNote) => {
    setLoading(true);
    try {
      if (memoryScope === "user") {
        await deleteUserNote(userId, token, note.id, sessionId);
      } else {
        await deleteProjectNote(userId, token, note.id, sessionId);
      }
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className={cn("flex h-full min-h-0 flex-col", embedded ? "" : "p-3")}>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="relative min-w-[140px] flex-1">
          <Search className="pointer-events-none absolute left-2 top-2.5 h-4 w-4 text-muted-foreground" />
          <input
            className="focus-ring w-full rounded-md border border-border bg-background py-2 pl-8 pr-2 text-sm"
            placeholder={t("project_memory.search_placeholder")}
            value={searchQ}
            onChange={(e) => setSearchQ(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && void load()}
          />
        </div>
        <select
          className="focus-ring rounded-md border border-border bg-background px-2 py-2 text-sm"
          value={category}
          onChange={(e) => setCategory(e.target.value)}
        >
          <option value="">{t("project_memory.all_categories")}</option>
          {NOTE_CATEGORIES.map((c) => (
            <option key={c} value={c}>
              {categoryLabel(c)}
            </option>
          ))}
        </select>
        <select
          className="focus-ring rounded-md border border-border bg-background px-2 py-2 text-sm"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value as StatusFilter)}
        >
          <option value="active">{t("project_memory.status_active")}</option>
          <option value="superseded">{t("project_memory.status_superseded")}</option>
          <option value="all">{t("project_memory.status_all")}</option>
        </select>
        {searchQ.trim() ? (
          <select
            className="focus-ring rounded-md border border-border bg-background px-2 py-2 text-xs"
            value={searchMode}
            onChange={(e) => setSearchMode(e.target.value as "current" | "historical")}
          >
            <option value="current">{t("project_memory.search_current")}</option>
            <option value="historical">{t("project_memory.search_historical")}</option>
          </select>
        ) : null}
        <button type="button" className="focus-ring rounded-md border p-2" onClick={() => void load()}>
          <RefreshCw className={cn("h-4 w-4", loading && "animate-spin")} />
        </button>
        <button type="button" className="focus-ring rounded-md border p-2" onClick={startCreate}>
          <Plus className="h-4 w-4" />
        </button>
      </div>

      {statusText ? (
        <p className="mb-2 text-xs text-muted-foreground">{statusText}</p>
      ) : null}
      {error ? <p className="mb-2 text-xs text-destructive">{error}</p> : null}

      {(creating || editing) && (
        <div className="mb-3 rounded-lg border border-border bg-muted/30 p-3">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-sm font-medium">
              {editing ? t("project_memory.edit_note") : t("project_memory.new_note")}
            </span>
            <button type="button" onClick={cancelForm} className="focus-ring rounded p-1">
              <X className="h-4 w-4" />
            </button>
          </div>
          <select
            className="focus-ring mb-2 w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm"
            value={draftCategory}
            onChange={(e) => setDraftCategory(e.target.value)}
          >
            {NOTE_CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {categoryLabel(c)}
              </option>
            ))}
          </select>
          <div className="mb-2">
            <label className="mb-1 block text-xs text-muted-foreground">
              {t("project_memory.importance")} ({draftImportance})
            </label>
            <input
              type="range"
              min={1}
              max={5}
              value={draftImportance}
              onChange={(e) => setDraftImportance(Number(e.target.value))}
              className="w-full"
            />
          </div>
          <textarea
            className="focus-ring mb-2 min-h-[80px] w-full rounded-md border border-border bg-background p-2 text-sm"
            maxLength={500}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder={t("project_memory.note_placeholder")}
          />
          <button
            type="button"
            className="focus-ring rounded-md bg-primary px-3 py-1.5 text-sm text-primary-foreground"
            onClick={() => void saveForm()}
            disabled={loading || !draft.trim()}
          >
            {t("project_memory.save")}
          </button>
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto">
        {loading && notes.length === 0 ? (
          <div className="flex justify-center py-8 text-muted-foreground">
            <Loader2 className="h-6 w-6 animate-spin" />
          </div>
        ) : sorted.length === 0 ? (
          <p className="py-8 text-center text-sm text-muted-foreground">
            {memoryScope === "user"
              ? t("user_memory.empty")
              : t("project_memory.empty")}
          </p>
        ) : (
          <ul className="space-y-2">
            {sorted.map((note) => (
              <li
                key={note.id}
                className={cn(
                  "rounded-lg border p-3 text-sm shadow-sm",
                  note.status === "superseded"
                    ? "border-border/50 bg-muted/20 opacity-80"
                    : "border-border/80 bg-card"
                )}
              >
                <div className="mb-1 flex flex-wrap items-center gap-2">
                  <span className="rounded bg-primary/10 px-1.5 py-0.5 text-[10px] font-medium uppercase text-primary">
                    {categoryLabel(note.category)}
                  </span>
                  <span className="text-[10px] text-muted-foreground">#{note.seq}</span>
                  <span className="text-[10px] text-muted-foreground">
                    {t("project_memory.importance_short")} {note.importance}
                  </span>
                  {note.status !== "active" ? (
                    <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] uppercase text-muted-foreground">
                      {note.status}
                    </span>
                  ) : null}
                  {note.superseded_by ? (
                    <span className="text-[10px] text-muted-foreground">
                      → #{note.superseded_by}
                    </span>
                  ) : null}
                  <div className="ml-auto flex gap-1">
                    {note.status === "active" ? (
                      <>
                        <button
                          type="button"
                          className="focus-ring rounded p-1"
                          onClick={() => startEdit(note)}
                        >
                          <Pencil className="h-3.5 w-3.5" />
                        </button>
                        <button
                          type="button"
                          className="focus-ring rounded p-1 text-destructive"
                          onClick={() => void onDelete(note)}
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </>
                    ) : null}
                  </div>
                </div>
                <p className="whitespace-pre-wrap break-words">{note.content}</p>
                <div className="mt-2 flex flex-wrap gap-2 text-[10px] text-muted-foreground">
                  {note.created_at ? <span>{formatWhen(note.created_at)}</span> : null}
                  {note.source_session_id ? (
                    <span className="font-mono">
                      {t("project_memory.session")}: {note.source_session_id.slice(0, 8)}…
                    </span>
                  ) : null}
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

export function UserMemoryNotesPanel(
  props: Omit<Props, "memoryScope" | "projectSlug">
) {
  return <ProjectMemoryNotesPanel {...props} memoryScope="user" />;
}
