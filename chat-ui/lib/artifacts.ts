export function artifactLanguage(artType: string, savedPath?: string): string {
  const path = (savedPath || "").toLowerCase();
  if (path.endsWith(".tsx")) return "tsx";
  if (path.endsWith(".ts")) return "typescript";
  if (path.endsWith(".jsx")) return "jsx";
  if (path.endsWith(".js")) return "javascript";
  if (path.endsWith(".py")) return "python";
  if (path.endsWith(".json")) return "json";
  if (path.endsWith(".md")) return "markdown";
  if (path.endsWith(".html")) return "html";
  if (path.endsWith(".css")) return "css";
  if (path.endsWith(".yaml") || path.endsWith(".yml")) return "yaml";
  const t = artType.trim().toLowerCase();
  if (t === "plan") return "markdown";
  if (t === "python") return "python";
  if (t === "html") return "html";
  return t || "text";
}
