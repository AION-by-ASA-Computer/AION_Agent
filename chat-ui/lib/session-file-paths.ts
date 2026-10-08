/**
 * Session file filtering utilities.
 * Filters out internal engine artifacts, tool cache, scripts (.py, .js, .ts),
 * and runtime configurations (.json) so only user-facing output files are shown.
 */

const EXCLUDED_EXTENSIONS = new Set([
  "json",
  "jsonl",
  "py",
  "pyc",
  "pyo",
  "pyd",
  "js",
  "mjs",
  "cjs",
  "ts",
  "tsx",
  "jsx",
  "sh",
  "bash",
  "bat",
  "cmd",
  "ps1",
  "tmp",
  "temp",
  "log",
  "lock",
  "pid",
  "swp",
]);

/** Offloaded tool results (L1 context offloading) — hidden from user file lists. */
export function isToolOffloadSessionPath(relativePath?: string | null): boolean {
  const rel = (relativePath || "").replace(/\\/g, "/").trim();
  return rel.startsWith("derived/tool_results/");
}

/**
 * Intelligent filter for files generated in session workspace.
 * True only for actual user-facing deliverable files (e.g. .docx, .xlsx, .pdf, .csv, .zip, images, reports).
 */
export function isUserFacingGeneratedFile(relativePathOrName?: string | null): boolean {
  if (!relativePathOrName) return false;
  const rel = relativePathOrName.replace(/\\/g, "/").trim();
  if (isToolOffloadSessionPath(rel)) return false;

  const fileName = rel.split("/").pop() || "";
  if (!fileName || fileName.startsWith(".")) return false;

  const dotIdx = fileName.lastIndexOf(".");
  if (dotIdx === -1) {
    // Files without extensions in workspace are typically internal scratch or binaries
    return false;
  }

  const ext = fileName.slice(dotIdx + 1).toLowerCase();
  return !EXCLUDED_EXTENSIONS.has(ext);
}

export function filterUserVisibleSessionFiles<T extends { relative_path?: string; name?: string }>(
  files: T[],
): T[] {
  return files.filter((f) => isUserFacingGeneratedFile(f.relative_path || f.name));
}
