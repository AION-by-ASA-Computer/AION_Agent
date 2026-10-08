"use client";

import { useMemo } from "react";
import {
  Download,
  FileSpreadsheet,
  FileText,
  Image as ImageIcon,
  Archive,
  Presentation,
  File,
  ExternalLink,
} from "lucide-react";
import { cn } from "@/lib/cn";

type FileMeta = {
  ext: string;
  category: string;
  icon: typeof FileText;
  badgeClass: string;
  cardClass: string;
  actionBtnClass: string;
  iconColor: string;
};

function getFileMeta(filename: string): FileMeta {
  const parts = filename.split(".");
  const ext = (parts.length > 1 ? parts.pop() : "")?.toLowerCase() || "";

  switch (ext) {
    case "docx":
    case "doc":
    case "odt":
    case "rtf":
      return {
        ext: ext.toUpperCase(),
        category: "Documento",
        icon: FileText,
        badgeClass: "bg-blue-500/15 border-blue-500/30 text-blue-600 dark:text-blue-400 shadow-2xs",
        cardClass:
          "bg-blue-500/[0.08] border-blue-500/30 hover:border-blue-500/50 hover:bg-blue-500/[0.13] dark:bg-blue-950/30 dark:border-blue-500/35 dark:hover:bg-blue-950/45 dark:hover:border-blue-500/55",
        actionBtnClass:
          "border-blue-500/30 bg-background/90 text-blue-700 dark:text-blue-300 group-hover:bg-background group-hover:border-blue-500/50",
        iconColor: "text-blue-600 dark:text-blue-400",
      };
    case "xlsx":
    case "xls":
    case "csv":
    case "tsv":
    case "ods":
      return {
        ext: ext.toUpperCase(),
        category: "Foglio di calcolo",
        icon: FileSpreadsheet,
        badgeClass: "bg-emerald-500/15 border-emerald-500/30 text-emerald-600 dark:text-emerald-400 shadow-2xs",
        cardClass:
          "bg-emerald-500/[0.08] border-emerald-500/30 hover:border-emerald-500/50 hover:bg-emerald-500/[0.13] dark:bg-emerald-950/30 dark:border-emerald-500/35 dark:hover:bg-emerald-950/45 dark:hover:border-emerald-500/55",
        actionBtnClass:
          "border-emerald-500/30 bg-background/90 text-emerald-700 dark:text-emerald-300 group-hover:bg-background group-hover:border-emerald-500/50",
        iconColor: "text-emerald-600 dark:text-emerald-400",
      };
    case "pptx":
    case "ppt":
    case "odp":
      return {
        ext: ext.toUpperCase(),
        category: "Presentazione",
        icon: Presentation,
        badgeClass: "bg-amber-500/15 border-amber-500/30 text-amber-600 dark:text-amber-400 shadow-2xs",
        cardClass:
          "bg-amber-500/[0.08] border-amber-500/30 hover:border-amber-500/50 hover:bg-amber-500/[0.13] dark:bg-amber-950/30 dark:border-amber-500/35 dark:hover:bg-amber-950/45 dark:hover:border-amber-500/55",
        actionBtnClass:
          "border-amber-500/30 bg-background/90 text-amber-700 dark:text-amber-300 group-hover:bg-background group-hover:border-amber-500/50",
        iconColor: "text-amber-600 dark:text-amber-400",
      };
    case "pdf":
      return {
        ext: "PDF",
        category: "Documento PDF",
        icon: FileText,
        badgeClass: "bg-rose-500/15 border-rose-500/30 text-rose-600 dark:text-rose-400 shadow-2xs",
        cardClass:
          "bg-rose-500/[0.08] border-rose-500/30 hover:border-rose-500/50 hover:bg-rose-500/[0.13] dark:bg-rose-950/30 dark:border-rose-500/35 dark:hover:bg-rose-950/45 dark:hover:border-rose-500/55",
        actionBtnClass:
          "border-rose-500/30 bg-background/90 text-rose-700 dark:text-rose-300 group-hover:bg-background group-hover:border-rose-500/50",
        iconColor: "text-rose-600 dark:text-rose-400",
      };
    case "png":
    case "jpg":
    case "jpeg":
    case "webp":
    case "svg":
    case "gif":
      return {
        ext: ext.toUpperCase(),
        category: "Immagine",
        icon: ImageIcon,
        badgeClass: "bg-violet-500/15 border-violet-500/30 text-violet-600 dark:text-violet-400 shadow-2xs",
        cardClass:
          "bg-violet-500/[0.08] border-violet-500/30 hover:border-violet-500/50 hover:bg-violet-500/[0.13] dark:bg-violet-950/30 dark:border-violet-500/35 dark:hover:bg-violet-950/45 dark:hover:border-violet-500/55",
        actionBtnClass:
          "border-violet-500/30 bg-background/90 text-violet-700 dark:text-violet-300 group-hover:bg-background group-hover:border-violet-500/50",
        iconColor: "text-violet-600 dark:text-violet-400",
      };
    case "zip":
    case "tar":
    case "gz":
    case "7z":
    case "rar":
      return {
        ext: ext.toUpperCase(),
        category: "Archivio",
        icon: Archive,
        badgeClass: "bg-orange-500/15 border-orange-500/30 text-orange-600 dark:text-orange-400 shadow-2xs",
        cardClass:
          "bg-orange-500/[0.08] border-orange-500/30 hover:border-orange-500/50 hover:bg-orange-500/[0.13] dark:bg-orange-950/30 dark:border-orange-500/35 dark:hover:bg-orange-950/45 dark:hover:border-orange-500/55",
        actionBtnClass:
          "border-orange-500/30 bg-background/90 text-orange-700 dark:text-orange-300 group-hover:bg-background group-hover:border-orange-500/50",
        iconColor: "text-orange-600 dark:text-orange-400",
      };
    default:
      return {
        ext: ext ? ext.toUpperCase() : "FILE",
        category: "File",
        icon: File,
        badgeClass: "bg-muted text-muted-foreground border-border/50",
        cardClass:
          "bg-card/75 border-border/80 hover:border-border hover:bg-muted/40",
        actionBtnClass:
          "border-border bg-background/90 text-foreground group-hover:bg-background",
        iconColor: "text-muted-foreground",
      };
  }
}

