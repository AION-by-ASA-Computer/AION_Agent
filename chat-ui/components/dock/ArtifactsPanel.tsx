"use client";

import React, { useState } from "react";
import { cn } from "@/lib/cn";
import {
  LucideIcon,
  File,
  FileCode,
  FileSpreadsheet,
  FileText,
  FileImage,
  FileVideo,
  FileAudio,
  FileArchive,
  DownloadIcon,
  Folder,
  FolderOpen,
  ChevronRight,
  ChevronDown,
  RefreshCw,
} from "lucide-react";
import { useT } from "@/lib/i18n/use-t";
import { StreamingContentPreview } from "@/components/dock/StreamingContentPreview";
import { sessionDownloadUrl, type SessionFileRow } from "@/lib/api/aion";

export type DockArtifactItem = {
  key: string;
  id: string;
  title: string;
  language: string;
  typeLabel: string;
  savedPath?: string;
  downloadUrl?: string;
  execution?: string;
  source: "history" | "live";
  order: number;
  /** In-progress SSE buffer (not yet saved to workspace). */
  buffer?: string;
  streaming?: boolean;
};

interface IconConfig {
  icon: LucideIcon;
  bgClass: string;
  iconClass: string;
}

function getFileIconConfig(item: {
  title?: string;
  savedPath?: string;
  language?: string;
  typeLabel?: string;
}): IconConfig {
  const path = (item.savedPath || "").toLowerCase();
  const title = (item.title || "").toLowerCase();
  const lang = (item.language || "").toLowerCase();
  const typeLabel = (item.typeLabel || "").toLowerCase();

  const pdfExtensions = [".pdf"];
  const wordExtensions = [".doc", ".docx", ".odt", ".rtf"];
  const excelExtensions = [".xls", ".xlsx", ".csv", ".ods", ".tsv"];
  const imageExtensions = [".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp"];
  const videoExtensions = [".mp4", ".mov", ".avi", ".mkv", ".webm"];
  const audioExtensions = [".mp3", ".wav", ".ogg", ".m4a", ".flac"];
  const archiveExtensions = [".zip", ".rar", ".tar", ".gz", ".7z", ".tgz"];

  const codeLanguages = [
    "tsx", "typescript", "jsx", "javascript", "python", "json", "markdown", "html", "css",
    "yaml", "yml", "bash", "sh", "sql", "rust", "go", "cpp", "c", "java", "php", "ruby",
    "shell", "powershell", "xml"
  ];
  const codeExtensions = [
    ".tsx", ".ts", ".jsx", ".js", ".py", ".json", ".md", ".html", ".css",
    ".yaml", ".yml", ".sh", ".sql", ".rs", ".go", ".cpp", ".h", ".java", ".php", ".rb",
    ".xml", ".toml", ".ini", ".conf"
  ];

  // PDF
  if (
    pdfExtensions.some(ext => path.endsWith(ext) || title.endsWith(ext)) ||
    typeLabel.includes("pdf") ||
    lang === "pdf"
  ) {
    return {
      icon: FileText,
      bgClass: "bg-rose-500/10 border border-rose-500/20",
      iconClass: "text-rose-400",
    };
  }

  // Word
  if (
    wordExtensions.some(ext => path.endsWith(ext) || title.endsWith(ext)) ||
    typeLabel.includes("word") ||
    typeLabel.includes("docx") ||
    typeLabel.includes("msword")
  ) {
    return {
      icon: FileText,
      bgClass: "bg-blue-500/10 border border-blue-500/20",
      iconClass: "text-blue-400",
    };
  }

  // Excel / Spreadsheet
  if (
    excelExtensions.some(ext => path.endsWith(ext) || title.endsWith(ext)) ||
    typeLabel.includes("excel") ||
    typeLabel.includes("spreadsheet") ||
    typeLabel.includes("csv") ||
    typeLabel.includes("sheet") ||
    lang === "csv"
  ) {
    return {
      icon: FileSpreadsheet,
      bgClass: "bg-emerald-500/10 border border-emerald-500/20",
      iconClass: "text-emerald-400",
    };
  }

  // Images
  if (
    imageExtensions.some(ext => path.endsWith(ext) || title.endsWith(ext)) ||
    typeLabel.startsWith("image/") ||
    typeLabel.includes("image")
  ) {
    return {
      icon: FileImage,
      bgClass: "bg-violet-500/10 border border-violet-500/20",
      iconClass: "text-violet-400",
    };
  }

  // Video
  if (
    videoExtensions.some(ext => path.endsWith(ext) || title.endsWith(ext)) ||
    typeLabel.startsWith("video/") ||
    typeLabel.includes("video")
  ) {
    return {
      icon: FileVideo,
      bgClass: "bg-fuchsia-500/10 border border-fuchsia-500/20",
      iconClass: "text-fuchsia-400",
    };
  }

  // Audio
  if (
    audioExtensions.some(ext => path.endsWith(ext) || title.endsWith(ext)) ||
    typeLabel.startsWith("audio/") ||
    typeLabel.includes("audio")
  ) {
    return {
      icon: FileAudio,
      bgClass: "bg-cyan-500/10 border border-cyan-500/20",
      iconClass: "text-cyan-400",
    };
  }

  // Archives
  if (
    archiveExtensions.some(ext => path.endsWith(ext) || title.endsWith(ext)) ||
    typeLabel.includes("zip") ||
    typeLabel.includes("archive") ||
    typeLabel.includes("compressed")
  ) {
    return {
      icon: FileArchive,
      bgClass: "bg-amber-500/10 border border-amber-500/20",
      iconClass: "text-amber-400",
    };
  }

  // Generic Code
  if (
    codeLanguages.includes(lang) ||
    codeExtensions.some(ext => path.endsWith(ext) || title.endsWith(ext)) ||
    typeLabel.includes("code") ||
    (lang !== "text" && lang !== "" && !lang.includes("artifact"))
  ) {
    return {
      icon: FileCode,
      bgClass: "bg-indigo-500/10 border border-indigo-500/20",
      iconClass: "text-indigo-400",
    };
  }

  // Default
  return {
    icon: File,
    bgClass: "bg-slate-500/10 border border-slate-500/20",
    iconClass: "text-slate-400",
  };
}

