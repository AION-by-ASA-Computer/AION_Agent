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
        "focus-ring ml-2 inline-flex h-7 max-w-[10rem] items-center gap-1 rounded-full border border-primary/25 bg-primary/8 px-2.5 text-[11px] font-medium text-primary transition-colors hover:bg-primary/15",
        className
      )}
    >
      <Database size={12} className="shrink-0" aria-hidden />
      <span className="truncate">{label}</span>
      <ChevronRight size={11} className="shrink-0 opacity-60" aria-hidden />
    </button>
  );
}
