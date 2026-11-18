/**
 * Remark plugin: turn links to repository files into GitHub links.
 *
 * Why: the Markdown in `docs/` often links to source files (`src/api/main.py`,
 * `../../scripts/install.sh`, `config_std/...`). Those links work when reading
 * the Markdown on GitHub or in an editor, but they are not pages of the
 * Docusaurus site, so the build would report them as broken and readers of the
 * published site (Vercel / Docker) would land on 404 pages.
 *
 * Important: the plugin must NOT depend on the source files being on disk.
 * The Docker image of the website (docker/Dockerfile.website) copies only
 * `website/` and `docs/`, so `src/`, `scripts/`, … do not exist there. The
 * rewrite is therefore decided from the link text alone; the disk is only
 * consulted for files inside `docs/` (always present).
 *
 * Rules, for every Markdown link / link definition whose URL is a relative
 * path that is NOT a `.md`/`.mdx` page:
 *   - `./x` or `../x`: resolved relative to the Markdown file (repo layout);
 *   - bare `x/y` (e.g. `src/api/main.py`): relative to the Markdown file when
 *     that file exists inside `docs/`, otherwise relative to the repository
 *     root (authors write repo-root paths from any page);
 *   - the result must stay inside the repository, else the link is untouched;
 *   - rewritten to `https://github.com/<org>/<repo>/blob|tree/<branch>/<path>`
 *     (`tree` when the link ends with `/`), keeping any `#L10`-style fragment.
 *
 * Used by `website/docusaurus.config.ts` (docs plugin `remarkPlugins`).
 * Options: `repoRoot` (absolute path of the repository), `githubBase`
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

/** Repo-relative POSIX path of `abs`, or null when it falls outside the repository. */
function toRepoPath(abs: string, repoRoot: string): string | null {
  const rel = path.relative(repoRoot, abs);
  if (rel === '' || rel.startsWith('..') || path.isAbsolute(rel)) return null;
  return rel.split(path.sep).join('/');
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
      if (!target) return;

      // Explicitly relative links follow the repository layout from the page.
      // Bare paths are page-relative only when they point to a file that
      // exists next to the page (e.g. docs/api-and-runtime/contract/*.json);
      // otherwise they are repository-root paths such as `src/api/main.py`.
      const explicit = target.startsWith('./') || target.startsWith('../');
      const pageRelative = path.resolve(fileDir, target);
      const abs = explicit || fs.existsSync(pageRelative) ? pageRelative : path.resolve(repoRoot, target);

      const rel = toRepoPath(abs, repoRoot);
      if (!rel) return;

      const kind = target.endsWith('/') ? 'tree' : 'blob';
      node.url = `${githubBase}/${kind}/${branch}/${encodeURI(rel)}${target.endsWith('/') ? '/' : ''}${fragment}`;
    };

    // Depth-first walk over the Markdown tree.
    const walk = (node: MdNode) => {
      if (node.type === 'link' || node.type === 'definition') rewrite(node);
      node.children?.forEach(walk);
    };
    walk(tree);
  };
}
