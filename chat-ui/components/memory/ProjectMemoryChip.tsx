"use client";

import { useCallback, useEffect, useState } from "react";
import { ChevronRight, Database } from "lucide-react";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";
import { fetchSqlProjects } from "@/lib/api/query-memory";

type Props = {
  userId: string;
  token?: string | null;
  profileSlug?: string;
  projectSlug: string;
  onOpenPanel: () => void;
  className?: string;
};

export function ProjectMemoryChip({
  userId,
  token,
  profileSlug,
  projectSlug,
  onOpenPanel,
  className,
}: Props) {
  const t = useT();
  const [label, setLabel] = useState(projectSlug);

  const resolveLabel = useCallback(async () => {
    try {
      const list = await fetchSqlProjects(userId, token, profileSlug);
      const hit = list.find((p) => p.slug === projectSlug);
      setLabel(hit?.display_name ?? projectSlug);
    } catch {
      setLabel(projectSlug);
    }
  }, [userId, token, profileSlug, projectSlug]);

  useEffect(() => {
    void resolveLabel();
  }, [resolveLabel]);

  return (
    <button
      type="button"
      title={t("memory_dock.open_panel")}
      onClick={onOpenPanel}
      className={cn(
        "focus-ring inline-flex h-7 max-w-[10rem] shrink items-center gap-1.5 rounded-full border border-black/[0.08] dark:border-white/[0.08] bg-card/70 dark:bg-card/40 px-3 text-xs font-semibold text-foreground shadow-2xs backdrop-blur-xl transition-all duration-200 hover:scale-[1.02] hover:bg-card/95 dark:hover:bg-card/70 hover:border-black/15 dark:hover:border-white/15 active:scale-[0.98] sm:max-w-[12rem]",
        className
      )}
    >
      <Database size={12} className="shrink-0 text-red-500 dark:text-red-400" aria-hidden />
      <span className="truncate">{label}</span>
      <ChevronRight size={10} className="shrink-0 opacity-60" aria-hidden />
    </button>
  );
}
