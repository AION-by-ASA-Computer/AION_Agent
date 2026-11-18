/**
 * Sidebars of the AION documentation site.
 *
 * The docs are split by AUDIENCE, one sidebar per navbar tab, so each reader
 * only sees the pages meant for them:
 *   - startSidebar:     newcomers and chat users (what AION is, quickstart, user guide)
 *   - apiSidebar:       developers integrating AION through the REST API
 *   - adminSidebar:     administrators and operators (install, configure, secure, connect)
 *   - internalsSidebar: people who develop AION itself (architecture, memory, design notes)
 *
 * The sidebar is intentionally decoupled from the folder layout of `docs/`:
 * file paths are referenced by source code and CLAUDE.md, so pages are moved
 * between sections here instead of on disk. Every page in `docs/` should appear
 * in exactly one sidebar (check with `npm run build`: orphan pages still build
 * but are not reachable from the navigation).
 */
import type {SidebarsConfig} from '@docusaurus/plugin-content-docs';

const sidebars: SidebarsConfig = {
  startSidebar: [
    'index',
    {
      type: 'category',
      label: 'Get started',
      collapsed: false,
      items: [
        'getting-started/what-is-aion',
        'getting-started/key-concepts',
        'getting-started/quickstart',
        'getting-started/faq',
      ],
    },
    {
      type: 'category',
      label: 'User guide',
      collapsed: false,
      items: [
        'user-guide/using-the-chat',
        'clients/side-threads',
      ],
    },
  ],

  apiSidebar: [
    {
      type: 'category',
      label: 'API guide',
      collapsed: false,
      items: [
        'api-guide/overview',
        'api-guide/get-an-api-key',
        'api-guide/first-api-call',
        'api-guide/streaming',
        'api-guide/conversations-and-files',
        'api-guide/openai-compatible',
        'api-guide/errors-and-troubleshooting',
      ],
    },
    {
      type: 'category',
      label: 'Integrations',
      collapsed: false,
      items: ['clients/n8n', 'clients/sdk-and-widget', 'security/service-accounts'],
    },
    {
      type: 'category',
      label: 'Reference',
      collapsed: false,
      items: [
        'api-and-runtime/rest-api',
        'api-and-runtime/sse-events',
        'security/api-keys',
        'api-and-runtime/session-charts',
        'api-and-runtime/mcp-integrations-api',
      ],
    },
  ],

  adminSidebar: [
    'admin-guide/checklist',
    'clients/admin-ui',
    {
      type: 'category',
      label: 'Install and update',
      collapsed: false,
      items: [
        'deployment/docker',
        'deployment/migrate-compose-to-ghcr',
        'deployment/self-update',
        'deployment/podman-sandbox',
      ],
    },
    {
      type: 'category',
      label: 'Configuration',
      collapsed: true,
      items: [
        'configuration/environment',
        'configuration/llm-provider-precedence',
        'configuration/profiles',
        'configuration/skills-and-prompts',
        'configuration/soul-memory-user',
        'configuration/web-search-and-fetch',
        'configuration/filesystem-policy-and-promo',
        'configuration/office-and-legacy-word',
        'configuration/document-evidence',
      ],
    },
    {
      type: 'category',
      label: 'Users and security',
      collapsed: true,
      items: [
        'security/identity-and-chat-auth',
        'security/password-setup-email',
        'security/sso-migration',
        'security/two-factor-auth',
        'security/session-isolation',
        'security/pii-review-token',
      ],
    },
    {
      type: 'category',
      label: 'Connectors (MCP)',
      collapsed: true,
      items: [
        'integrations/mcp',
        {
          type: 'category',
          label: 'Custom MCP servers',
          collapsed: false,
          link: {type: 'doc', id: 'mcp/custom-mcp-servers'},
          items: ['mcp/custom-mcp-development'],
        },
        'mcp/registry',
        'mcp/connector-catalog',
        'mcp/hub-wizard',
        'mcp/user-isolation-and-credentials',
        'mcp/smb-files',
        'mcp/microsoft-365',
        'mcp/speech-to-text',
        'mcp/remote-bridge',
        'mcp/promo-render',
        'mcp/orchestration',
        'integrations/deep-research',
      ],
    },
    {
      type: 'category',
      label: 'Messaging channels',
      collapsed: true,
      items: ['integrations/whatsapp', 'telegram/RUNBOOK'],
    },
    {
      type: 'category',
      label: 'Monitoring',
      collapsed: true,
      items: ['architecture/observability', 'benchmarks/agent-smoke-tests'],
    },
  ],

  internalsSidebar: [
    {
      type: 'category',
      label: 'Architecture',
      collapsed: false,
      items: [
        'architecture/overview',
        'architecture/source-tree',
        'api-and-runtime/agent-pipeline',
        'architecture/plan-execution-run-model',
        'architecture/context-offloading',
        'architecture/aion-harness-v2',
        'clients/chat-ui',
      ],
    },
    {
      type: 'category',
      label: 'Memory',
      collapsed: false,
      items: [
        'memory/stm-ltm-and-query',
        'memory/mnemos',
        'memory/mnemos-hardening',
        'memory/context-compaction',
        'memory/chat-history-and-fts',
        'memory/structured-memory',
        'learning/hermes-features',
      ],
    },
    {
      type: 'category',
      label: 'Quality and benchmarks',
      collapsed: true,
      items: [
        'architecture/testing-and-optimization',
        'benchmarks/overview',
        'benchmarks/mnemos-bench',
        'benchmarks/longmemeval-v2',
      ],
    },
    {
      type: 'category',
      label: 'Contributing',
      collapsed: true,
      items: ['opensource/repository-model', 'opensource/releases', 'standard/authoring'],
    },
    {
      type: 'category',
      label: 'Design notes',
      collapsed: true,
      items: [
        'architecture/aion-native-hardening-plan',
        'architecture/agent-deployment-governance',
        'architecture/whatsapp-channel-plan',
        'architecture/aion-vs-longrun-assessment',
        'architecture/long-run-pi-mode',
      ],
    },
  ],
};

export default sidebars;
