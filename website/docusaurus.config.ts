/**
 * Docusaurus configuration of the AION Agents documentation site.
 *
 * The Markdown sources live in the repository-level `docs/` folder (single
 * source of truth); this `website/` folder only holds the site shell.
 * The same build is published in two ways:
 *   - Vercel (public documentation): served from the domain root, baseUrl '/'.
 *   - Docker stack (per-customer install): served under https://<domain>/docs/,
 *     built with DOCUSAURUS_BASE_URL=/docs/ (see docker/Dockerfile.website,
 *     docker/nginx-website.conf and docker/Caddyfile).
 *
 * Docs are mounted at the site root (routeBasePath '/'), so page URLs are
 * `<baseUrl><page>`, e.g. `/api-guide/overview` on Vercel and
 * `/docs/api-guide/overview` in Docker. There is no separate landing page:
 * `docs/index.md` (slug '/') is the home page.
 *
 * This file runs in Node.js at build time: no browser APIs here.
 */
import path from 'node:path';
import {themes as prismThemes} from 'prism-react-renderer';
import type {Config} from '@docusaurus/types';
import type * as Preset from '@docusaurus/preset-classic';
import repoLinks from './src/remark/repo-links';

const GITHUB_REPO = 'https://github.com/AION-by-ASA-Computer/AION_Agent';

// baseUrl comes from the environment so one codebase serves both targets.
// An empty value is normalized to '/': in Docker an empty baseUrl would make
// bundles point to /assets/, which Caddy routes to the chat-ui instead.
const _buRaw = (process.env.DOCUSAURUS_BASE_URL ?? '').trim();
const baseUrl = _buRaw === '' ? '/' : _buRaw.endsWith('/') ? _buRaw : `${_buRaw}/`;

// Public origin of the site (used for canonical URLs and the sitemap).
// DOCUSAURUS_URL wins; on Vercel fall back to the production domain Vercel
// exposes at build time; otherwise the AION website.
const siteUrl =
  process.env.DOCUSAURUS_URL ??
  (process.env.VERCEL_PROJECT_PRODUCTION_URL
    ? `https://${process.env.VERCEL_PROJECT_PRODUCTION_URL}`
    : 'https://aion-asa.com');

