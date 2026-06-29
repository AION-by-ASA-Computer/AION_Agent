export function formatToolInput(input: unknown, maxChars = 8192): string {
  if (input == null) return "";
  let text: string;
  if (typeof input === "string") {
    text = input;
    try {
      const parsed = JSON.parse(input);
      text = JSON.stringify(parsed, null, 2);
    } catch {
      /* keep raw string */
    }
  } else {
    try {
      text = JSON.stringify(input, null, 2);
    } catch {
      text = String(input);
    }
  }
  if (text.length > maxChars) {
    return `${text.slice(0, maxChars)}\n… [troncato]`;
  }
  return text;
}

export function toolInputPreview(input: unknown): string {
  if (input == null) return "";
  if (typeof input === "object" && (input as Record<string, unknown>)._pending === true) {
    return "preparazione in corso…";
  }
  if (typeof input !== "object") return "";
  const obj = input as Record<string, unknown>;
  const keys = ["query", "relative_path", "url", "name", "path", "file"];
  const parts: string[] = [];
  for (const k of keys) {
    if (obj[k] != null && String(obj[k]).trim()) {
      parts.push(`${k}=${String(obj[k]).slice(0, 80)}`);
    }
    if (parts.length >= 2) break;
  }
  if (typeof obj.content === "string" && obj.content.length > 0) {
    const kb = Math.round(obj.content.length / 1024);
    parts.push(`content≈${kb} KB`);
  }
  return parts.join(", ");
}
