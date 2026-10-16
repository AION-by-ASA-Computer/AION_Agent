"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Check,
  CheckCircle2,
  Copy,
  Database,
  Filter,
  Loader2,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  Sparkles,
  Trash2,
  X,
  Zap,
} from "lucide-react";
import {
  deleteSqlQuery,
  fetchSqlQueries,
  patchSqlQuery,
  type SqlQueryRow,
} from "@/lib/api/query-memory";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";

type Props = {
  userId: string;
  token?: string | null;
  projectSlug: string;
  profileSlug?: string;
  onProjectChange: (slug: string) => void;
  /** Render inside MemoryDockPanel (no project toolbar). */
  embedded?: boolean;
};

type FilterTab = "all" | "verified" | "draft";

function highlightSql(sql: string) {
  const keywords = /\b(SELECT|FROM|WHERE|INSERT|INTO|UPDATE|SET|DELETE|JOIN|INNER|LEFT|RIGHT|FULL|OUTER|ON|GROUP BY|ORDER BY|HAVING|LIMIT|OFFSET|AS|AND|OR|NOT|IN|IS|NULL|LIKE|BETWEEN|CASE|WHEN|THEN|ELSE|END|COUNT|SUM|AVG|MIN|MAX|DISTINCT|UNION|ALL|CREATE|TABLE|DROP|ALTER|TOP|DESC|ASC)\b/gi;
  const parts = sql.split(keywords);

  return parts.map((part, i) => {
    if (part.toUpperCase().match(keywords)) {
      return (
        <span key={i} className="font-bold text-sky-600 dark:text-sky-400">
          {part.toUpperCase()}
        </span>
      );
    }
    return (
      <span key={i} className="text-slate-800 dark:text-slate-200">
        {part}
      </span>
    );
  });
}

