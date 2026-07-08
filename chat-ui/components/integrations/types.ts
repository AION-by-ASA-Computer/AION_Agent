export type CredentialField = {
  key: string;
  label: string;
  type: "text" | "password" | "oauth";
  required: boolean;
  description?: string;
};

export type Integration = {
  server_slug: string;
  display_name: string;
  description?: string;
  icon_url?: string;
  category?: string;
  credential_mode?: "none" | "org_shared" | "per_user";
  org_managed?: boolean;
  requires_user_credentials: boolean;
  credential_schema: CredentialField[];
  has_oauth: boolean;
  is_remote_bridge?: boolean;
  remote_url?: string;
  oauth_provider?: string;
  oauth_authorization_server?: string;
  oauth_client_id?: string;
  oauth_scopes?: string[];
  is_configured: boolean;
  user_enabled?: boolean;
  can_disable?: boolean;
  credentials_hints: Array<{
    key: string;
    display_hint?: string;
    is_expired: boolean;
    updated_at?: string;
  }>;
};
