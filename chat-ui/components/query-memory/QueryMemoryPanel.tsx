"use client";

import { useCallback, useEffect, useState } from "react";
import { Check, Copy, Loader2, Pencil, RefreshCw, Search, Trash2, X } from "lucide-react";
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

function highlightSql(sql: string) {
  const keywords = /\b(SELECT|FROM|WHERE|INSERT|INTO|UPDATE|SET|DELETE|JOIN|INNER|LEFT|RIGHT|FULL|OUTER|ON|GROUP BY|ORDER BY|HAVING|LIMIT|OFFSET|AS|AND|OR|NOT|IN|IS|NULL|LIKE|BETWEEN|CASE|WHEN|THEN|ELSE|END|COUNT|SUM|AVG|MIN|MAX|DISTINCT|UNION|ALL|CREATE|TABLE|DROP|ALTER)\b/gi;
  const parts = sql.split(keywords);

  return parts.map((part, i) => {
    if (part.toUpperCase().match(keywords)) {
      return (
        <span key={i} className="font-semibold text-sky-400 dark:text-sky-300">
          {part.toUpperCase()}
        </span>
      );
    }
    return <span key={i}>{part}</span>;
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
  const [verifiedOnly, setVerifiedOnly] = useState(false);
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
        verified_only: verifiedOnly,
        limit: 100,
      });
      setRows(data);
    } catch (e) {
      setError(String(e));
      setRows([]);
    } finally {
      setLoading(false);
    }
  }, [userId, token, projectSlug, filter, verifiedOnly]);

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

  return (
    <div className={cn("flex flex-col text-sm h-full min-h-0 p-3.5 gap-3", embedded ? "" : "p-4")}>
      {/* 1. Unified Search & Filter Control Row */}
      <div className="flex items-center gap-1.5">
        <div className="relative min-w-0 flex-1">
          <Search size={13} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground/60" />
          <input
            className="focus-ring w-full rounded-xl border border-black/[0.08] dark:border-white/[0.08] bg-card/60 dark:bg-card/40 py-2 pl-8 pr-7 text-xs text-foreground placeholder:text-muted-foreground/60 transition-all focus:border-primary/40 focus:ring-2 focus:ring-primary/20"
            placeholder={t("query_memory.filter_placeholder") || "Cerca query SQL..."}
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && void load()}
          />
          {filter && (
            <button
              type="button"
              onClick={() => setFilter("")}
              className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground text-xs p-0.5 rounded-full"
            >
              ✕
            </button>
          )}
        </div>

        <button
          type="button"
          onClick={() => setVerifiedOnly((prev) => !prev)}
          className={cn(
            "rounded-xl border px-2.5 py-2 text-xs font-medium transition-all shrink-0",
            verifiedOnly
              ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 font-semibold shadow-2xs"
              : "border-black/[0.06] dark:border-white/[0.08] bg-card/60 dark:bg-card/40 text-muted-foreground hover:bg-card/90 hover:text-foreground"
          )}
        >
          {t("query_memory.verified_only") || "Verificate"}
        </button>

        <button
          type="button"
          className="focus-ring shrink-0 rounded-xl border border-black/[0.06] dark:border-white/[0.08] bg-card/60 dark:bg-card/40 p-2 text-muted-foreground hover:bg-card/90 hover:text-foreground transition-all"
          onClick={() => void load()}
          title={t("query_memory.refresh")}
        >
          <RefreshCw size={14} className={cn(loading && "animate-spin text-primary")} />
        </button>
      </div>

      {/* 2. SQL Queries List with Floating Glassmorphic Cards */}
      <div className="min-h-0 flex-1 overflow-y-auto custom-scrollbar">
        {loading && rows.length === 0 && (
          <div className="flex justify-center py-12 text-muted-foreground">
            <Loader2 className="animate-spin text-primary" size={22} />
          </div>
        )}

        {error && (
          <p className="rounded-xl border border-destructive/30 bg-destructive/10 p-3 text-xs text-destructive">
            {error}
          </p>
        )}

        {!loading && !error && rows.length === 0 && (
          <div className="rounded-2xl border border-dashed border-border/80 bg-muted/20 px-4 py-10 text-center">
            <p className="text-xs font-medium text-muted-foreground">{t("query_memory.empty")}</p>
          </div>
        )}

        <div className="space-y-2.5">
          {rows.map((row) => {
            const isEditing = editingId === row.id;
            return (
              <article
                key={row.id}
                className={cn(
                  "group rounded-2xl border p-3.5 shadow-2xs backdrop-blur-xl transition-all duration-200 animate-in fade-in-0 slide-in-from-bottom-1",
                  isEditing
                    ? "border-primary/40 ring-1 ring-primary/20 bg-card/90"
                    : "border-black/[0.06] dark:border-white/[0.08] bg-card/60 dark:bg-card/35 hover:bg-card/90 hover:shadow-md hover:-translate-y-0.5"
                )}
              >
                <div>
                  {isEditing ? (
                    <div className="space-y-2.5">
                      <textarea
                        className="w-full rounded-xl border border-black/[0.08] dark:border-white/[0.08] bg-background/80 px-2.5 py-2 text-xs text-foreground"
                        rows={2}
                        value={editRequest}
                        onChange={(e) => setEditRequest(e.target.value)}
                        placeholder={t("query_memory.request_label")}
                      />
                      <textarea
                        className="w-full rounded-xl border border-black/[0.08] dark:border-white/[0.08] bg-black/40 dark:bg-black/60 px-2.5 py-2 font-mono text-xs leading-relaxed text-foreground"
                        rows={6}
                        value={editSql}
                        onChange={(e) => setEditSql(e.target.value)}
                        placeholder="SQL"
                      />
                      <div className="flex items-center justify-between">
                        <label className="flex items-center gap-2 text-xs text-muted-foreground cursor-pointer">
                          <input
                            type="checkbox"
                            className="rounded border-border"
                            checked={editVerified}
                            onChange={(e) => setEditVerified(e.target.checked)}
                          />
                          {t("query_memory.verified")}
                        </label>
                        <div className="flex gap-2">
                          <button
                            type="button"
                            className="rounded-xl border px-3 py-1.5 text-xs text-muted-foreground hover:bg-muted"
                            onClick={cancelEdit}
                          >
                            {t("btn.cancel")}
                          </button>
                          <button
                            type="button"
                            disabled={saving}
                            className="rounded-xl bg-primary px-3.5 py-1.5 text-xs font-semibold text-primary-foreground hover:bg-primary/90"
                            onClick={() => void onSaveEdit()}
                          >
                            {t("btn.save")}
                          </button>
                        </div>
                      </div>
                    </div>
                  ) : (
                    <>
                      {/* Header: User Question + Soft Modern Badge */}
                      <div className="mb-2.5 flex items-start justify-between gap-2">
                        <p className="text-xs font-semibold leading-snug text-foreground">
                          {row.user_request}
                        </p>
                        <span
                          className={cn(
                            "shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide",
                            row.is_verified
                              ? "border-emerald-500/20 bg-emerald-500/10 text-emerald-500 dark:text-emerald-400"
                              : "border-black/[0.06] dark:border-white/[0.06] bg-muted/40 text-muted-foreground"
                          )}
                        >
                          {row.is_verified
                            ? (t("query_memory.verified") || "Verificata")
                            : (t("query_memory.draft") || "Bozza")}
                        </span>
                      </div>

                      {/* SQL Code Well */}
                      <div className="rounded-xl border border-black/10 dark:border-white/5 bg-black/30 dark:bg-black/60 p-2.5 shadow-inner">
                        <pre className="max-h-32 overflow-auto font-mono text-[11px] leading-relaxed text-foreground/90 whitespace-pre-wrap custom-scrollbar">
                          {highlightSql(row.sql_text)}
                        </pre>
                      </div>

                      {/* Discreet Card Footer: Actions & Execution Count */}
                      <div className="mt-2.5 flex items-center justify-between border-t border-black/[0.04] dark:border-white/[0.04] pt-2">
                        <div className="flex items-center gap-1">
                          <button
                            type="button"
                            title={t("query_memory.copy_sql")}
                            className="focus-ring rounded-lg p-1 text-muted-foreground/60 hover:bg-muted/80 hover:text-foreground transition-all"
                            onClick={() => void handleCopy(row.id, row.sql_text)}
                          >
                            {copiedId === row.id ? (
                              <Check size={13} className="text-emerald-500" />
                            ) : (
                              <Copy size={13} />
                            )}
                          </button>
                          <button
                            type="button"
                            title={t("query_memory.edit")}
                            className="focus-ring rounded-lg p-1 text-muted-foreground/60 hover:bg-muted/80 hover:text-foreground transition-all"
                            onClick={() => startEdit(row)}
                          >
                            <Pencil size={13} />
                          </button>
                          <button
                            type="button"
                            title={t("btn.delete")}
                            className="focus-ring rounded-lg p-1 text-muted-foreground/60 hover:bg-destructive/10 hover:text-destructive transition-all"
                            onClick={() => onDelete(row)}
                          >
                            <Trash2 size={13} />
                          </button>
                        </div>
                        <span className="text-[10px] text-muted-foreground/60 font-mono">
                          {row.success_count} {row.success_count === 1 ? "run" : "runs"}
                        </span>
                      </div>
                    </>
                  )}
                </div>
              </article>
            );
          })}
        </div>
      </div>

      {/* Delete Confirmation Modal */}
      {deletingItem && (
        <div
          className="fixed inset-0 z-[220] flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm animate-in fade-in-0 duration-150"
          role="presentation"
          onClick={() => setDeletingItem(null)}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="delete-query-title"
            className="w-full max-w-md rounded-2xl border border-border/60 bg-card p-6 shadow-2xl animate-in zoom-in-95 duration-150"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="mb-5 flex items-start justify-between gap-3">
              <div className="flex items-center gap-3">
                <div className="flex size-10 items-center justify-center rounded-xl bg-destructive/10 text-destructive">
                  <Trash2 size={20} aria-hidden />
                </div>
                <div>
                  <h2 id="delete-query-title" className="text-base font-semibold text-foreground">
                    {t("query_memory.delete_confirm")}
                  </h2>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    Questa azione non può essere annullata.
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
              <p className="text-xs font-medium text-foreground leading-snug">
                {deletingItem.user_request}
              </p>
              <pre className="rounded-lg border border-border/50 bg-muted/30 p-3 text-[0.714em] font-mono leading-relaxed text-foreground/90 max-h-40 overflow-y-auto whitespace-pre-wrap">
                {deletingItem.sql_text}
              </pre>
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
