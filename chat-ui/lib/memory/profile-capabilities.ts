/** Derive chat-ui memory panels from active agent profile MCP / native tools. */

export type ProfileMemorySource = {
  mcp_servers?: string[] | null;
  native_tool_groups?: string[] | null;
};

function normServers(servers?: string[] | null): string[] {
  return (servers ?? []).map((s) => s.trim().toLowerCase()).filter(Boolean);
}

function normGroups(groups?: string[] | null): string[] {
  return (groups ?? []).map((s) => s.trim().toLowerCase()).filter(Boolean);
}

export function hasMnemosTools(profile?: ProfileMemorySource | null): boolean {
  const groups = normGroups(profile?.native_tool_groups);
  return groups.includes("mnemos");
}

/** @deprecated use hasMnemosTools */
export function hasMempalaceMcp(profile?: ProfileMemorySource | null): boolean {
  return hasMnemosTools(profile);
}

export function hasSqlQueryMemory(profile?: ProfileMemorySource | null): boolean {
  const groups = normGroups(profile?.native_tool_groups);
  if (groups.includes("sql_query_memory")) return true;
  const servers = normServers(profile?.mcp_servers);
  return servers.some((s) => {
    if (s === "memory" || s.endsWith("/memory")) return true;
    return (
      s === "query_memory" ||
      s.includes("query_memory") ||
      s === "sql_query_memory" ||
      s.includes("sql_query_memory")
    );
  });
}

export function showProjectMemoryUi(profile?: ProfileMemorySource | null): boolean {
  return hasMnemosTools(profile) || hasSqlQueryMemory(profile);
}