export function QueryMemoryPanel({
  userId,
  token,
  projectSlug,
  profileSlug: _profileSlug,
  onProjectChange: _onProjectChange,
  embedded = false,
}: Props) {
  const t = useT();
  const [rows, setRows] = useState<SqlQueryRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [filter, setFilter] = useState("");
  const [activeTab, setActiveTab] = useState<FilterTab>("all");
  const [error, setError] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editRequest, setEditRequest] = useState("");
  const [editSql, setEditSql] = useState("");
  const [editVerified, setEditVerified] = useState(false);
  const [saving, setSaving] = useState(false);
  const [deletingItem, setDeletingItem] = useState<SqlQueryRow | null>(null);
  const [copiedId, setCopiedId] = useState<number | null>(null);

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

  const load = useCallback(async () => {
    if (!projectSlug) return;
    setLoading(true);
    setError(null);
    try {
      const data = await fetchSqlQueries(userId, projectSlug, token, {
        q: filter || undefined,
        verified_only: activeTab === "verified",
        limit: 100,
      });
      setRows(data);
    } catch (e) {
      setError(String(e));
      setRows([]);
    } finally {
      setLoading(false);
    }
  }, [userId, token, projectSlug, filter, activeTab]);

  useEffect(() => {
    void load();
  }, [load]);

  const startEdit = (row: SqlQueryRow) => {
    setEditingId(row.id);
    setEditRequest(row.user_request);
    setEditSql(row.sql_text);
    setEditVerified(row.is_verified);
  };

  const cancelEdit = () => setEditingId(null);

  const onSaveEdit = async () => {
    if (editingId == null) return;
    setSaving(true);
    setError(null);
    try {
      await patchSqlQuery(
        userId,
        editingId,
        {
          user_request: editRequest.trim(),
          sql_text: editSql.trim(),
          is_verified: editVerified,
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

  const onDelete = (row: SqlQueryRow) => {
    setDeletingItem(row);
  };

  const confirmDelete = async () => {
    if (!deletingItem) return;
    const id = deletingItem.id;
    setSaving(true);
    setError(null);
    try {
      await deleteSqlQuery(userId, id, token);
      if (editingId === id) cancelEdit();
      setDeletingItem(null);
      void load();
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  };

  const handleCopy = async (id: number, text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedId(id);
      window.setTimeout(() => setCopiedId(null), 2000);
    } catch {
      /* ignore */
    }
  };

  const filteredRows = useMemo(() => {
    if (activeTab === "all") return rows;
    if (activeTab === "verified") return rows.filter((r) => r.is_verified);
    return rows.filter((r) => !r.is_verified);
  }, [rows, activeTab]);

  const verifiedCount = useMemo(() => rows.filter((r) => r.is_verified).length, [rows]);
  const draftCount = useMemo(() => rows.filter((r) => !r.is_verified).length, [rows]);

  return (
    <div className={cn("flex flex-col text-sm h-full min-h-0 p-3.5 gap-3", embedded ? "" : "p-4")}>
      {/* 1. Modern Unified Search & Filter Pill Bar */}
      <div className="space-y-2">
        <div className="flex items-center gap-1.5">
          <div className="relative min-w-0 flex-1">
            <Search
              size={13}
              className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground"
            />
            <input
              className="focus-ring w-full rounded-xl border border-black/[0.08] dark:border-white/[0.08] bg-card/80 dark:bg-card/40 py-2 pl-8 pr-7 text-xs text-foreground placeholder:text-muted-foreground transition-all focus:border-primary/40 focus:ring-2 focus:ring-primary/20"
              placeholder={t("query_memory.filter_placeholder") || "Cerca per richiesta o query SQL..."}
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && void load()}
            />
            {filter && (
              <button
                type="button"
                onClick={() => setFilter("")}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground text-xs p-0.5 rounded-full cursor-pointer"
              >
                ✕
              </button>
            )}
          </div>

          <button
            type="button"
            className="focus-ring shrink-0 rounded-xl border border-black/[0.08] dark:border-white/[0.08] bg-card/80 dark:bg-card/40 p-2 text-muted-foreground hover:bg-card hover:text-foreground transition-all cursor-pointer active:scale-95"
            onClick={() => void load()}
            title={t("query_memory.refresh") || "Ricarica"}
          >
            <RefreshCw size={14} className={cn(loading && "animate-spin text-primary")} />
          </button>
        </div>

        {/* Filter Pills */}
        <div className="flex items-center gap-1.5 overflow-x-auto custom-scrollbar pb-0.5">
          <button
            type="button"
            onClick={() => setActiveTab("all")}
            className={cn(
              "flex items-center gap-1.5 rounded-xl px-2.5 py-1 text-xs font-semibold transition-all cursor-pointer border",
              activeTab === "all"
                ? "bg-foreground text-background border-transparent shadow-xs"
                : "border-black/[0.06] dark:border-white/[0.08] bg-card/60 text-muted-foreground hover:bg-card hover:text-foreground"
            )}
          >
            <span>Tutte</span>
            <span
              className={cn(
                "rounded-full px-1.5 py-0.2 text-[10px] font-mono",
                activeTab === "all" ? "bg-background/20 text-background" : "bg-muted/80 text-muted-foreground"
              )}
            >
              {rows.length}
            </span>
          </button>

          <button
            type="button"
            onClick={() => setActiveTab("verified")}
            className={cn(
              "flex items-center gap-1.5 rounded-xl px-2.5 py-1 text-xs font-semibold transition-all cursor-pointer border",
              activeTab === "verified"
                ? "bg-foreground text-background border-transparent shadow-xs"
                : "border-black/[0.06] dark:border-white/[0.08] bg-card/60 text-muted-foreground hover:bg-card hover:text-foreground"
            )}
          >
            <CheckCircle2 size={12} className={activeTab === "verified" ? "text-background" : "text-muted-foreground"} />
            <span>Verificate</span>
            <span
              className={cn(
                "rounded-full px-1.5 py-0.2 text-[10px] font-mono",
                activeTab === "verified" ? "bg-background/20 text-background" : "bg-muted/80 text-muted-foreground"
              )}
            >
              {verifiedCount}
            </span>
          </button>

          <button
            type="button"
            onClick={() => setActiveTab("draft")}
            className={cn(
              "flex items-center gap-1.5 rounded-xl px-2.5 py-1 text-xs font-semibold transition-all cursor-pointer border",
              activeTab === "draft"
                ? "bg-foreground text-background border-transparent shadow-xs"
                : "border-black/[0.06] dark:border-white/[0.08] bg-card/60 text-muted-foreground hover:bg-card hover:text-foreground"
            )}
          >
            <span>Bozze</span>
            <span
              className={cn(
                "rounded-full px-1.5 py-0.2 text-[10px] font-mono",
                activeTab === "draft" ? "bg-background/20 text-background" : "bg-muted/80 text-muted-foreground"
              )}
            >
              {draftCount}
            </span>
          </button>
        </div>
      </div>

      {/* 2. SQL Queries List with Ultra-Modern Glassmorphic Cards */}
      <div className="min-h-0 flex-1 overflow-y-auto custom-scrollbar pr-0.5">
        {loading && rows.length === 0 && (
          <div className="flex flex-col items-center justify-center py-16 text-muted-foreground gap-2">
            <Loader2 className="animate-spin text-primary" size={24} />
            <p className="text-xs">Caricamento query salvate...</p>
          </div>
        )}

        {error && (
          <p className="rounded-2xl border border-destructive/30 bg-destructive/10 p-3.5 text-xs text-destructive">
            {error}
          </p>
        )}

        {!loading && !error && filteredRows.length === 0 && (
          <div className="rounded-2xl border border-dashed border-border/80 bg-muted/20 px-4 py-12 text-center">
            <Database size={24} className="mx-auto mb-2 text-muted-foreground/60" />
            <p className="text-xs font-semibold text-foreground">
              {rows.length === 0 ? "Nessuna query SQL in memoria" : "Nessuna query corrispondente ai filtri"}
            </p>
            <p className="text-[11px] text-muted-foreground mt-1">
              {rows.length === 0
                ? "Le query eseguite e verificate dall'agente per questo progetto verranno memorizzate qui."
                : "Prova a modificare i termini di ricerca o la categoria selezionata."}
            </p>
          </div>
        )}

        <div className="space-y-3">
          {filteredRows.map((row) => {
            const isEditing = editingId === row.id;
            return (
              <article
                key={row.id}
                className={cn(
                  "group rounded-2xl border p-3.5 shadow-2xs backdrop-blur-xl transition-all duration-200 animate-in fade-in-0 slide-in-from-bottom-1",
                  isEditing
                    ? "border-primary/50 ring-2 ring-primary/20 bg-card"
                    : "border-black/[0.08] dark:border-white/[0.08] bg-card/80 dark:bg-card/40 hover:bg-card hover:shadow-md hover:border-black/[0.12] dark:hover:border-white/[0.15]"
                )}
              >
                <div>
                  {isEditing ? (
                    <div className="space-y-3">
                      <div className="space-y-1">
                        <label className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
                          Richiesta Utente / Scopo
                        </label>
                        <textarea
                          className="w-full rounded-xl border border-border bg-background px-3 py-2 text-xs text-foreground focus:border-primary/50 focus:outline-none"
                          rows={2}
                          value={editRequest}
                          onChange={(e) => setEditRequest(e.target.value)}
                          placeholder={t("query_memory.request_label")}
                        />
                      </div>

                      <div className="space-y-1">
                        <label className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
                          Query SQL
                        </label>
                        <textarea
                          className="w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 font-mono text-xs leading-relaxed text-slate-100 placeholder:text-slate-500 focus:border-primary/50 focus:outline-none"
                          rows={6}
                          value={editSql}
                          onChange={(e) => setEditSql(e.target.value)}
                          placeholder="SELECT ..."
                        />
                      </div>

                      <div className="flex items-center justify-between pt-1">
                        <label className="flex items-center gap-2 text-xs text-foreground font-medium cursor-pointer">
                          <input
                            type="checkbox"
                            className="rounded border-border size-3.5 text-primary"
                            checked={editVerified}
                            onChange={(e) => setEditVerified(e.target.checked)}
                          />
                          <span>{t("query_memory.verified") || "Query Verificata"}</span>
                        </label>
                        <div className="flex gap-2">
                          <button
                            type="button"
                            className="rounded-xl border border-border px-3 py-1.5 text-xs text-muted-foreground hover:bg-muted hover:text-foreground transition-colors cursor-pointer"
                            onClick={cancelEdit}
                          >
                            {t("btn.cancel") || "Annulla"}
                          </button>
                          <button
                            type="button"
                            disabled={saving}
                            className="focus-ring rounded-2xl bg-gradient-to-r from-rose-500 to-red-600 hover:from-rose-600 hover:to-red-700 px-4 py-1.5 text-xs font-bold text-white shadow-md shadow-rose-500/25 border border-rose-400/30 backdrop-blur-xl transition-all duration-200 hover:scale-[1.01] active:scale-[0.98] disabled:opacity-50 cursor-pointer"
                            onClick={() => void onSaveEdit()}
                          >
                            {t("btn.save") || "Salva"}
                          </button>
                        </div>
                      </div>
                    </div>
                  ) : (
                    <>
                      {/* Card Header: User Request + Status Badge */}
                      <div className="mb-2.5 flex items-start justify-between gap-2.5">
                        <div className="min-w-0 flex-1">
                          <p className="text-xs font-bold leading-snug text-foreground">
                            {row.user_request}
                          </p>
                        </div>
                        <span
                          className={cn(
                            "shrink-0 rounded-full border px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wide flex items-center gap-1",
                            row.is_verified
                              ? "border-emerald-500/30 bg-emerald-500/15 text-emerald-600 dark:text-emerald-400"
                              : "border-black/[0.08] dark:border-white/[0.08] bg-muted/60 text-muted-foreground"
                          )}
                        >
                          {row.is_verified && <CheckCircle2 size={11} className="shrink-0" />}
                          <span>
                            {row.is_verified
                              ? (t("query_memory.verified") || "Verificata")
                              : (t("query_memory.draft") || "Bozza")}
                          </span>
                        </span>
                      </div>

                      {/* SQL Code Block Container (High-Contrast in Light & Dark Mode) */}
                      <div className="relative rounded-xl border border-black/[0.08] dark:border-white/[0.08] bg-slate-100/90 dark:bg-black/60 p-3 shadow-inner group/code">
                        <div className="mb-1.5 flex items-center justify-between border-b border-black/[0.05] dark:border-white/[0.06] pb-1">
                          <span className="font-mono text-[9px] font-bold uppercase tracking-wider text-muted-foreground/80">
                            SQL Query
                          </span>
                          <button
                            type="button"
                            onClick={() => void handleCopy(row.id, row.sql_text)}
                            className="flex items-center gap-1 rounded-lg px-2 py-0.5 text-[10px] font-medium text-muted-foreground hover:bg-black/5 dark:hover:bg-white/10 hover:text-foreground transition-all cursor-pointer"
                            title={t("query_memory.copy_sql") || "Copia query"}
                          >
                            {copiedId === row.id ? (
                              <>
                                <Check size={11} className="text-emerald-500" />
                                <span className="text-emerald-500 font-bold">Copiato</span>
                              </>
                            ) : (
                              <>
                                <Copy size={11} />
                                <span>Copia</span>
                              </>
                            )}
                          </button>
                        </div>
                        <pre className="max-h-40 overflow-auto font-mono text-[11px] leading-relaxed whitespace-pre-wrap custom-scrollbar">
                          {highlightSql(row.sql_text)}
                        </pre>
                      </div>

                      {/* Card Footer: Action Buttons + Stats */}
                      <div className="mt-2.5 flex items-center justify-between pt-1 text-xs">
                        <div className="flex items-center gap-1">
                          <button
                            type="button"
                            title={t("query_memory.edit") || "Modifica"}
                            className="flex items-center gap-1 rounded-lg px-2 py-1 text-xs text-muted-foreground hover:bg-amber-500/10 hover:text-amber-600 dark:hover:text-amber-400 transition-all cursor-pointer"
                            onClick={() => startEdit(row)}
                          >
                            <Pencil size={12} />
                            <span className="text-[11px] font-medium">Modifica</span>
                          </button>
                          <button
                            type="button"
                            title={t("btn.delete") || "Elimina"}
                            className="flex items-center gap-1 rounded-lg px-2 py-1 text-xs text-muted-foreground hover:bg-destructive/10 hover:text-destructive transition-all cursor-pointer"
                            onClick={() => onDelete(row)}
                          >
                            <Trash2 size={12} />
                            <span className="text-[11px] font-medium">Elimina</span>
                          </button>
                        </div>

                        <div className="flex items-center gap-1 text-[10px] text-muted-foreground font-mono bg-muted/40 px-2 py-0.5 rounded-lg border border-black/[0.04] dark:border-white/[0.04]">
                          <Zap size={11} className="text-sky-500" />
                          <span>
                            {row.success_count} {row.success_count === 1 ? "esecuzione" : "esecuzioni"}
                          </span>
                        </div>
                      </div>
                    </>
                  )}
                </div>
              </article>
            );
          })}
        </div>
      </div>

      {/* Delete Confirmation Dialog */}
      {deletingItem && (
        <div
          className="fixed inset-0 z-[230] flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm animate-in fade-in-0"
          role="presentation"
          onClick={() => setDeletingItem(null)}
        >
          <div
            role="dialog"
            aria-modal="true"
            className="w-full max-w-sm rounded-2xl border border-border bg-card p-5 shadow-2xl animate-in zoom-in-95 duration-150"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="mb-3 flex items-center gap-3">
              <div className="flex size-9 items-center justify-center rounded-xl bg-destructive/15 text-destructive">
                <Trash2 size={18} />
              </div>
              <div>
                <h3 className="text-sm font-bold text-foreground">Elimina Query</h3>
                <p className="text-xs text-muted-foreground">Questa azione è irreversibile.</p>
              </div>
            </div>

            <p className="text-xs text-muted-foreground mb-4">
              Sei sicuro di voler eliminare la query memorizzata per:
              <br />
              <strong className="text-foreground mt-1 block truncate">"{deletingItem.user_request}"</strong>
            </p>

            <div className="flex justify-end gap-2">
              <button
                type="button"
                className="rounded-xl border border-border px-3.5 py-1.5 text-xs font-semibold text-muted-foreground hover:bg-muted cursor-pointer"
                onClick={() => setDeletingItem(null)}
              >
                {t("btn.cancel") || "Annulla"}
              </button>
              <button
                type="button"
                className="rounded-xl bg-destructive px-4 py-1.5 text-xs font-bold text-destructive-foreground hover:bg-destructive/90 cursor-pointer shadow-xs"
                onClick={() => void confirmDelete()}
              >
                {t("btn.delete") || "Elimina"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
