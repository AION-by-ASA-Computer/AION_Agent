import type { Integration } from "@/components/integrations/types";

/** Display name for OAuth buttons — from API (`oauth_display_name` / catalog YAML `title`). */
export function oauthProviderDisplayName(integration: Integration): string {
  return (
    integration.oauth_display_name?.trim() ||
    integration.display_name?.trim() ||
    "OAuth"
  );
}

export function oauthManagedFieldKeys(): Set<string> {
  return new Set(["OAUTH_TOKEN", "OAUTH_REFRESH_TOKEN"]);
}
