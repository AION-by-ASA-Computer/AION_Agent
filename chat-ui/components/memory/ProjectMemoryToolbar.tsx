"use client";

import { useCallback, useEffect, useState } from "react";
import { Database, ExternalLink, Plus, Settings2 } from "lucide-react";
import Link from "next/link";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";
import { fetchSqlProjects, type SqlProject } from "@/lib/api/query-memory";
import { ProjectCreateModal } from "@/components/memory/ProjectCreateModal";
import { ProjectSettingsModal } from "@/components/memory/ProjectSettingsModal";

const STORAGE_KEY = "aion_sql_query_project";

type Props = {
  userId: string;
  token?: string | null;
  profileSlug?: string;
  value: string;
  onChange: (slug: string) => void;
  /** @deprecated use variant */
  compact?: boolean;
  variant?: "compact" | "panel";
  className?: string;
};

export function ProjectMemoryToolbar({
  userId,
  token,
  profileSlug,
  value,
  onChange,
  compact = false,
  variant: variantProp,
  className,
}: Props) {
  const variant = variantProp ?? (compact ? "compact" : "panel");
  const t = useT();
  const [projects, setProjects] = useState<SqlProject[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);

  const load = useCallback(async () => {
    setLoadError(null);
    try {
      const list = await fetchSqlProjects(userId, token, profileSlug);
      setProjects(list);
      if (list.length && !value) {
        onChange(list[0].slug);
      }
    } catch (e) {
      setLoadError(String(e));
      setProjects([]);
    }
  }, [userId, token, profileSlug, value, onChange]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (value) localStorage.setItem(STORAGE_KEY, value);
  }, [value]);

  const current = projects.find((p) => p.slug === value);

  return (
    <>
      <div
        className={cn(
          "flex items-center justify-between gap-2 rounded-2xl border border-black/[0.06] dark:border-white/[0.08] bg-card/60 dark:bg-card/40 p-1.5 px-2.5 backdrop-blur-xl shadow-2xs transition-all",
          className
        )}
      >
        {/* Project Selector Label & Dropdown */}
        <div className="flex min-w-0 flex-1 items-center gap-2">
          <Database size={13} className="shrink-0 text-sky-500 dark:text-sky-400" aria-hidden />
          <span className="shrink-0 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
            {t("memory_project.label")}:
          </span>
          <div className="relative min-w-0 flex-1">
            <select
              className="focus-ring w-full cursor-pointer appearance-none rounded-lg bg-transparent py-0.5 pr-4 text-xs font-semibold text-foreground outline-none transition-colors hover:text-primary"
              value={value}
              onChange={(e) => onChange(e.target.value)}
              aria-label={t("memory_project.label")}
            >
              {projects.length === 0 && (
                <option value={value || "default"}>{value || "default"}</option>
              )}
              {value && !projects.some((p) => p.slug === value) && (
                <option value={value}>
                  {value} ({t("memory_project.not_in_list")})
                </option>
              )}
              {projects.map((p) => (
                <option key={p.id} value={p.slug}>
                  {p.display_name}
                </option>
              ))}
            </select>
          </div>
        </div>

        {/* Action Buttons */}
        <div className="flex items-center gap-1 shrink-0">
          <button
            type="button"
            title={t("memory_project.new_project")}
            className="focus-ring inline-flex items-center gap-1 rounded-xl border border-black/[0.06] dark:border-white/[0.08] bg-card/80 hover:bg-card p-1.5 text-xs font-medium text-foreground transition-all hover:scale-105 active:scale-95"
            onClick={() => setCreateOpen(true)}
          >
            <Plus size={13} className="text-primary" />
            <span className="hidden sm:inline text-[11px] font-semibold">{t("memory_project.new_short")}</span>
          </button>

          <button
            type="button"
            title={t("memory_project.settings")}
            disabled={!value}
            className="focus-ring rounded-xl border border-black/[0.06] dark:border-white/[0.08] bg-card/80 hover:bg-card p-1.5 text-muted-foreground hover:text-foreground transition-all disabled:opacity-40"
            onClick={() => setSettingsOpen(true)}
          >
            <Settings2 size={13} />
          </button>

          <Link
            href={value ? `/projects?project=${encodeURIComponent(value)}` : "/projects"}
            className="focus-ring rounded-xl border border-black/[0.06] dark:border-white/[0.08] bg-card/80 hover:bg-card p-1.5 text-muted-foreground hover:text-foreground transition-all"
            title={t("memory_project.open_full_page")}
          >
            <ExternalLink size={13} />
          </Link>
        </div>
      </div>

      {loadError && (
        <p className="mt-1 text-[11px] text-destructive truncate px-1" title={loadError}>
          {loadError}
        </p>
      )}

      <ProjectCreateModal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        userId={userId}
        token={token}
        profileSlug={profileSlug}
        onCreated={(slug) => {
          void load();
          onChange(slug);
        }}
      />
      <ProjectSettingsModal
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        userId={userId}
        token={token}
        profileSlug={profileSlug}
        projectSlug={value}
        onUpdated={() => void load()}
      />
    </>
  );
}

export function readStoredSqlProject(): string {
  if (typeof window === "undefined") return "default";
  return localStorage.getItem(STORAGE_KEY) || "default";
}
