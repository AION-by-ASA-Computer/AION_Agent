"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Loader2, Pencil, RefreshCw, Trash2, X } from "lucide-react";
import {
  deleteNavigationDrawer,
  fetchNavigationDrawerDetail,
  fetchNavigationDrawers,
  fetchNavigationStatus,
  pruneLegacyNavigationWings,
  searchNavigationMemory,
  upsertNavigationDrawer,
  type NavigationDrawer,
} from "@/lib/api/navigation-memory";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";
import { fetchSqlProjects } from "@/lib/api/query-memory";

const ROOMS = [
  "entry_points",
  "join_paths",
  "pitfalls",
  "heuristics",
  "limitations",
  "discoveries",
] as const;

const ROOM_LABELS: Record<string, string> = {
  entry_points: "Entry",
  join_paths: "JOIN",
  pitfalls: "Pitfall",
  heuristics: "Heuristic",
  limitations: "Limits",
  discoveries: "Discovery",
};

type Props = {
  userId: string;
  sessionId: string;
  token?: string | null;
  projectSlug: string;
  profileSlug?: string;
  onProjectChange: (slug: string) => void;
  embedded?: boolean;
};

function drawerId(row: NavigationDrawer): string {
  return String(row.id ?? row.drawer_id ?? "");
}

function drawerFullText(row: NavigationDrawer): string {
  return row.content ?? row.text ?? row.preview ?? row.content_preview ?? "";
}

function drawerPreview(row: NavigationDrawer): string {
  const text = drawerFullText(row);
  return text.length > 400 ? `${text.slice(0, 400)}…` : text;
}