export function ArtifactsPanel({
  items,
  sessionFiles = [],
  loadingFiles = false,
  onRefreshFiles,
  conversationId,
  token,
}: {
  items: DockArtifactItem[];
  sessionFiles?: SessionFileRow[];
  loadingFiles?: boolean;
  onRefreshFiles?: () => void;
  conversationId?: string;
  token?: string | null;
}) {
  const t = useT();

  const [expandedFolders, setExpandedFolders] = useState<Record<string, boolean>>({
    root: true,
    uploads: true,
    derived: true,
    workspace: true,
  });

  const toggleFolder = (folder: string) => {
    setExpandedFolders((prev) => ({
      ...prev,
      [folder]: !prev[folder],
    }));
  };

  // Filtra i file relativi agli "execution_plan"
  const filteredItems = items.filter((item) => {
    const title = (item.title || "").toLowerCase();
    const savedPath = (item.savedPath || "").toLowerCase();
    const typeLabel = (item.typeLabel || "").toLowerCase();
    const lang = (item.language || "").toLowerCase();

    const isExecutionPlan =
      title.includes("execution_plan") ||
      savedPath.includes("execution_plan") ||
      typeLabel === "plan" ||
      lang === "plan";

    return !isExecutionPlan;
  });

  const handleItemClick = (itemId: string) => {
    const element = document.getElementById(`artifact-${itemId}`);
    if (element) {
      // 1. Scroll the element into center view smoothly
      element.scrollIntoView({ behavior: "smooth", block: "center" });

      // 2. Add visual highlight pulse effect
      element.classList.add("ring-2", "ring-primary", "scale-[1.01]", "transition-all", "duration-300");
      setTimeout(() => {
        element.classList.remove("ring-2", "ring-primary", "scale-[1.01]");
      }, 2000);

      // 3. Open the details accordion if closed
      const summary = element.querySelector("summary");
      if (summary && element instanceof HTMLDetailsElement && !element.open) {
        summary.click();
      }
    }
  };

  if (!filteredItems.length && !sessionFiles.length) {
    return (
      <div className="p-4 flex flex-col items-center justify-center gap-2 text-center text-muted-foreground select-none">
        <File size={24} className="opacity-40" />
        <p className="text-xs">
          {t("artifacts.no_artifacts")}
        </p>
      </div>
    );
  }

  const rootFiles = sessionFiles.filter((f) => {
    const rel = f.relative_path || "";
    return !rel.includes("/");
  });
  const uploadsFiles = sessionFiles.filter((f) => f.relative_path?.startsWith("uploads/"));
  const derivedFiles = sessionFiles.filter((f) => f.relative_path?.startsWith("derived/"));
  const workspaceFiles = sessionFiles.filter((f) => f.relative_path?.startsWith("workspace/"));

  const renderFolder = (
    folderKey: "root" | "uploads" | "derived" | "workspace",
    files: SessionFileRow[]
  ) => {
    const isExpanded = expandedFolders[folderKey];
    const folderTitle = t(`artifacts.${folderKey}`);
    
    // Custom theme colors for folders
    const themeColors = {
      root: {
        bg: "bg-emerald-500/10 hover:bg-emerald-500/15 border-emerald-500/20",
        text: "text-emerald-400",
        folderBg: "bg-emerald-500/10",
      },
      uploads: {
        bg: "bg-amber-500/10 hover:bg-amber-500/15 border-amber-500/20",
        text: "text-amber-400",
        folderBg: "bg-amber-500/10",
      },
      derived: {
        bg: "bg-cyan-500/10 hover:bg-cyan-500/15 border-cyan-500/20",
        text: "text-cyan-400",
        folderBg: "bg-cyan-500/10",
      },
      workspace: {
        bg: "bg-violet-500/10 hover:bg-violet-500/15 border-violet-500/20",
        text: "text-violet-400",
        folderBg: "bg-violet-500/10",
      },
    }[folderKey];

    return (
      <div className="border border-border/40 rounded-lg bg-card/25 overflow-hidden transition-all duration-200">
        {/* Folder Header Row */}
        <button
          type="button"
          onClick={() => toggleFolder(folderKey)}
          className="w-full flex items-center justify-between px-3 py-2 text-xs font-semibold text-foreground hover:bg-muted/40 transition-colors select-none"
        >
          <div className="flex items-center gap-2">
            {isExpanded ? <ChevronDown size={14} className="text-muted-foreground/75" /> : <ChevronRight size={14} className="text-muted-foreground/75" />}
            <div className={cn("p-1 rounded flex items-center justify-center", themeColors.folderBg)}>
              {isExpanded ? (
                <FolderOpen size={13} className={themeColors.text} />
              ) : (
                <Folder size={13} className={themeColors.text} />
              )}
            </div>
            <span>{folderTitle}</span>
          </div>
          <span className="text-[10px] bg-muted/65 text-muted-foreground px-1.5 py-0.5 rounded-full border border-border/30">
            {files.length}
          </span>
        </button>

        {/* Expanded Content */}
        {isExpanded && (
          <div className="border-t border-border/35 bg-card/10 p-2 space-y-1 animate-in fade-in-50 duration-150">
            {files.length === 0 ? (
              <p className="text-[11px] text-muted-foreground/50 italic py-2 px-3 pl-8 select-none">
                Nessun file presente.
              </p>
            ) : (
              files.map((file, idx) => {
                const relPath = file.relative_path || "";
                const displayName = file.name || relPath.split("/").pop() || "file";
                const downloadUrl = conversationId ? sessionDownloadUrl(conversationId, relPath, token) : undefined;
                const iconConfig = getFileIconConfig({
                  title: displayName,
                  savedPath: relPath,
                  language: file.mime || "",
                  typeLabel: file.mime || "file",
                });

                return (
                  <div
                    key={idx}
                    className="group relative flex items-center justify-between rounded-md px-2.5 py-1.5 text-xs text-muted-foreground hover:bg-card/65 hover:text-foreground transition-all duration-150 pl-8"
                  >
                    <div className="flex items-center gap-2.5 min-w-0 flex-1">
                      <div className={cn("p-1 rounded shrink-0 flex items-center justify-center", iconConfig.bgClass)}>
                        <iconConfig.icon size={13} className={iconConfig.iconClass} />
                      </div>
                      <div className="min-w-0 flex-1 flex items-center justify-between gap-2 pr-2">
                        <span className="truncate text-xs font-medium text-foreground/85 group-hover:text-foreground">
                          {displayName}
                        </span>
                        {file.size_bytes !== undefined && (
                          <span className="shrink-0 text-[10px] text-muted-foreground/50">
                            {formatBytes(file.size_bytes)}
                          </span>
                        )}
                      </div>
                    </div>

                    {downloadUrl && (
                      <a
                        href={downloadUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="focus-ring opacity-0 group-hover:opacity-100 transition-opacity p-1 rounded hover:bg-muted text-muted-foreground hover:text-foreground shrink-0"
                        onClick={(e) => e.stopPropagation()}
                      >
                        <DownloadIcon size={13} />
                      </a>
                    )}
                  </div>
                );
              })
            )}
          </div>
        )}
      </div>
    );
  };

  return (
    <div className="space-y-4 p-3">
      {/* Session Files Section */}
      <div className="space-y-2">
        <div className="flex items-center justify-between px-1 py-1 border-b border-border/15 pb-2 mb-3">
          <h3 className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground/60 flex items-center gap-1.5 select-none">
            <Folder size={12} />
            {t("artifacts.session_files")}
          </h3>
          {onRefreshFiles && (
            <button
              type="button"
              onClick={onRefreshFiles}
              className="flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] text-muted-foreground/60 hover:text-foreground hover:bg-muted/50 transition-all select-none"
              title={t("artifacts.refresh")}
            >
              <RefreshCw size={10} className={cn(loadingFiles && "animate-spin")} />
              {t("artifacts.refresh")}
            </button>
          )}
        </div>
        
        {loadingFiles && sessionFiles.length === 0 ? (
          <p className="text-[11px] text-muted-foreground/50 text-center py-4 animate-pulse select-none">Caricamento...</p>
        ) : (
          <div className="space-y-2.5">
            {rootFiles.length > 0 && renderFolder("root", rootFiles)}
            {renderFolder("uploads", uploadsFiles)}
            {renderFolder("derived", derivedFiles)}
            {renderFolder("workspace", workspaceFiles)}
          </div>
        )}
      </div>

      {/* Generated Artifacts Section */}
      {filteredItems.length > 0 && (
        <div className="space-y-2 mt-6">
          <div className="flex items-center justify-between px-1 py-1 border-b border-border/15 pb-2 mb-3 select-none">
            <h3 className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground/60 flex items-center gap-1.5">
              <FileCode size={12} />
              {t("artifacts.generated_artifacts")}
            </h3>
          </div>
          <div className="space-y-2">
            {filteredItems.map((item) => {
              const iconConfig = getFileIconConfig(item);

              return (
                <article
                  key={item.key}
                  onClick={() => handleItemClick(item.id)}
                  className="group relative rounded-aion border border-border bg-card/50 p-3 text-xs hover:bg-card/80 cursor-pointer transition-all duration-200"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex items-start gap-2.5 min-w-0 flex-1">
                      {/* Icona con stile premium */}
                      <div className={cn(
                        "p-1.5 rounded-md shrink-0 flex items-center justify-center transition-transform duration-200 group-hover:scale-105",
                        iconConfig.bgClass
                      )}>
                        <iconConfig.icon size={16} className={iconConfig.iconClass} />
                      </div>

                      {/* Info File */}
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-[13px] font-medium text-foreground transition-colors group-hover:text-foreground/90">
                          {item.title}
                        </p>
                        <p className="mt-0.5 text-[11px] text-muted-foreground flex items-center gap-1.5 flex-wrap">
                          <span>{item.typeLabel}</span>
                          <span className="text-muted-foreground/30">•</span>
                          <span>{item.language}</span>
                          <span className="text-muted-foreground/30">•</span>
                          <span className={cn(
                            "inline-flex items-center rounded-full px-1.5 py-0.2 text-[9px] font-semibold border uppercase tracking-wider",
                            item.source === "live"
                              ? "bg-amber-500/10 text-amber-400 border-amber-500/20"
                              : "bg-blue-500/10 text-blue-400 border-blue-500/20"
                          )}>
                            {item.source === "live" ? t("artifacts.source.live") : t("artifacts.source.history")}
                          </span>
                        </p>
                      </div>
                    </div>

                    {/* Azioni */}
                    {item.downloadUrl ? (
                      <a
                        className="focus-ring shrink-0 rounded-full bg-primary/15 px-2.5 py-1 text-[11px] font-medium text-primary transition-colors hover:bg-primary/25 flex items-center gap-1.5"
                        href={item.downloadUrl}
                        target="_blank"
                        rel="noreferrer"
                        onClick={(e) => e.stopPropagation()}
                      >
                        <DownloadIcon size={12} aria-hidden />
                        {t("artifacts.download")}
                      </a>
                    ) : (
                      <span className="shrink-0 rounded-full bg-muted px-2.5 py-1 text-[11px] text-muted-foreground">
                        {t("artifacts.in_memory")}
                      </span>
                    )}
                  </div>

                  {/* Path e Risultato Esecuzione allineati perfettamente */}
                  {item.savedPath ? (
                    <p className="mt-2 truncate font-mono text-[10px] text-muted-foreground pl-[38px]">
                      {item.savedPath}
                    </p>
                  ) : null}
                  {item.execution ? (
                    <p className="mt-2 text-[11px] text-muted-foreground pl-[38px]">
                      {item.execution}
                    </p>
                  ) : null}
                  {item.streaming ? (
                    <div className="mt-3 overflow-hidden rounded-lg border border-border/60">
                      <StreamingContentPreview
                        title={item.title}
                        content={item.buffer || ""}
                        streaming
                        kind="artifact"
                      />
                    </div>
                  ) : null}
                </article>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

function formatBytes(bytes?: number): string {
  if (bytes === undefined || bytes === null || isNaN(bytes)) return "";
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + " " + sizes[i];
}