const config: Config = {
  title: 'AION Agents',
  tagline: 'Documentation for users, administrators and developers of AION Agents.',
  favicon: 'img/favicon.png',

  future: {
    v4: true, // Improve compatibility with the upcoming Docusaurus v4
  },

  url: siteUrl,
  baseUrl,
  organizationName: 'AION-by-ASA-Computer',
  projectName: 'AION_Agent',

  // Broken internal links fail the build, so a broken page never reaches
  // Vercel. Links to repository files are turned into GitHub links by
  // src/remark/repo-links.ts, so they don't count as broken.
  onBrokenLinks: 'throw',
  onBrokenAnchors: 'warn',

  markdown: {
    mermaid: true,
    // `future.v4` turns these MDX v1 conveniences off by default; the docs use
    // them: explicit heading ids (`## Title {#old-anchor}`) keep old anchors
    // working after translations, and admonition titles are written as
    // `:::warning Title`. HTML comments are allowed too.
    mdx1Compat: {headingIds: true, admonitions: true, comments: true},
    hooks: {
      onBrokenMarkdownLinks: 'throw',
    },
  },

  themes: [
    '@docusaurus/theme-mermaid',
    [
      // Offline full-text search: the index is built at build time, so it works
      // the same on Vercel, in Docker and air-gapped installs (no Algolia).
      require.resolve('@easyops-cn/docusaurus-search-local'),
      {
        hashed: true,
        indexBlog: false,
        // The Markdown lives in the repository-level docs/ folder, not website/docs.
        docsDir: '../docs',
        docsRouteBasePath: '/',
        language: ['en'],
        highlightSearchTermsOnTargetPage: true,
        explicitSearchResultPath: true,
        searchResultLimits: 10,
      },
    ],
  ],

  i18n: {
    defaultLocale: 'en',
    locales: ['en'],
  },

  presets: [
    [
      'classic',
      {
        docs: {
          // Markdown sources are in the repository-level docs/ folder.
          path: '../docs',
          routeBasePath: '/',
          sidebarPath: './sidebars.ts',
          // "Edit this page" opens the source file on GitHub.
          editUrl: ({docPath}) => `${GITHUB_REPO}/edit/main/docs/${docPath}`,
          remarkPlugins: [
            [repoLinks, {repoRoot: path.resolve(__dirname, '..'), githubBase: GITHUB_REPO, branch: 'main'}],
          ],
        },
        blog: false,
        theme: {
          customCss: './src/css/custom.css',
        },
      } satisfies Preset.Options,
    ],
  ],

  themeConfig: {
    image: 'img/aion-logo-light.png',
    colorMode: {
      defaultMode: 'dark',
      respectPrefersColorScheme: true,
      disableSwitch: false,
    },
    docs: {
      sidebar: {
        hideable: true,
        autoCollapseCategories: false,
      },
    },
    tableOfContents: {
      minHeadingLevel: 2,
      maxHeadingLevel: 3,
    },
    mermaid: {
      theme: {light: 'neutral', dark: 'dark'},
    },
    navbar: {
      // No text title: the AION logo alone is the link to the home page.
      hideOnScroll: false,
      logo: {
        alt: 'AION',
        src: 'img/aion-logo-light.png',
        srcDark: 'img/aion-logo-dark.svg',
        height: 32,
      },
      // One tab per audience; each tab opens its own sidebar (see sidebars.ts).
      items: [
        {type: 'docSidebar', sidebarId: 'startSidebar', position: 'left', label: 'Get started'},
        {type: 'docSidebar', sidebarId: 'apiSidebar', position: 'left', label: 'API'},
        {type: 'docSidebar', sidebarId: 'adminSidebar', position: 'left', label: 'Administration'},
        {type: 'docSidebar', sidebarId: 'internalsSidebar', position: 'left', label: 'Internals'},
        {href: 'https://aion-asa.com', label: 'aion-asa.com', position: 'right'},
        {href: GITHUB_REPO, label: 'GitHub', position: 'right'},
      ],
    },
    // Footer follows the page theme (light/dark), styled in src/css/custom.css.
    footer: {
      style: 'light',
      logo: {
        alt: 'AION',
        src: 'img/aion-logo-light.png',
        srcDark: 'img/aion-logo-dark.svg',
        height: 26,
        href: 'https://aion-asa.com',
      },
      links: [
        {
          title: 'Get started',
          items: [
            {label: 'What is AION', to: '/getting-started/what-is-aion'},
            {label: 'Quickstart', to: '/getting-started/quickstart'},
            {label: 'Using the chat', to: '/user-guide/using-the-chat'},
            {label: 'FAQ', to: '/getting-started/faq'},
          ],
        },
        {
          title: 'Developers',
          items: [
            {label: 'API overview', to: '/api-guide/overview'},
            {label: 'Get an API key', to: '/api-guide/get-an-api-key'},
            {label: 'REST API reference', to: '/api-and-runtime/rest-api'},
          ],
        },
        {
          title: 'Administrators',
          items: [
            {label: 'Administrator checklist', to: '/admin-guide/checklist'},
            {label: 'Deploy with Docker', to: '/deployment/docker'},
            {label: 'Connectors (MCP)', to: '/integrations/mcp'},
          ],
        },
        {
          title: 'AION',
          items: [
            {label: 'Website', href: 'https://aion-asa.com'},
            {label: 'GitHub', href: GITHUB_REPO},
            {label: 'Releases', href: `${GITHUB_REPO}/releases`},
          ],
        },
      ],
      copyright: `© ${new Date().getFullYear()} AION · ASA Computer · Documentation for AION Agents`,
    },
    prism: {
      theme: prismThemes.github,
      darkTheme: prismThemes.dracula,
      additionalLanguages: ['bash', 'powershell', 'json', 'yaml', 'python', 'http'],
    },
  } satisfies Preset.ThemeConfig,
};

export default config;
