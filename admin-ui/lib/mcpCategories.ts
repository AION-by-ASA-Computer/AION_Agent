/** Definizioni categorie e mapping per il Marketplace MCP */

export type McpCategory =
  | "all"
  | "official"
  | "productivity"
  | "database"
  | "developer"
  | "observability"
  | "web";

export interface CategoryDef {
  id: McpCategory;
  label: string;
  description: string;
}

export const MCP_CATEGORIES: CategoryDef[] = [
  {
    id: "all",
    label: "All Integrations",
    description: "Explore all available connectors and MCP servers",
  },
  {
    id: "official",
    label: "Official & Verified",
    description: "Certified official connectors with guided setup",
  },
  {
    id: "productivity",
    label: "Productivity & Office",
    description: "Email, Slack, ClickUp, Notion, Google Workspace, Calendars",
  },
  {
    id: "database",
    label: "Database & Storage",
    description: "PostgreSQL, Supabase, Qdrant, SQLite, MySQL, Redis, Vector DBs",
  },
  {
    id: "developer",
    label: "Developer & Cloud",
    description: "GitHub, GitLab, Docker, Filesystem, Terminal, DevOps",
  },
  {
    id: "observability",
    label: "Observability & Logs",
    description: "Prometheus, Sentry, Grafana, Log aggregators, Metrics",
  },
  {
    id: "web",
    label: "Web & Search",
    description: "Brave Search, Fetch, Puppeteer, Scraping, Perplexity",
  },
];

export function categorizeMcp(item: {
  id?: string;
  name?: string;
  title?: string;
  description?: string;
  tags?: string[];
  category?: string;
}): McpCategory {
  if (item.category && item.category !== "all") {
    const cat = item.category.toLowerCase();
    if (
      cat === "productivity" ||
      cat === "database" ||
      cat === "developer" ||
      cat === "observability" ||
      cat === "web"
    ) {
      return cat as McpCategory;
    }
  }

  const text = `${item.id || ""} ${item.name || ""} ${item.title || ""} ${item.description || ""} ${(item.tags || []).join(" ")}`.toLowerCase();

  if (
    text.includes("email") ||
    text.includes("imap") ||
    text.includes("smtp") ||
    text.includes("mail") ||
    text.includes("slack") ||
    text.includes("notion") ||
    text.includes("clickup") ||
    text.includes("calendar") ||
    text.includes("todo") ||
    text.includes("jira") ||
    text.includes("linear") ||
    text.includes("workspace") ||
    text.includes("teams") ||
    text.includes("office")
  ) {
    return "productivity";
  }

  if (
    text.includes("postgres") ||
    text.includes("mysql") ||
    text.includes("sqlite") ||
    text.includes("supabase") ||
    text.includes("qdrant") ||
    text.includes("redis") ||
    text.includes("mongo") ||
    text.includes("database") ||
    text.includes("sql") ||
    text.includes("vector") ||
    text.includes("chroma") ||
    text.includes("pinecone") ||
    text.includes("storage")
  ) {
    return "database";
  }

  if (
    text.includes("github") ||
    text.includes("gitlab") ||
    text.includes("git") ||
    text.includes("docker") ||
    text.includes("file") ||
    text.includes("filesystem") ||
    text.includes("shell") ||
    text.includes("terminal") ||
    text.includes("code") ||
    text.includes("ast") ||
    text.includes("bash") ||
    text.includes("python") ||
    text.includes("node")
  ) {
    return "developer";
  }

  if (
    text.includes("sentry") ||
    text.includes("prometheus") ||
    text.includes("grafana") ||
    text.includes("log") ||
    text.includes("monitor") ||
    text.includes("trace") ||
    text.includes("metrics") ||
    text.includes("datadog") ||
    text.includes("audit")
  ) {
    return "observability";
  }

  if (
    text.includes("search") ||
    text.includes("brave") ||
    text.includes("fetch") ||
    text.includes("scrape") ||
    text.includes("puppeteer") ||
    text.includes("browser") ||
    text.includes("web") ||
    text.includes("crawler") ||
    text.includes("tavily") ||
    text.includes("perplexity")
  ) {
    return "web";
  }

  return "productivity";
}