export function NavigationMemoryPanel({
  userId,
  sessionId,
  token,
  projectSlug,
  profileSlug: _profileSlug,
  onProjectChange,
  embedded = false,
}: Props) {
  const t = useT();
  const [rows, setRows] = useState<NavigationDrawer[]>([]);
  const [wing, setWing] = useState("");
  const [selectedWing, setSelectedWing] = useState("");
  const [drawerCount, setDrawerCount] = useState(0);
  const [allWings, setAllWings] = useState<Record<string, number>>({});
  const [roomFilter, setRoomFilter] = useState<string>("");
  const [searchQ, setSearchQ] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [prunePreview, setPrunePreview] = useState<string[] | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editRoom, setEditRoom] = useState("");
  const [editContent, setEditContent] = useState("");
  const [saving, setSaving] = useState(false);
  const [deletingItem, setDeletingItem] = useState<NavigationDrawer | null>(null);
  const [sqlProjects, setSqlProjects] = useState<any[]>([]);

  useEffect(() => {
    fetchSqlProjects(userId, token, _profileSlug)
      .then((list) => setSqlProjects(list || []))
      .catch((e) => console.error("Error loading SQL projects in NavigationMemoryPanel", e));
  }, [userId, token, _profileSlug]);

  useEffect(() => {
    if (!deletingItem) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setDeletingItem(null);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [deletingItem]);

  // Sync selected wing with active project's wing when projectSlug changes
  useEffect(() => {
    setSelectedWing("");
  }, [projectSlug]);

  const load = useCallback(async () => {
    if (!projectSlug || !sessionId) return;
    setLoading(true);
    setError(null);
    try {
      const st = await fetchNavigationStatus(userId, sessionId, projectSlug, token);
      const currentActiveWing = st.wing;
      setWing(currentActiveWing);
      setDrawerCount(st.drawer_count);
      setAllWings(st.wings ?? {});

      const wingToQuery = selectedWing || currentActiveWing;
      if (!selectedWing) {
        setSelectedWing(currentActiveWing);
      }

      let loaded: NavigationDrawer[] = [];
      if (searchQ.trim()) {
        const hit = await searchNavigationMemory(
          userId,
          sessionId,
          projectSlug,
          searchQ.trim(),
          token,
          { room: roomFilter || undefined, limit: 50, wing: wingToQuery }
        );
        loaded = hit.results ?? [];
      } else {
        const data = await fetchNavigationDrawers(
          userId,
          sessionId,
          projectSlug,
          token,
          { room: roomFilter || undefined, limit: 100, wing: wingToQuery }
        );
        loaded = data.drawers ?? [];
      }
      if (!roomFilter && !searchQ.trim() && loaded.length === 0 && (st.sample_drawers?.length ?? 0) > 0 && wingToQuery === currentActiveWing) {
        loaded = st.sample_drawers ?? [];
      }
      if (roomFilter) {
        loaded = loaded.filter((row) => row.room === roomFilter);
      }
      setRows(loaded);
    } catch (e) {
      setError(String(e));
      setRows([]);
      setAllWings({});
    } finally {
      setLoading(false);
    }
  }, [userId, sessionId, token, projectSlug, roomFilter, searchQ, selectedWing]);

  useEffect(() => {
    void load();
  }, [load]);

  const startEdit = async (row: NavigationDrawer) => {
    const id = drawerId(row);
    if (!id) return;
    setEditingId(id);
    setEditRoom(row.room || ROOMS[0]);
    setEditContent(drawerFullText(row));
    try {
      const full = await fetchNavigationDrawerDetail(userId, sessionId, id, token);
      const body = drawerFullText(full);
      if (body) {
        setEditContent(body);
        if (full.room) setEditRoom(full.room);
      }
    } catch {
      /* keep list preview */
    }
  };

  const cancelEdit = () => setEditingId(null);

  const onSaveEdit = async () => {
    if (!editingId || !editContent.trim()) return;
    setSaving(true);
    setError(null);
    try {
      await upsertNavigationDrawer(
        userId,
        sessionId,
        {
          project: projectSlug,
          room: editRoom,
          content: editContent.trim(),
          drawer_id: editingId,
        },
        token
      );
      setEditingId(null);
      void load();
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  };

  const onDelete = (row: NavigationDrawer) => {
    setDeletingItem(row);
  };

  const confirmDelete = async () => {
    if (!deletingItem) return;
    const id = drawerId(deletingItem);
    if (!id) return;
    setSaving(true);
    setError(null);
    try {
      await deleteNavigationDrawer(userId, sessionId, id, token);
      if (editingId === id) cancelEdit();
      setDeletingItem(null);
      void load();
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  };

  const onPruneLegacy = async (execute: boolean) => {
    try {
      const res = await pruneLegacyNavigationWings(userId, sessionId, token, {
        dry_run: !execute,
      });
      setPrunePreview(res.pruned_wings);
      if (execute) void load();
    } catch (e) {
      setError(String(e));
    }
  };

  const otherWingsWithData = Object.entries(allWings)
    .filter(([name, count]) => count > 0 && name !== wing)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 8);

  const wingOptions = useMemo(() => {
    const options = new Set<string>();

    // 1. Project wings from all SQL projects
    if (sqlProjects && sqlProjects.length > 0) {
      sqlProjects.forEach((p) => {
        if (p.slug) {
          options.add(`wing_proj_${p.slug.toLowerCase().trim()}`);
        }
      });
    }

    // 2. Always show the active project wing
    const projWing = `wing_proj_${projectSlug}`;
    options.add(projWing);

    // 3. Always show standard system and user wings
    const uWing = userId ? `wing_user_${userId.toLowerCase().trim()}` : "wing_user_default";
    options.add(uWing);
    options.add("wing_user_default");
    options.add("wing_aion_system");
    options.add("wing_session_context");
    options.add("wing_research");

    // 4. Show the currently resolved active wing
    if (wing) {
      options.add(wing);
    }

    // 5. Add all other wings returned by status API
    Object.keys(allWings).forEach((w) => {
      if (w.trim()) {
        options.add(w.trim());
      }
    });

    return Array.from(options).sort();
  }, [projectSlug, wing, allWings, userId, sqlProjects]);

  const handleWingChange = (newWing: string) => {
    setSelectedWing(newWing);
    if (newWing.startsWith("wing_proj_")) {
      const proj = newWing.replace("wing_proj_", "");
      onProjectChange(proj);
    }
  };

  return (
    <div className={cn("flex flex-col text-sm", embedded ? "h-full min-h-0" : "h-full")}>
      <div
        className={cn(
          "shrink-0 space-y-3",
          embedded ? "border-b border-border/60 bg-muted/20 px-4 py-3" : "border-b border-border p-3"
        )}
      >
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-[11px] text-muted-foreground">
          <div className="flex items-center gap-1.5">
            <span>{t("navigation_memory.wing")}</span>
            <select
              className="rounded border border-border bg-background px-1.5 py-0.5 font-mono text-[10px] text-foreground shadow-sm outline-none focus-visible:ring-1 focus-visible:ring-primary/30"
              value={selectedWing || wing || `wing_proj_${projectSlug}`}
              onChange={(e) => handleWingChange(e.target.value)}
            >
              {wingOptions.map((w) => {
                const count = allWings[w] ?? 0;
                const displayLabel = count > 0 ? `${w} (${count})` : w;
                return (
                  <option key={w} value={w}>
                    {displayLabel}
                  </option>
                );
              })}
            </select>
          </div>
          {drawerCount > 0 && (
            <span className="rounded-full bg-primary/10 px-2 py-0.5 text-primary">
              {drawerCount} {t("navigation_memory.drawers")}
            </span>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <select
            className="rounded-lg border border-border bg-background px-2.5 py-2 text-xs shadow-sm outline-none focus-visible:ring-2 focus-visible:ring-primary/30"
            value={roomFilter}
            onChange={(e) => setRoomFilter(e.target.value)}
          >
            <option value="">{t("navigation_memory.all_rooms")}</option>
            {ROOMS.map((r) => (
              <option key={r} value={r}>
                {ROOM_LABELS[r] ?? r}
              </option>
            ))}
          </select>
          <input
            className="min-w-[120px] flex-1 rounded-lg border border-border bg-background px-2.5 py-2 text-xs shadow-sm outline-none focus-visible:ring-2 focus-visible:ring-primary/30"
            placeholder={t("navigation_memory.search_placeholder")}
            value={searchQ}
            onChange={(e) => setSearchQ(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && void load()}
          />
          <button
            type="button"
            className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-xs font-medium text-primary-foreground shadow-sm"
            onClick={() => void load()}
          >
            <RefreshCw size={13} aria-hidden />
            {t("navigation_memory.refresh")}
          </button>
        </div>

        <details className="group rounded-lg border border-border/60 bg-background/50 text-xs">
          <summary className="cursor-pointer px-3 py-2 font-medium text-muted-foreground hover:text-foreground">
            {t("navigation_memory.advanced")}
          </summary>
          <div className="space-y-2 border-t border-border/50 px-3 py-2">
            <p className="text-[11px] leading-relaxed text-muted-foreground">
              {t("navigation_memory.hint")}
            </p>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                className="rounded-lg border border-border px-2.5 py-1.5 hover:bg-muted/50"
                onClick={() => void onPruneLegacy(false)}
              >
                {t("navigation_memory.preview_legacy")}
              </button>
              <button
                type="button"
                className="rounded-lg border border-destructive/40 px-2.5 py-1.5 text-destructive hover:bg-destructive/10"
                onClick={() => {
                  if (!confirm(t("navigation_memory.prune_confirm"))) return;
                  void onPruneLegacy(true);
                }}
              >
                {t("navigation_memory.prune_legacy")}
              </button>
            </div>
            {prunePreview && prunePreview.length > 0 && (
              <p className="text-[11px] text-amber-600 dark:text-amber-400">
                {t("navigation_memory.legacy_wings")}: {prunePreview.join(", ")}
              </p>
            )}
          </div>
        </details>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain p-3">
        {loading && (
          <div className="flex justify-center py-12 text-muted-foreground">
            <Loader2 className="animate-spin" size={22} />
          </div>
        )}
        {error && (
          <p className="rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-xs text-destructive">
            {error}
          </p>
        )}
        {!loading && !error && rows.length === 0 && (
          <div className="space-y-3">
            <div className="rounded-xl border border-dashed border-border bg-muted/20 px-4 py-8 text-center">
              <p className="text-xs text-muted-foreground">{t("navigation_memory.empty")}</p>
              {selectedWing || wing ? (
                <p className="mt-2 font-mono text-[10px] text-muted-foreground">
                  {t("navigation_memory.active_wing")}: {selectedWing || wing}
                </p>
              ) : null}
            </div>
            {otherWingsWithData.length > 0 ? (
              <div className="rounded-xl border border-amber-500/30 bg-amber-500/5 px-4 py-3">
                <p className="text-xs font-medium text-amber-800 dark:text-amber-200">
                  {t("navigation_memory.other_wings_hint")}
                </p>
                <ul className="mt-2 space-y-1 font-mono text-[10px] text-muted-foreground">
                  {otherWingsWithData.map(([name, count]) => (
                    <li key={name}>
                      {name} — {count} {t("navigation_memory.drawers")}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </div>
        )}
        <div className="space-y-2">
          {rows.map((row) => {
            const id = drawerId(row);
            const isEditing = editingId === id && id !== "";
            const room = row.room || "—";
            return (
              <article
                key={id || `${room}-${drawerPreview(row).slice(0, 16)}`}
                className={cn(
                  "rounded-xl border bg-card/80 shadow-sm",
                  isEditing ? "border-primary/40 ring-1 ring-primary/20" : "border-border/80"
                )}
              >
                <div className="p-3">
                  <div className="mb-2 flex items-center justify-between gap-2">
                    <span className="rounded-md bg-muted px-2 py-0.5 font-mono text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
                      {ROOM_LABELS[room] ?? room}
                    </span>
                    {id && !isEditing && (
                      <div className="flex gap-0.5">
                        <button
                          type="button"
                          className="rounded-md p-1.5 text-muted-foreground hover:bg-muted"
                          title={t("navigation_memory.edit")}
                          onClick={() => void startEdit(row)}
                        >
                          <Pencil size={14} />
                        </button>
                        <button
                          type="button"
                          className="rounded-md p-1.5 text-destructive hover:bg-destructive/10"
                          title={t("btn.delete")}
                          onClick={() => onDelete(row)}
                        >
                          <Trash2 size={14} />
                        </button>
                      </div>
                    )}
                    {isEditing && (
                      <button type="button" onClick={cancelEdit} title={t("btn.cancel")}>
                        <X size={14} />
                      </button>
                    )}
                  </div>
                  {isEditing ? (
                    <div className="space-y-2">
                      <select
                        className="w-full rounded-lg border border-border bg-background px-2 py-1.5 text-xs"
                        value={editRoom}
                        onChange={(e) => setEditRoom(e.target.value)}
                      >
                        {ROOMS.map((r) => (
                          <option key={r} value={r}>
                            {ROOM_LABELS[r] ?? r}
                          </option>
                        ))}
                      </select>
                      <textarea
                        className="w-full rounded-lg border border-border bg-background px-2.5 py-2 text-xs leading-relaxed"
                        rows={10}
                        value={editContent}
                        onChange={(e) => setEditContent(e.target.value)}
                      />
                      <button
                        type="button"
                        disabled={saving}
                        className="rounded-lg bg-primary px-3 py-1.5 text-xs text-primary-foreground"
                        onClick={() => void onSaveEdit()}
                      >
                        {t("btn.save")}
                      </button>
                    </div>
                  ) : drawerFullText(row) ? (
                    <p className="whitespace-pre-wrap text-xs leading-relaxed text-foreground/95">
                      {drawerPreview(row)}
                    </p>
                  ) : (
                    <p className="text-xs italic text-muted-foreground">
                      {t("navigation_memory.no_content")}
                    </p>
                  )}
                </div>
              </article>
            );
          })}
        </div>
      </div>

      {deletingItem && (
        <div
          className="fixed inset-0 z-[220] flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm animate-in fade-in-0 duration-150"
          role="presentation"
          onClick={() => setDeletingItem(null)}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="delete-drawer-title"
            className="w-full max-w-md rounded-2xl border border-border/60 bg-card p-6 shadow-2xl animate-in zoom-in-95 duration-150"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="mb-5 flex items-start justify-between gap-3">
              <div className="flex items-center gap-3">
                <div className="flex size-10 items-center justify-center rounded-xl bg-destructive/10 text-destructive">
                  <Trash2 size={20} aria-hidden />
                </div>
                <div>
                  <h2 id="delete-drawer-title" className="text-base font-semibold text-foreground">
                    {t("navigation_memory.delete_confirm")}
                  </h2>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    This action cannot be undone.
                  </p>
                </div>
              </div>
              <button
                type="button"
                className="rounded-lg p-1 text-muted-foreground hover:bg-muted"
                onClick={() => setDeletingItem(null)}
              >
                <X size={18} />
              </button>
            </div>

            <div className="space-y-3">
              <div className="rounded-lg border border-border/50 bg-muted/30 p-3 text-xs leading-relaxed text-foreground/90 max-h-40 overflow-y-auto">
                {drawerPreview(deletingItem)}
              </div>
              {error && <p className="text-xs text-destructive">{error}</p>}
            </div>

            <div className="mt-6 flex justify-end gap-2">
              <button
                type="button"
                className="rounded-lg border border-border px-4 py-2 text-sm hover:bg-muted/50"
                onClick={() => setDeletingItem(null)}
              >
                {t("btn.cancel")}
              </button>
              <button
                type="button"
                disabled={saving}
                className="inline-flex items-center gap-1.5 rounded-lg bg-destructive px-4 py-2 text-sm font-medium text-destructive-foreground hover:bg-destructive/90 disabled:opacity-50"
                onClick={() => void confirmDelete()}
              >
                {saving && <Loader2 size={14} className="animate-spin" />}
                {t("btn.delete")}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
