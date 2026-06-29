/** Client-safe admin UI path prefix (empty in local dev, `/admin` in Docker prod). */
export function adminBasePath(): string {
  const raw = (process.env.NEXT_PUBLIC_BASE_PATH ?? "").trim().replace(/\/$/, "");
  return raw === "/" ? "" : raw;
}

/** Prefix an app route for hard navigations (`window.location`, SSE URLs). */
export function adminPath(path: string): string {
  const p = path.startsWith("/") ? path : `/${path}`;
  const bp = adminBasePath();
  return bp ? `${bp}${p}` : p;
}
