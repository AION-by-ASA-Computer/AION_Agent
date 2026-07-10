/** Browser-visible API base (FastAPI URL). Must be absolute in dev — relative URLs would hit the Next.js origin and 404. */
export function apiBase(): string {
  const b = process.env.NEXT_PUBLIC_AION_API_URL?.trim().replace(/\/$/, "");
  if (b) return b;
  return "http://localhost:8001";
}

export function adminUiBase(): string {
  return (process.env.NEXT_PUBLIC_AION_ADMIN_UI_URL || "http://localhost:3870").replace(/\/$/, "");
}
