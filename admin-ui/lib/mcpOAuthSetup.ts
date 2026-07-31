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

type OAuthConfigLike = {
  client_id?: string;
  client_secret?: string;
  authorization_server?: string;
  token_url?: string;
  client_credentials_required?: boolean;
};

/** True se l'admin deve registrare client_id/secret (GitHub, SharePoint, Gmail, …). */
export function oauthAdminClientCredentialsRequired(
  oauthConfig: OAuthConfigLike | undefined,
  connector?: Record<string, unknown> | null,
): boolean {
  if (oauthConfig?.client_credentials_required) return true;
  const hints = connectorOAuthSetupHints(connector);
  if (hints.needsAdminCredentials) return true;
  const authRef = String(oauthConfig?.authorization_server || oauthConfig?.token_url || "").toLowerCase();
  return authRef.includes("login.microsoftonline.com");
}

/** False se mancano client_id o client_secret richiesti dall'admin. */
export function oauthAdminCredentialsConfigured(
  oauthConfig: OAuthConfigLike | undefined,
  connector?: Record<string, unknown> | null,
): boolean {
  if (!oauthAdminClientCredentialsRequired(oauthConfig, connector)) return true;
  const clientId = String(oauthConfig?.client_id || "").trim();
  const clientSecret = String(oauthConfig?.client_secret || "").trim();
  return Boolean(clientId && clientSecret);
}

export function oauthAdminSetupPending(
  oauthConfig: OAuthConfigLike | undefined,
  connector?: Record<string, unknown> | null,
  config?: { type?: string },
): boolean {
  const hints = connectorOAuthSetupHints(connector);
  const usesOAuth =
    hints.usesOAuth ||
    config?.type === "remote-bridge" ||
    Boolean(oauthConfig?.authorization_server || oauthConfig?.token_url);
  if (!usesOAuth) return false;
  return !oauthAdminCredentialsConfigured(oauthConfig, connector);
}
