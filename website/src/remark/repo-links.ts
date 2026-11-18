/**
 * Remark plugin: turn links to repository files into GitHub links.
 *
 * Why: the Markdown in `docs/` often links to source files (`src/api/main.py`,
 * `../../scripts/install.sh`, `config_std/...`). Those links work when reading
 * the Markdown on GitHub or in an editor, but they are not pages of the
 * Docusaurus site, so the build reported them as broken and readers of the
 * published site (Docusaurus / Vercel) landed on 404 pages.
 *
 * What it does, for every Markdown link (and link definition) whose URL is a
 * relative path that is NOT a `.md`/`.mdx` page:
 *   1. resolve it relative to the Markdown file; if that points to an existing
 *      file or folder inside the repository, use it;
 *   2. otherwise try it as a repository-root path (authors often write
 *      `src/api/main.py` from any page);
 *   3. if found, rewrite the URL to
 *      `https://github.com/<org>/<repo>/blob|tree/<branch>/<path>` keeping any
 *      `#L10`-style fragment.
 * Links that cannot be resolved are left untouched, so Docusaurus still
 * reports them as broken.
 *
 * Used by `website/docusaurus.config.ts` (docs plugin `remarkPlugins`).
 * Options: `repoRoot` (absolute path of the repository) and `githubBase`
 * (e.g. `https://github.com/AION-by-ASA-Computer/AION_Agent`), `branch`.
 */
import fs from 'node:fs';
import path from 'node:path';

type Options = {repoRoot: string; githubBase: string; branch?: string};

// Minimal mdast shape: we only need `type`, `url` and `children`.
type MdNode = {type: string; url?: string; children?: MdNode[]};

/** True for URLs that must never be rewritten (absolute, anchors, site paths, pages). */
function isSkippable(url: string): boolean {
  return (
    url === '' ||
    url.startsWith('#') ||
    url.startsWith('/') ||
    /^[a-z][a-z0-9+.-]*:/i.test(url) || // http:, https:, mailto:, file:, …
    /\.mdx?$/i.test(url.split(/[?#]/)[0])
  );
}

/** Return the repo-relative POSIX path if `abs` exists inside the repository. */
function repoRelative(abs: string, repoRoot: string): string | null {
  const rel = path.relative(repoRoot, abs);
  if (rel === '' || rel.startsWith('..') || path.isAbsolute(rel)) return null;
  return fs.existsSync(abs) ? rel.split(path.sep).join('/') : null;
}

export default function repoLinks(options: Options) {
  const {repoRoot, githubBase} = options;
  const branch = options.branch ?? 'main';

  return (tree: MdNode, file: {path?: string; history?: string[]}) => {
    const filePath = file.path ?? file.history?.[0];
    if (!filePath) return;
    const fileDir = path.dirname(filePath);

    const rewrite = (node: MdNode) => {
      const url = node.url ?? '';
      if (isSkippable(url)) return;
      const hashIdx = url.indexOf('#');
      const target = decodeURI(hashIdx >= 0 ? url.slice(0, hashIdx) : url);
      const fragment = hashIdx >= 0 ? url.slice(hashIdx) : '';

      // 1) relative to the page, 2) relative to the repository root.
      const rel =
        repoRelative(path.resolve(fileDir, target), repoRoot) ??
        repoRelative(path.resolve(repoRoot, target), repoRoot);
      if (!rel) return;

      const kind = fs.statSync(path.join(repoRoot, rel)).isDirectory() ? 'tree' : 'blob';
      node.url = `${githubBase}/${kind}/${branch}/${encodeURI(rel)}${fragment}`;
    };

    // Depth-first walk over the Markdown tree.
    const walk = (node: MdNode) => {
      if (node.type === 'link' || node.type === 'definition') rewrite(node);
      node.children?.forEach(walk);
    };
    walk(tree);
  };
}
