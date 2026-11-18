# AION Agents documentation site

Docusaurus shell for the documentation in the repository-level [`docs/`](../docs) folder
(the Markdown is the single source of truth; this folder only contains the site:
config, sidebars, theme, search).

| File | Purpose |
|---|---|
| `docusaurus.config.ts` | Site config: navbar tabs, footer, local search, base URL, GitHub edit links. |
| `sidebars.ts` | The four audience sidebars (Get started, API, Administration, Internals). Every page in `docs/` must be listed here. |
| `src/remark/repo-links.ts` | Turns links to repository files (`src/...`, `scripts/...`) into GitHub links. |
| `src/css/custom.css` | AION theme (colours, font, tables), shared by every deployment. |
| `vercel.json` | Build settings for the Vercel project. |

## Local preview

The website is part of the pnpm workspace at the repository root.

```bash
pnpm install            # from the repository root, once
cd website
pnpm start              # live preview on http://localhost:3000
pnpm run build          # production build in build/ (fails on broken links)
pnpm run serve          # serve the production build locally
```

## Deployments

The same build is published in two places; the look and the content are identical,
only the base path changes.

| Target | Base URL | How |
|---|---|---|
| **Vercel** (public docs) | `/` | Vercel project with *Root Directory* = `website`; settings come from `vercel.json`. Deploys run automatically on push. Optional env var `DOCUSAURUS_URL` sets the canonical domain (otherwise Vercel's production domain is used). |
| **Docker stack** (each customer install) | `/docs/` | `docker/Dockerfile.website` builds with `DOCUSAURUS_BASE_URL=/docs/` and serves the files with nginx (`docker/nginx-website.conf`) behind Caddy. |

Page URLs are `<base URL><page path>`, e.g. `/api-guide/overview` on Vercel and
`https://<domain>/docs/api-guide/overview` in Docker.

Writing rules: [docs/standard/authoring.md](../docs/standard/authoring.md).
