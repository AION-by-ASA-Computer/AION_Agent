"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  Binary,
  Loader2,
  Play,
  RefreshCw,
  Zap,
} from "lucide-react";
import {
  compressProjectMemory,
  fetchProjectDigests,
  fetchProjectMemoryStatus,
  fetchWakePreview,
  type ProjectDigest,
  type ProjectMemoryStatus,
  type WakePreviewRow,
} from "@/lib/api/project-memory";
import { ProjectMemoryDigestTree } from "@/components/project-memory/ProjectMemoryDigestTree";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";

type Props = {
  userId: string;
  projectSlug: string;
  token?: string | null;
  embedded?: boolean;
};

function StatCard({
  label,
  value,
  hint,
  tone = "default",
}: {
  label: string;
  value: string | number;
  hint?: string;
  tone?: "default" | "ok" | "warn";
}) {
  return (
    <div
      className={cn(
        "rounded-lg border px-3 py-2",
        tone === "ok" && "border-emerald-500/30 bg-emerald-500/5",
        tone === "warn" && "border-amber-500/30 bg-amber-500/5",
        tone === "default" && "border-border/70 bg-card/40"
      )}
    >
      <p className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </p>
      <p className="text-lg font-semibold tabular-nums">{value}</p>
      {hint ? <p className="text-[10px] text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

export function ProjectMemoryDebugPanel({
  userId,
  projectSlug,
  token,
  embedded = false,
}: Props) {
  const t = useT();
  const [status, setStatus] = useState<ProjectMemoryStatus | null>(null);
  const [digests, setDigests] = useState<ProjectDigest[]>([]);
  const [wakeRows, setWakeRows] = useState<WakePreviewRow[]>([]);
  const [digestFilter, setDigestFilter] = useState<"" | "ready" | "stale">("");
  const [loading, setLoading] = useState(false);
  const [compressing, setCompressing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [section, setSection] = useState<"overview" | "tree" | "wake" | "digests">(
    "overview"
  );

  const load = useCallback(async () => {
    if (!projectSlug.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const [st, dg, wake] = await Promise.all([
        fetchProjectMemoryStatus(userId, projectSlug, token),
        fetchProjectDigests(
          userId,
          projectSlug,
          token,
          digestFilter === "ready"
            ? { readyOnly: true }
            : digestFilter === "stale"
              ? { readyOnly: false }
              : undefined
        ),
        fetchWakePreview(userId, projectSlug, token),
      ]);
      setStatus(st);
      setDigests(dg);
      setWakeRows(wake.rows ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [userId, projectSlug, token, digestFilter]);

  useEffect(() => {
    void load();
  }, [load]);

  const onCompress = async () => {
    setCompressing(true);
    setError(null);
    try {
      await compressProjectMemory(userId, projectSlug, token);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setCompressing(false);
    }
  };

  const levelSummary = useMemo(() => {
    if (!status?.digest_levels) return "—";
    return Object.entries(status.digest_levels)
      .sort(([a], [b]) => Number(a) - Number(b))
      .map(([lv, n]) => `L${lv}:${n}`)
      .join(" · ");
  }, [status?.digest_levels]);

  const filteredDigests = useMemo(() => {
    if (digestFilter === "ready") return digests.filter((d) => d.ready);
    if (digestFilter === "stale") return digests.filter((d) => !d.ready);
    return digests;
  }, [digests, digestFilter]);

  const tabBtn = (id: typeof section, label: string, Icon: typeof Activity) => (
    <button
      key={id}
      type="button"
      onClick={() => setSection(id)}
      className={cn(
        "focus-ring flex items-center gap-1 rounded-md px-2 py-1.5 text-[11px] font-medium",
        section === id
          ? "bg-background text-foreground shadow-sm"
          : "text-muted-foreground hover:text-foreground"
      )}
    >
      <Icon className="h-3.5 w-3.5" />
      {label}
    </button>
  );

  return (
    <div className={cn("flex h-full min-h-0 flex-col", embedded ? "" : "p-3")}>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="flex flex-1 flex-wrap gap-1 rounded-lg border border-border/60 bg-muted/30 p-1">
          {tabBtn("overview", t("project_memory_debug.tab_overview"), Activity)}
          {tabBtn("tree", t("project_memory_debug.tab_tree"), Binary)}
          {tabBtn("wake", t("project_memory_debug.tab_wake"), Play)}
          {tabBtn("digests", t("project_memory_debug.tab_digests"), Zap)}
        </div>
        <button
          type="button"
          className="focus-ring rounded-md border p-2"
          onClick={() => void load()}
          disabled={loading}
          title={t("project_memory_debug.refresh")}
        >
          <RefreshCw className={cn("h-4 w-4", loading && "animate-spin")} />
        </button>
        <button
          type="button"
          className="focus-ring rounded-md border border-primary/40 bg-primary/10 px-2 py-2 text-xs font-medium text-primary"
          onClick={() => void onCompress()}
          disabled={compressing || loading}
        >
          {compressing ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            t("project_memory_debug.compress")
          )}
        </button>
      </div>

      {status ? (
        <p className="mb-2 font-mono text-[10px] text-muted-foreground">
          scope: {status.scope_type ?? "project"} / {status.scope_key ?? projectSlug}
        </p>
      ) : null}
      {error ? <p className="mb-2 text-xs text-destructive">{error}</p> : null}

      <div className="min-h-0 flex-1 overflow-y-auto">
        {section === "overview" && status ? (
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-2">
              <StatCard
                label={t("project_memory_debug.stat_active")}
                value={status.notes_active}
                hint={`${status.notes_total} ${t("project_memory_debug.total")}`}
                tone="ok"
              />
              <StatCard
                label={t("project_memory_debug.stat_superseded")}
                value={status.notes_superseded ?? 0}
              />
              <StatCard
                label={t("project_memory_debug.stat_seq")}
                value={status.seq_count ?? 0}
                hint={t("project_memory_debug.seq_hint")}
              />
              <StatCard
                label={t("project_memory_debug.stat_digests_ready")}
                value={status.digests_ready}
                hint={`${status.digests_total ?? 0} ${t("project_memory_debug.total")}`}
                tone="ok"
              />
              <StatCard
                label={t("project_memory_debug.stat_digests_stale")}
                value={status.digests_stale ?? 0}
                tone={(status.digests_stale ?? 0) > 0 ? "warn" : "default"}
              />
              <StatCard
                label={t("project_memory_debug.stat_levels")}
                value={levelSummary}
              />
            </div>
            <p className="text-xs leading-relaxed text-muted-foreground">
              {t("project_memory_debug.overview_help")}
            </p>
          </div>
        ) : null}

        {section === "tree" ? (
          <ProjectMemoryDigestTree
            userId={userId}
            projectSlug={projectSlug}
            token={token}
            seqCount={status?.seq_count ?? 0}
          />
        ) : null}

        {section === "wake" ? (
          <div className="space-y-2">
            <p className="text-xs text-muted-foreground">{t("project_memory_debug.wake_help")}</p>
            {wakeRows.length === 0 ? (
              <p className="py-6 text-center text-sm text-muted-foreground">
                {t("project_memory_debug.wake_empty")}
              </p>
            ) : (
              <ul className="space-y-2">
                {wakeRows.map((row, i) => (
                  <li
                    key={`wake-${i}`}
                    className="rounded-lg border border-border/70 bg-card/50 p-2 text-xs"
                  >
                    <div className="mb-1 flex items-center gap-2">
                      <span
                        className={cn(
                          "rounded px-1 py-0.5 text-[9px] font-medium uppercase",
                          row.kind === "digest"
                            ? "bg-amber-500/15 text-amber-700 dark:text-amber-300"
                            : "bg-primary/10 text-primary"
                        )}
                      >
                        {row.kind}
                      </span>
                      {row.kind === "digest" && row.lo != null && row.hi != null ? (
                        <span className="font-mono text-[10px] text-muted-foreground">
                          [{row.lo}, {row.hi})
                        </span>
                      ) : null}
                      {row.kind === "note" && row.seq != null ? (
                        <span className="font-mono text-[10px] text-muted-foreground">
                          #{row.seq}
                        </span>
                      ) : null}
                    </div>
                    <p className="whitespace-pre-wrap break-words font-mono text-[11px] leading-relaxed">
                      {row.line}
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </div>
        ) : null}

        {section === "digests" ? (
          <div className="space-y-2">
            <div className="flex gap-2">
              <select
                className="focus-ring rounded-md border border-border bg-background px-2 py-1.5 text-xs"
                value={digestFilter}
                onChange={(e) =>
                  setDigestFilter(e.target.value as "" | "ready" | "stale")
                }
              >
                <option value="">{t("project_memory_debug.filter_all")}</option>
                <option value="ready">{t("project_memory_debug.filter_ready")}</option>
                <option value="stale">{t("project_memory_debug.filter_stale")}</option>
              </select>
            </div>
            {filteredDigests.length === 0 ? (
              <p className="py-6 text-center text-sm text-muted-foreground">
                {t("project_memory_debug.digests_empty")}
              </p>
            ) : (
              <ul className="space-y-2">
                {filteredDigests.map((d) => (
                  <li
                    key={`${d.lo}-${d.hi}`}
                    className={cn(
                      "rounded-lg border p-2 text-xs",
                      d.ready
                        ? "border-emerald-500/25 bg-emerald-500/5"
                        : "border-destructive/25 bg-destructive/5"
                    )}
                  >
                    <div className="mb-1 flex flex-wrap items-center gap-2">
                      <span className="font-mono text-[10px] font-semibold">
                        [{d.lo}, {d.hi})
                      </span>
                      <span className="text-[10px] text-muted-foreground">
                        {t("project_memory_debug.level")} {d.level}
                      </span>
                      <span
                        className={cn(
                          "rounded px-1.5 py-0.5 text-[9px] font-medium uppercase",
                          d.ready
                            ? "bg-emerald-500/15 text-emerald-700"
                            : "bg-destructive/15 text-destructive"
                        )}
                      >
                        {d.ready
                          ? t("project_memory_debug.digest_ready")
                          : t("project_memory_debug.digest_stale")}
                      </span>
                    </div>
                    <p className="line-clamp-4 whitespace-pre-wrap break-words">
                      {d.summary || t("project_memory_debug.no_summary")}
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </div>
        ) : null}

        {loading && !status ? (
          <div className="flex justify-center py-10 text-muted-foreground">
            <Loader2 className="h-6 w-6 animate-spin" />
          </div>
        ) : null}
      </div>
    </div>
  );
}
