"use client";

import { useCallback, useEffect, useState } from "react";
import { Database } from "lucide-react";
import { cn } from "@/lib/cn";
import { fetchSqlProjects, type SqlProject } from "@/lib/api/query-memory";

const STORAGE_KEY = "aion_sql_query_project";

type Props = {
  userId: string;
  token?: string | null;
  profileSlug?: string;
  value: string;
  onChange: (slug: string) => void;
  className?: string;
  compact?: boolean;
};

export function ProjectSelector({
  userId,
  token,
  profileSlug,
  value,
  onChange,
  className,
  compact = false,
}: Props) {
  const [projects, setProjects] = useState<SqlProject[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);

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

  return (
    <label className={cn("flex min-w-0 flex-col gap-0.5", className)}>
      <span className={cn("text-muted-foreground", compact ? "text-[10px]" : "text-[11px]")}>
        Project
      </span>
      <span
        className={cn(
          "focus-within:ring-ring/50 flex min-w-0 items-center gap-1.5 rounded-full border border-border bg-muted/40 focus-within:ring-1",
          compact ? "h-7 px-2" : "h-8 px-2.5"
        )}
      >
        <Database size={12} className="shrink-0 text-primary" aria-hidden />
        <select
          className={cn(
            "min-w-0 flex-1 bg-transparent text-foreground outline-none",
            compact ? "max-w-[8rem] text-[11px]" : "max-w-[10rem] text-xs"
          )}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          aria-label="SQL QueryMemory project drawer"
        >
          {projects.length === 0 && (
            <option value={value || "default"}>{value || "default"}</option>
          )}
          {value && !projects.some((p) => p.slug === value) && (
            <option value={value}>{value}</option>
          )}
          {projects.map((p) => (
            <option key={p.id} value={p.slug}>
              {p.display_name}
            </option>
          ))}
        </select>
      </span>
      {loadError ? (
        <span className="text-[10px] text-destructive truncate" title={loadError}>
          {loadError}
        </span>
      ) : null}
    </label>
  );
}

export function readStoredSqlProject(): string {
  if (typeof window === "undefined") return "default";
  return localStorage.getItem(STORAGE_KEY) || "default";
}
