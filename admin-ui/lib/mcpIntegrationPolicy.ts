/** Policy integrazioni MCP (DB) allineata al catalogo Hub. */

export type CredentialMode = "none" | "org_shared" | "per_user";

export type CredentialSchemaField = {
  _id?: string;
  key: string;
  label: string;
  type: "text" | "password" | "oauth";
  required: boolean;
  description?: string;
  env_placeholder?: string;
  registry_env_key?: string;
};

export type CredentialSchemaLoose = Array<{
  _id?: string;
  key: string;
  label: string;
  type?: string;
  required?: boolean;
  description?: string;
}>;

function parseSchemaFieldType(raw?: string): CredentialSchemaField["type"] {
  if (raw === "text" || raw === "password" || raw === "oauth") return raw;
  return "password";
}

/** Normalizza campi da API/DB per l'editor schema credenziali. */
export function normalizeCredentialSchema(
  fields: CredentialSchemaLoose | undefined,
): CredentialSchemaField[] {
  if (!fields?.length) return [];
  const out: CredentialSchemaField[] = [];
  for (let i = 0; i < fields.length; i++) {
    const f = fields[i];
    const key = String(f.key || "").trim();
    if (!key) continue;
    const label = String(f.label || key).trim() || key;
    out.push({
      _id: f._id || `cred_${key}_${i}_${Math.random().toString(36).slice(2, 9)}`,
      key,
      label,
      type: parseSchemaFieldType(f.type),
      required: Boolean(f.required),
      ...(f.description ? { description: f.description } : {}),
    });
  }
  return out;
}

export type IntegrationPolicyRow = {
  server_slug: string;
  display_name?: string;
  is_enabled_for_users: boolean;
  requires_user_credentials: boolean;
  credential_mode: CredentialMode;
  credential_schema: CredentialSchemaLoose;
  suggested_env_yaml?: string;
  oauth_config?: {
    provider?: string;
    authorization_server?: string;
    token_url?: string;
    client_id?: string;
    client_secret?: string;
    scopes?: string[];
    client_id_source?: string;
  };
  aion_connector_id?: string | null;
  user_may_disable?: boolean;
  is_in_registry?: boolean;
};

export function modeLabel(mode: CredentialMode): string {
  switch (mode) {
    case "per_user":
      return "Per utente";
    case "org_shared":
      return "Organizzazione";
    default:
      return "Nessuna";
  }
}

export function policyBadges(policy: IntegrationPolicyRow | undefined): string[] {
  if (!policy) return [];
  const out: string[] = [];
  if (policy.is_enabled_for_users) out.push("Chat");
  if (policy.credential_mode === "per_user") out.push("Per utente");
  else if (policy.credential_mode === "org_shared") out.push("Org");
  const n = policy.credential_schema?.length ?? 0;
  if (n > 0) out.push(`Schema ${n}`);
  return out;
}
