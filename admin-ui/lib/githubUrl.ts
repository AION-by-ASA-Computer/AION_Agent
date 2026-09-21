const GITHUB_HOSTS = new Set(["github.com", "www.github.com"]);

/** True when ``url`` points at github.com (hostname check, not substring). */
export function isAllowedGithubUrl(url: string): boolean {
  try {
    const parsed = new URL(url);
    if (parsed.protocol !== "https:" && parsed.protocol !== "http:") {
      return false;
    }
    const host = parsed.hostname.toLowerCase();
    return GITHUB_HOSTS.has(host);
  } catch {
    return false;
  }
}

/** Build a canonical repo URL from a ``github:owner/repo`` marketplace id. */
export function githubRepoUrlFromId(id: string | undefined): string | null {
  if (!id?.startsWith("github:")) {
    return null;
  }
  const slug = id.slice("github:".length).trim().replace(/^\/+/, "");
  const parts = slug.split("/").filter(Boolean);
  if (parts.length < 2) {
    return null;
  }
  const [owner, repo, ...rest] = parts;
  if (rest.length > 0) {
    return null;
  }
  if (!/^[A-Za-z0-9_.-]+$/.test(owner) || !/^[A-Za-z0-9_.-]+$/.test(repo)) {
    return null;
  }
  const url = `https://github.com/${owner}/${repo}`;
  return isAllowedGithubUrl(url) ? url : null;
}

/** Pick the first validated GitHub repo URL from marketplace metadata. */
export function resolveGithubMarketplaceUrl(target: {
  url?: string;
  package_url?: string;
  id?: string;
}): string | null {
  const candidates = [
    target.url,
    target.package_url?.startsWith("http") ? target.package_url : undefined,
    githubRepoUrlFromId(target.id),
  ];
  for (const candidate of candidates) {
    if (candidate && isAllowedGithubUrl(candidate)) {
      return candidate;
    }
  }
  return null;
}