export function GeneratedFileCard({
  filename,
  downloadUrl,
  className,
}: {
  filename: string;
  downloadUrl?: string;
  className?: string;
}) {
  const cleanName = useMemo(() => {
    const raw = filename.replace(/\\/g, "/");
    return raw.split("/").pop() || filename;
  }, [filename]);

  const meta = useMemo(() => getFileMeta(cleanName), [cleanName]);
  const Icon = meta.icon;

  const canPreviewInBrowser =
    meta.ext === "PDF" ||
    meta.ext === "HTML" ||
    meta.category === "Immagine";

  const cardContent = (
    <>
      {/* Icon and File Details */}
      <div className="flex items-center gap-3.5 min-w-0 flex-1">
        <div
          className={cn(
            "flex size-11 sm:size-12 shrink-0 items-center justify-center rounded-xl border transition-transform duration-200 group-hover:scale-105",
            meta.badgeClass,
          )}
          aria-hidden="true"
        >
          <Icon className={cn("size-5 sm:size-6", meta.iconColor)} />
        </div>

        <div className="min-w-0 flex-1">
          <p
            className="text-sm font-semibold text-foreground truncate tracking-tight leading-snug group-hover:underline group-hover:underline-offset-2"
            title={cleanName}
          >
            {cleanName}
          </p>
          <p className="mt-0.5 text-[11px] font-medium text-muted-foreground uppercase tracking-wider">
            {meta.category} {meta.ext ? `· ${meta.ext}` : ""}
          </p>
        </div>
      </div>

      {/* Action pill: visual affordance */}
      <div
        className={cn(
          "inline-flex shrink-0 items-center gap-1.5 rounded-xl border px-3.5 py-1.5 text-xs font-semibold shadow-2xs transition-all duration-200 pointer-events-none",
          meta.actionBtnClass,
        )}
      >
        {canPreviewInBrowser ? (
          <>
            <span>Apri</span>
            <ExternalLink size={13} className="shrink-0" aria-hidden="true" />
          </>
        ) : (
          <>
            <Download size={13} className="shrink-0" aria-hidden="true" />
            <span>Scarica</span>
          </>
        )}
      </div>
    </>
  );

  if (downloadUrl) {
    return (
      <a
        href={downloadUrl}
        target={canPreviewInBrowser ? "_blank" : undefined}
        rel="noopener noreferrer"
        download={!canPreviewInBrowser ? cleanName : undefined}
        className={cn(
          "group relative flex items-center justify-between gap-3.5 rounded-2xl border p-3.5 sm:p-4 shadow-2xs backdrop-blur-md transition-all duration-200 cursor-pointer hover:shadow-xs active:scale-[0.99] select-none",
          meta.cardClass,
          className,
        )}
      >
        {cardContent}
      </a>
    );
  }

  return (
    <div
      className={cn(
        "group relative flex items-center justify-between gap-3.5 rounded-2xl border p-3.5 sm:p-4 shadow-2xs backdrop-blur-md transition-all duration-200",
        meta.cardClass,
        className,
      )}
    >
      {cardContent}
    </div>
  );
}
