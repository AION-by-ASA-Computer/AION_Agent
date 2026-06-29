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

  const projectSelect = (
    <select
      className={cn(
        "w-full bg-transparent text-foreground outline-none",
        variant === "panel" ? "text-sm font-medium" : "text-xs"
      )}
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
  );

  const actionButtons = (
    <>
      <button
        type="button"
        title={t("memory_project.new_project")}
        className={cn(
          "inline-flex items-center gap-1 rounded-lg border border-border bg-background/80 transition-colors hover:bg-muted/60",
          variant === "panel" ? "px-2.5 py-2 text-xs font-medium" : "p-1.5"
        )}
        onClick={() => setCreateOpen(true)}
      >
        <Plus size={14} />
        {variant === "panel" ? <span className="hidden sm:inline">{t("memory_project.new_short")}</span> : null}
      </button>
      <button
        type="button"
        title={t("memory_project.settings")}
        disabled={!value}
        className={cn(
          "inline-flex items-center gap-1 rounded-lg border border-border bg-background/80 transition-colors hover:bg-muted/60 disabled:opacity-40",
          variant === "panel" ? "px-2.5 py-2 text-xs font-medium" : "p-1.5"
        )}
        onClick={() => setSettingsOpen(true)}
      >
        <Settings2 size={14} />
        {variant === "panel" ? <span className="hidden sm:inline">{t("memory_project.settings_short")}</span> : null}
      </button>
      {variant === "panel" ? (
        <Link
          href={value ? `/projects?project=${encodeURIComponent(value)}` : "/projects"}
          className="inline-flex items-center gap-1 rounded-lg border border-border bg-background/80 px-2.5 py-2 text-xs font-medium text-muted-foreground transition-colors hover:bg-muted/60 hover:text-foreground"
          title={t("memory_project.open_full_page")}
        >
          <ExternalLink size={14} />
        </Link>
      ) : null}
    </>
  );

  return (
    <>
      <div className={cn("flex flex-col gap-2", className)}>
        {variant === "panel" ? (
          <div className="rounded-xl border border-border/70 bg-card/60 p-3 shadow-sm">
            <label className="flex flex-col gap-1.5">
              <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                {t("memory_project.label")}
              </span>
              <span className="focus-within:ring-ring/50 flex items-center gap-2 rounded-lg border border-border bg-muted/30 px-3 py-2 focus-within:ring-2">
                <Database size={16} className="shrink-0 text-primary" aria-hidden />
                {projectSelect}
              </span>
            </label>
            {current?.description ? (
              <p className="mt-2 line-clamp-2 text-xs leading-relaxed text-muted-foreground">
                {current.description}
              </p>
            ) : null}
            <div className="mt-2 flex flex-wrap items-center gap-2">
              {current?.role ? (
                <span className="rounded-md bg-muted px-2 py-0.5 text-[10px] text-muted-foreground">
                  {t("memory_project.your_role")}:{" "}
                  <span className="font-mono text-foreground">{current.role}</span>
                </span>
              ) : null}
              <div className="ml-auto flex flex-wrap gap-1.5">{actionButtons}</div>
            </div>
          </div>
        ) : (
          <div className="flex flex-wrap items-end gap-2">
            <label className="flex min-w-0 flex-1 flex-col gap-0.5">
              <span className="text-[10px] text-muted-foreground">{t("memory_project.label")}</span>
              <span className="focus-within:ring-ring/50 flex h-7 min-w-0 items-center gap-1.5 rounded-full border border-border bg-muted/40 px-2 focus-within:ring-1">
                <Database size={12} className="shrink-0 text-primary" aria-hidden />
                <span className="min-w-0 flex-1">{projectSelect}</span>
              </span>
            </label>
            {actionButtons}
          </div>
        )}
        {loadError ? (
          <p className="text-[10px] text-destructive truncate" title={loadError}>
            {loadError}
          </p>
        ) : null}
      </div>

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
