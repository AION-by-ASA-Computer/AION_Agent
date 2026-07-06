export type UserAppearanceMetadata = {
  profile_color?: string;
  avatar_url?: string;
};

export const PROFILE_ACCENT_COLORS = [
  { id: "violet", value: "#8b5cf6", className: "bg-violet-500" },
  { id: "blue", value: "#3b82f6", className: "bg-blue-500" },
  { id: "cyan", value: "#06b6d4", className: "bg-cyan-500" },
  { id: "emerald", value: "#10b981", className: "bg-emerald-500" },
  { id: "amber", value: "#f59e0b", className: "bg-amber-500" },
  { id: "rose", value: "#f43f5e", className: "bg-rose-500" },
  { id: "slate", value: "#64748b", className: "bg-slate-500" },
  { id: "primary", value: "", className: "bg-primary" },
] as const;

export function profileInitials(label: string): string {
  const cleaned = label.trim();
  if (!cleaned) return "?";
  const parts = cleaned.split(/\s+/).filter(Boolean);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  return cleaned.slice(0, 2).toUpperCase();
}

export function resolveProfileColor(metadata?: UserAppearanceMetadata | null): string {
  const stored = metadata?.profile_color?.trim();
  if (stored) {
    const match = PROFILE_ACCENT_COLORS.find((c) => c.id === stored || c.value === stored);
    if (match?.value) return match.value;
    if (stored.startsWith("#")) return stored;
  }
  return PROFILE_ACCENT_COLORS[0].value;
}

export function notifyProfileAppearanceUpdated(): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new Event("aion-profile-updated"));
}
