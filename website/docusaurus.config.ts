import {themes as prismThemes} from 'prism-react-renderer';
import type {Config} from '@docusaurus/types';
import type * as Preset from '@docusaurus/preset-classic';

// This runs in Node.js - Don't use client-side code here (browser APIs, JSX...)

// baseUrl env-driven per il deploy multi-tenant (vedi docker/Caddyfile).
//   dev:           DOCUSAURUS_BASE_URL non impostata -> '/'
//   docker prod:   DOCUSAURUS_BASE_URL='/docs/'      -> servito sotto /docs/
// Nota: routeBasePath rimane 'docs' (default) -> in prod gli URL hanno
// prefisso /docs/docs/ (baseUrl + routeBasePath). Per URL piu' puliti
// rimuovere src/pages/index.tsx e impostare docs.routeBasePath='/'.
// In Docker evitiamo baseUrl vuoto (""): darebbe bundle che puntano a /assets/
// e finiscono sul Next chat-ui dietro Caddy. Preferiamo '/' in dev locale.
const _buRaw = (process.env.DOCUSAURUS_BASE_URL ?? '').trim();
const baseUrl = _buRaw === '' ? '/' : (_buRaw.endsWith('/') ? _buRaw : `${_buRaw}/`);

// Quando baseUrl != '/', i footer link con path assoluti (es. /docs/...) non
// si auto-adeguano al doppio prefisso -> evitiamo di fallire il build su questi.
// Per dev (baseUrl=/) lasciamo 'throw' per intercettare regressioni.
const isCustomBaseUrl = baseUrl !== '/';

const config: Config = {
  title: 'AION Agent',
  tagline: 'Technical documentation: architecture, MCP, memory, and client integration.',
  favicon: 'img/favicon.png',

  // Future flags, see https://docusaurus.io/docs/api/docusaurus-config#future
  future: {
    v4: true, // Improve compatibility with the upcoming Docusaurus v4
  },

  // URL pubblico della documentazione (stesso dominio del sito AION se servita dalla root).
  url: process.env.DOCUSAURUS_URL ?? 'https://aion-asa.com',
  baseUrl,

  // GitHub pages deployment config.
  // If you aren't using GitHub pages, you don't need these.
  organizationName: 'aion-asa', // Usually your GitHub org/user name.
  projectName: 'aion-agent-documentation', // Usually your repo name.

  onBrokenLinks: isCustomBaseUrl ? 'warn' : 'throw',

  markdown: {
    mermaid: true,
  },

  themes: ['@docusaurus/theme-mermaid'],

  // Even if you don't use internationalization, you can use this field to set
  // useful metadata like html lang. For example, if your site is Chinese, you
  // may want to replace "en" with "zh-Hans".
  i18n: {
    defaultLocale: 'en',
    locales: ['en'],
  },

  presets: [
    [
      'classic',
      {
        docs: {
          // Markdown sorgente nella cartella `docs/` alla root del repository (non `website/docs`).
          path: '../docs',
          sidebarPath: './sidebars.ts',
          editUrl: undefined,
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
    mermaid: {
      theme: {light: 'neutral', dark: 'dark'},
    },
    navbar: {
      title: 'Documentation',
      logo: {
        alt: 'AION Agent',
        src: 'img/aion-logo-light.png',
        srcDark: 'img/aion-logo-dark.svg',
        height: 32,
        href: baseUrl,
      },
      items: [
        {
          type: 'docSidebar',
          sidebarId: 'tutorialSidebar',
          position: 'left',
          label: 'Guides',
        },
        {
          href: 'https://aion-asa.com',
          label: 'aion-asa.com',
          position: 'right',
        },
        {
          href: 'https://github.com/AION-by-ASA-Computer',
          label: 'GitHub',
          position: 'right',
        },
      ],
    },
    footer: {
      style: 'dark',
      logo: {
        alt: 'AION',
        src: 'img/aion-logo-dark.svg',
        height: 36,
        href: 'https://aion-asa.com',
      },
      links: [
        {
          title: 'Documentation',
          items: [
            {
              label: 'Index',
              to: '/docs/',
            },
          ],
        },
        {
          title: 'Product',
          items: [
            {
              label: 'Chainlit',
              href: 'https://docs.chainlit.io',
            },
            {
              label: 'REST API',
              to: '/docs/api-and-runtime/rest-api',
            },
          ],
        },
        {
          title: 'AION',
          items: [
            {
              label: 'Website',
              href: 'https://aion-asa.com',
            },
            {
              label: 'GitHub Organization',
              href: 'https://github.com/AION-by-ASA-Computer',
            },
          ],
        },
      ],
      copyright: `© ${new Date().getFullYear()} AION · https://aion-asa.com · Technical Documentation - Made with Docusaurus`,
    },
    prism: {
      theme: prismThemes.github,
      darkTheme: prismThemes.dracula,
    },
  } satisfies Preset.ThemeConfig,
};

export default config;
