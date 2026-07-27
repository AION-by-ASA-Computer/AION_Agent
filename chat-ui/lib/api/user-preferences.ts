import { apiBase } from "@/lib/config";

export const DEFAULT_PROFILE_METADATA_KEY = "default_profile_slug";
const LOCAL_STORAGE_KEY = "aion_default_profile_slug";

export type CurrentUser = {
  identifier?: string;
  metadata?: Record<string, unknown>;
};

export function readStoredDefaultProfileSlug(): string | null {
  if (typeof window === "undefined") return null;
  const raw = localStorage.getItem(LOCAL_STORAGE_KEY);
  return raw?.trim() || null;
}

export function writeStoredDefaultProfileSlug(slug: string): void {
  if (typeof window === "undefined") return;
  localStorage.setItem(LOCAL_STORAGE_KEY, slug);
}

export function readDefaultProfileSlug(metadata?: Record<string, unknown> | null): string | null {
  const raw = metadata?.[DEFAULT_PROFILE_METADATA_KEY];
  if (typeof raw !== "string") return null;
  const slug = raw.trim();
  return slug || null;
}

export async function fetchCurrentUser(token: string): Promise<CurrentUser | null> {
  try {
    const res = await fetch(`${apiBase()}/auth/me`, {
      headers: { Authorization: `Bearer ${token}` },
      cache: "no-store",
    });
    if (!res.ok) return null;
    return (await res.json()) as CurrentUser;
  } catch {
    return null;
  }
}

/** Persist default agent profile slug to ``users.metadata_json`` via PATCH /auth/me. */
export async function syncDefaultProfileSlug(token: string, slug: string): Promise<boolean> {
  try {
    const res = await fetch(`${apiBase()}/auth/me`, {
      method: "PATCH",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ metadata: { [DEFAULT_PROFILE_METADATA_KEY]: slug } }),
    });
    return res.ok;
  } catch {
    return false;
  }
}

export function resolveDefaultProfileSlug(
  profiles: Array<{ slug?: string; name: string }>,
  favoriteSlug: string | null | undefined,
): string {
  const normalized = profiles.map((p) => ({
    slug: p.slug || p.name.replace(/\s+/g, "_").toLowerCase(),
  }));
  if (favoriteSlug && normalized.some((p) => p.slug === favoriteSlug)) {
    return favoriteSlug;
  }
  if (normalized.some((p) => p.slug === "aion_std")) return "aion_std";
  return normalized[0]?.slug || "aion_std";
}
