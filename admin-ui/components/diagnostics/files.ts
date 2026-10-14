import { apiBase } from "@/lib/api";
import { getStoredToken } from "@/lib/auth/storage";
import { cleanFilePath } from "./format";

/** Workspace files produced by a run are served by the admin API; the token rides in the query for <img>/<a>. */
export function fileUrl(rawPath: string, download = false): string {
  const token = getStoredToken();
  return `${apiBase()}/admin/diagnostics/file?path=${encodeURIComponent(cleanFilePath(rawPath))}${download ? "&download=1" : ""}&access_token=${token || ""}`;
}

export function saveMarkdown(content: string, filename: string) {
  const blob = new Blob([content], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename.endsWith(".md") ? filename : `${filename}.md`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
