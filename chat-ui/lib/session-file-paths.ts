/** Offloaded tool results (L1 context offloading) — hidden from user file lists. */
export function isToolOffloadSessionPath(relativePath?: string | null): boolean {
  const rel = (relativePath || "").replace(/\\/g, "/").trim();
  return rel.startsWith("derived/tool_results/");
}

export function filterUserVisibleSessionFiles<T extends { relative_path?: string }>(
  files: T[],
): T[] {
  return files.filter((f) => !isToolOffloadSessionPath(f.relative_path));
}
