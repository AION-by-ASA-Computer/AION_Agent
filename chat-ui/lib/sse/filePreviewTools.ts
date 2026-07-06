/** Filesystem tools that stream file content via early artifact SSE on tool_start. */
export const FILE_PREVIEW_TOOL_NAMES = new Set([
  "sandbox_write_workspace_file",
  "sandbox_edit_workspace_file",
  "sandbox_apply_patch",
]);

export function isFilePreviewTool(name: string): boolean {
  const base = name.split("-").pop()?.toLowerCase() ?? name.toLowerCase();
  return FILE_PREVIEW_TOOL_NAMES.has(base);
}

export function generatingTitleForFileTool(
  toolName: string,
  input: unknown,
): string | undefined {
  const args = (input && typeof input === "object" ? input : {}) as Record<string, unknown>;
  const rel = String(args.relative_path ?? "").trim();
  if (rel) {
    const base = rel.split("/").pop() || rel;
    return base;
  }
  if (toolName.includes("apply_patch")) {
    return "patch";
  }
  return undefined;
}

export function isScriptLikeTitle(title?: string): boolean {
  if (!title) return false;
  const t = title.toLowerCase();
  return t.endsWith(".js") || t.endsWith(".ts") || t.endsWith(".mjs");
}
