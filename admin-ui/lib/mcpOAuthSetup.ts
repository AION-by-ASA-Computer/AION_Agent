/** OAuth admin setup hints from connector catalog YAML (`oauth:` block). */

import { apiBase } from "@/lib/api";

export type ConnectorOAuthBlock = {
  client_credentials_required?: boolean;
  setup_doc_url?: string;
  admin_setup_hint?: string;
  scopes?: string[];
};

export type ConnectorOAuthSetupHints = {
  usesOAuth: boolean;
  needsAdminCredentials: boolean;
  title: string;
  docUrl: string | null;
  adminHint: string | null;
  scopes: string[];
};

export function defaultOAuthRedirectUri(): string {
  return `${apiBase()}/v1/integrations/oauth/callback`;
}

export function connectorOAuthSetupHints(
  connector: Record<string, unknown> | null | undefined,
): ConnectorOAuthSetupHints {
  if (!connector) {
    return {
      usesOAuth: false,
      needsAdminCredentials: false,
      title: "Connector",
      docUrl: null,
      adminHint: null,
      scopes: [],
    };
  }
  const oauth = (connector.oauth || {}) as ConnectorOAuthBlock;
  const authType = String(connector.auth_type || "").toLowerCase();
  const needsAdmin = Boolean(oauth.client_credentials_required);
  const usesOAuth = authType === "oauth2" || needsAdmin;
  const docUrl = String(
    oauth.setup_doc_url || connector.official_doc_url || "",
  ).trim();
  const adminHint = String(oauth.admin_setup_hint || "").trim();
  const scopes = Array.isArray(oauth.scopes)
    ? oauth.scopes.map((s) => String(s)).filter(Boolean)
    : [];
  const title = String(connector.title || connector.id || "Connector").trim();
  return {
    usesOAuth,
    needsAdminCredentials: needsAdmin,
    title,
    docUrl: docUrl || null,
    adminHint: adminHint || null,
    scopes,
  };
}
