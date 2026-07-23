"use client";

import { useCallback, useEffect, useState } from "react";
import { Check, Copy, Loader2, Pencil, RefreshCw, Trash2, X } from "lucide-react";
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
    <div className={cn("flex flex-col text-sm", embedded ? "h-full min-h-0" : "h-full")}>
      <div
        className={cn(
          "shrink-0 space-y-3",
          embedded ? "border-b border-border/60 bg-muted/20 px-4 py-3" : "border-b border-border p-3"
        )}
      >
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative min-w-[140px] flex-1">
            <input
              className="w-full rounded-lg border border-border bg-background py-2 pl-3 pr-2 text-xs shadow-sm outline-none focus-visible:ring-2 focus-visible:ring-primary/30"
              placeholder={t("query_memory.filter_placeholder")}
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && void load()}
            />
          </div>
          <label className="flex cursor-pointer items-center gap-2 rounded-lg border border-border bg-background px-2.5 py-2 text-xs text-muted-foreground shadow-sm">
            <input
              type="checkbox"
              className="rounded border-border"
              checked={verifiedOnly}
              onChange={(e) => setVerifiedOnly(e.target.checked)}
            />
            {t("query_memory.verified_only")}
          </label>
          <button
            type="button"
            className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-xs font-medium text-primary-foreground shadow-sm hover:bg-primary/90"
            onClick={() => void load()}
          >
            <RefreshCw size={13} aria-hidden />
            {t("query_memory.refresh")}
          </button>
        </div>
        {!embedded && (
          <p className="text-[0.786em] text-muted-foreground">{t("query_memory.empty_hint")}</p>
        )}
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
          <div className="rounded-xl border border-dashed border-border bg-muted/20 px-4 py-10 text-center">
            <p className="text-xs text-muted-foreground">{t("query_memory.empty")}</p>
          </div>
        )}
        <div className="space-y-2">
          {rows.map((row) => {
            const isEditing = editingId === row.id;
            return (
              <article
                key={row.id}
                className={cn(
                  "rounded-xl border bg-card/80 shadow-sm transition-colors",
                  isEditing ? "border-primary/40 ring-1 ring-primary/20" : "border-border/80"
                )}
              >
                <div className="p-3">
                  {isEditing ? (
                    <div className="space-y-2">
                      <textarea
                        className="w-full rounded-lg border border-border bg-background px-2.5 py-2 text-xs"
                        rows={2}
                        value={editRequest}
                        onChange={(e) => setEditRequest(e.target.value)}
                        placeholder={t("query_memory.request_label")}
                      />
                      <textarea
                        className="w-full rounded-lg border border-border bg-background px-2.5 py-2 font-mono text-[0.786em] leading-relaxed"
                        rows={8}
                        value={editSql}
                        onChange={(e) => setEditSql(e.target.value)}
                        placeholder="SQL"
                      />
                      <label className="flex items-center gap-2 text-xs">
                        <input
                          type="checkbox"
                          checked={editVerified}
                          onChange={(e) => setEditVerified(e.target.checked)}
                        />
                        {t("query_memory.verified")}
                      </label>
                      <div className="flex gap-2">
                        <button
                          type="button"
                          disabled={saving}
                          className="rounded-lg bg-primary px-3 py-1.5 text-xs text-primary-foreground"
                          onClick={() => void onSaveEdit()}
                        >
                          {t("btn.save")}
                        </button>
                        <button
                          type="button"
                          className="rounded-lg border border-border px-3 py-1.5 text-xs"
                          onClick={cancelEdit}
                        >
                          {t("btn.cancel")}
                        </button>
                      </div>
                    </div>
                  ) : (
                    <>
                      <div className="mb-2 flex items-start justify-between gap-2">
                        <p className="text-xs font-medium leading-snug text-foreground">
                          {row.user_request}
                        </p>
                        <span
                          className={cn(
                            "shrink-0 rounded-md px-1.5 py-0.5 text-[0.714em] font-medium",
                            row.is_verified
                              ? "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400"
                              : "bg-muted text-muted-foreground"
                          )}
                        >
                          {row.is_verified
                            ? t("query_memory.verified")
                            : t("query_memory.draft")}
                        </span>
                      </div>
                      <pre className="max-h-28 overflow-auto rounded-lg bg-muted/50 p-2.5 font-mono text-[0.714em] leading-relaxed text-foreground/90 whitespace-pre-wrap">
                        {row.sql_text}
                      </pre>
                      <div className="mt-2 flex items-center gap-1 border-t border-border/50 pt-2">
                        <div className="relative inline-block">
                          <button
                            type="button"
                            title={t("query_memory.copy_sql")}
                            className="rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground"
                            onClick={() => void handleCopy(row.id, row.sql_text)}
                          >
                            {copiedId === row.id ? (
                              <Check size={14} className="text-emerald-500" />
                            ) : (
                              <Copy size={14} />
                            )}
                          </button>
                          {copiedId === row.id && (
                            <span className="absolute bottom-full left-1/2 z-10 -translate-x-1/2 mb-1.5 rounded bg-foreground px-2 py-1 text-[0.714em] font-medium text-background shadow-md animate-in fade-in-0 slide-in-from-bottom-1 duration-150 whitespace-nowrap">
                              {t("header.copied")}
                            </span>
                          )}
                        </div>
                        <button
                          type="button"
                          title={t("query_memory.edit")}
                          className="rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground"
                          onClick={() => startEdit(row)}
                        >
                          <Pencil size={14} />
                        </button>
                        <button
                          type="button"
                          title={t("btn.delete")}
                          className="rounded-md p-1.5 text-destructive hover:bg-destructive/10"
                          onClick={() => onDelete(row)}
                        >
                          <Trash2 size={14} />
                        </button>
                        {row.is_verified && (
                          <Check
                            size={14}
                            className="ml-auto text-emerald-600"
                            aria-hidden
                          />
                        )}
                        <span className="ml-auto text-[0.714em] text-muted-foreground">
                          ×{row.success_count}
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
