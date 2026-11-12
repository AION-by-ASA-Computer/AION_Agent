const ACRONYMS = new Set([
  "IMAP",
  "SMTP",
  "SSL",
  "TLS",
  "API",
  "URL",
  "URI",
  "ID",
  "SSH",
  "HTTP",
  "HTTPS",
  "JSON",
  "SQL",
  "DB",
  "PAT",
  "OAUTH",
  "2FA",
]);

const KNOWN_LABELS: Record<string, string> = {
  IMAP_HOST: "Server Posta in Arrivo (IMAP)",
  IMAP_PORT: "Porta IMAP",
  SMTP_HOST: "Server Posta in Uscita (SMTP)",
  SMTP_PORT: "Porta SMTP",
  EMAIL: "Indirizzo Email",
  EMAIL_ADDRESS: "Indirizzo Email",
  EMAIL_USER: "Nome Utente / Email",
  PASSWORD: "Password / App Password",
  EMAIL_PASSWORD: "Password / App Password",
  APP_PASSWORD: "Password per le App",
  USE_SSL: "Connessione Sicura (SSL/TLS)",
  ENABLE_SSL: "Connessione Sicura (SSL)",
  ENABLE_TLS: "Connessione Sicura (TLS)",
  ENABLE_ATTACHMENT_DOWNLOAD: "Scarica Allegati",
  FOLDER: "Cartella di Posta",
  MAILBOX: "Casella di Posta",
  API_KEY: "Chiave API",
  API_TOKEN: "Token API",
  ACCESS_TOKEN: "Token di Accesso",
  PERSONAL_ACCESS_TOKEN: "Personal Access Token",
  PAT: "Personal Access Token",
  CLIENT_ID: "Client ID",
  CLIENT_SECRET: "Client Secret",
  USERNAME: "Nome Utente",
  USER: "Nome Utente",
};

export function cleanFieldPrefix(key: string): string {
  let cleaned = key;
  const prefixes = ["MCP_EMAIL_SERVER_", "MCP_SERVER_", "MCP_"];
  for (const prefix of prefixes) {
    if (cleaned.startsWith(prefix) && cleaned.length > prefix.length) {
      cleaned = cleaned.slice(prefix.length);
      break;
    }
  }
  return cleaned;
}

export function formatFieldLabel(key: string, rawLabel?: string): string {
  const cleaned = cleanFieldPrefix(key);

  if (KNOWN_LABELS[cleaned]) {
    return KNOWN_LABELS[cleaned];
  }
  if (KNOWN_LABELS[key]) {
    return KNOWN_LABELS[key];
  }

  if (rawLabel && rawLabel.trim() && rawLabel !== key && !rawLabel.includes("_")) {
    return rawLabel.trim();
  }

  const base = (rawLabel || cleaned).trim();
  const words = base.replace(/[\-_]/g, " ").split(/\s+/);

  return words
    .filter(Boolean)
    .map((word) => {
      const upper = word.toUpperCase();
      if (ACRONYMS.has(upper)) {
        return upper;
      }
      return word.charAt(0).toUpperCase() + word.slice(1).toLowerCase();
    })
    .join(" ");
}

export function isBooleanField(field: { key: string; type?: string }): boolean {
  if (field.type === "boolean") return true;
  const cleaned = cleanFieldPrefix(field.key);
  return /^(ENABLE_|USE_|DISABLE_|ALLOW_|REQUIRE_|IS_|AUTO_|DEBUG$)|(_SSL|_TLS|_SECURE|_ENABLED|_DISABLED|_DEBUG)$/i.test(
    cleaned
  );
}

/** Display hints stored by the Integrations dialog for toggle (boolean) credentials. */
export const BOOLEAN_HINT_TRUE = "Attivo";
export const BOOLEAN_HINT_FALSE = "Disattivo";

const BOOLEAN_TRUE_TOKENS = new Set(["attivo", "true", "on", "yes", "1"]);
const BOOLEAN_FALSE_TOKENS = new Set(["disattivo", "false", "off", "no", "0"]);

/**
 * Parse a boolean credential value, default value or display hint.
 *
 * The saved value of a credential is encrypted server-side, so the toggle state
 * is rebuilt from its display hint ("Attivo" / "Disattivo"). Matching is by
 * EXACT token on purpose: a substring check such as `includes("attivo")` also
 * matches "disattivo", which made every saved `false` reload as `true`.
 * Mirrors `parse_boolean_token` in `src/runtime/mcp_integration_helpers.py`.
 *
 * @returns `true`/`false`, or `null` when the input is not boolean-like.
 */
export function parseBooleanToken(raw: unknown): boolean | null {
  if (typeof raw === "boolean") return raw;
  if (raw === null || raw === undefined) return null;
  const token = String(raw).trim().toLowerCase();
  if (BOOLEAN_TRUE_TOKENS.has(token)) return true;
  if (BOOLEAN_FALSE_TOKENS.has(token)) return false;
  return null;
}

export function isSecretField(field: { key: string; type?: string }): boolean {
  if (field.type === "password" || field.type === "oauth") return true;
  const cleaned = cleanFieldPrefix(field.key);
  return /(TOKEN|SECRET|PASSWORD|PASS|API_KEY|APIKEY|ACCESS_KEY|PRIVATE_KEY|CLIENT_SECRET|AUTH|BEARER|OAUTH)/i.test(
    cleaned
  );
}

export function isAdvancedField(field: { key: string; category?: string }): boolean {
  if (field.category === "advanced") return true;
  if (field.category === "basic") return false;
  const cleaned = cleanFieldPrefix(field.key);
  if (
    /^(EMAIL|USER|USERNAME|LOGIN|ACCOUNT|ID|CLIENT_ID|TOKEN|API_KEY|SECRET|PASSWORD|PASS|PAT|ACCESS_TOKEN)$|_EMAIL$|_USERNAME$|_PASSWORD$|_TOKEN$|_API_KEY$|_SECRET$|_PAT$/i.test(
      cleaned
    )
  ) {
    return false;
  }
  return true;
}
