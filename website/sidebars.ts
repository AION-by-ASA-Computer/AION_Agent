import type {SidebarsConfig} from '@docusaurus/plugin-content-docs';

/**
 * Sidebar ordinata per dominio (allineata alle cartelle in docs/).
 * L’indice principale è docs/index.md (slug /).
 */
const sidebars: SidebarsConfig = {
  tutorialSidebar: [
    'index',
    {
      type: 'category',
      label: 'Introduction',
      collapsed: false,
      items: ['introduction/overview'],
    },
    {
      type: 'category',
      label: 'Architecture',
      collapsed: false,
      items: [
        'architecture/overview',
        'architecture/source-tree',
        // 'architecture/agent-db',  // COMMENTED OUT: Agent DB doc disabled
        'architecture/observability',
        'architecture/testing-and-optimization',
      ],
    },
    {
      type: 'category',
      label: 'Configuration',
      collapsed: false,
      items: [
        'configuration/environment',
        'configuration/filesystem-policy-and-promo',
        'configuration/web-search-and-fetch',
        'configuration/profiles',
        'configuration/skills-and-prompts',
        'configuration/soul-memory-user',
      ],
    },
    {
      type: 'category',
      label: 'Deployment',
      collapsed: false,
      items: ['deployment/docker'],
    },
    {
      type: 'category',
      label: 'API and Runtime',
      collapsed: false,
      items: [
        'api-and-runtime/rest-api',
        'api-and-runtime/mcp-integrations-api',
        'api-and-runtime/agent-pipeline',
        'api-and-runtime/session-charts',
      ],
    },
    {
      type: 'category',
      label: 'Clients',
      collapsed: false,
      items: ['clients/chat-ui', 'clients/admin-ui', 'clients/sdk-and-widget'],
    },
    {
      type: 'category',
      label: 'Memory',
      collapsed: false,
      items: [
        'memory/stm-ltm-and-query',
        'memory/chat-history-and-fts',
        'memory/structured-memory'
      ],
    },
    {
      type: 'category',
      label: 'MCP',
      collapsed: false,
      items: [
        'mcp/registry',
        'mcp/promo-render',
        'mcp/user-isolation-and-credentials',
        'mcp/connector-catalog',
        'mcp/hub-wizard',
        'mcp/orchestration',
      ],
    },
    {
      type: 'category',
      label: 'Security and Identity',
      collapsed: false,
      items: ['security/identity-and-chat-auth'],
    },
    {
      type: 'category',
      label: 'Learning (Hermes)',
      collapsed: false,
      items: ['learning/hermes-features'],
    },
    {
      type: 'category',
      label: 'Integrations',
      collapsed: false,
      items: ['integrations/deep-research'],
    },
    {
      type: 'category',
      label: 'Standards',
      collapsed: true,
      items: ['standard/authoring'],
    },
  ],
};

export default sidebars;
