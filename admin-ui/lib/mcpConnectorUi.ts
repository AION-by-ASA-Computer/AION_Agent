/** Helper per form credenziali MCP guidato dal catalogo connettori (YAML). */

export type CredentialFieldDef = {
  key: string;
  label: string;
  secret: boolean;
  required: boolean;
};

function guessSecretFromKey(key: string): boolean {
  return /TOKEN|SECRET|PASSWORD|PRIVATE|API_KEY|REFRESH|CREDENTIAL/i.test(key);
}

function humanizeEnvKey(key: string): string {
  return key
    .split("_")
    .map((w) => (w ? w.charAt(0) + w.slice(1).toLowerCase() : ""))
    .join(" ");
}

export function buildCredentialFields(c: Record<string, unknown> | null | undefined): CredentialFieldDef[] {
  if (!c) return [];
  const raw = c.credential_fields;
  if (Array.isArray(raw) && raw.length) {
    return raw
      .map((row: Record<string, unknown>) => ({
        key: String(row.key ?? ""),
        label: String(row.label ?? row.label_it ?? row.key ?? ""),
        secret: Boolean(row.secret),
        required: Object.prototype.hasOwnProperty.call(row, "required") ? Boolean(row.required) : true,
      }))
      .filter((f) => f.key);
  }
  const req = (c.required_env as string[]) || [];
  const opt = (c.optional_env as string[]) || [];
  return [
    ...req.map((key) => ({
      key,
      label: humanizeEnvKey(key),
      secret: guessSecretFromKey(key),
      required: true as const,
    })),
    ...opt.map((key) => ({
      key,
      label: humanizeEnvKey(key),
      secret: guessSecretFromKey(key),
      required: false as const,
    })),
  ];
}

/** Allinea la riga catalogo al server installato (metadata o match su nome). */
export function matchConnectorRow(
  registryName: string,
  aionConnectorId: string | undefined,
  rows: Record<string, unknown>[],
): Record<string, unknown> | null {
  if (aionConnectorId) {
    const hit = rows.find((r) => r.id === aionConnectorId);
    if (hit) return hit;
  }
  const n = registryName.toLowerCase().replace(/_/g, "-");
  let best: Record<string, unknown> | null = null;
  let bestLen = 0;
  for (const r of rows) {
    const hintsRaw = r.mcp_name_hints as string[] | undefined;
    const hints: string[] =
      Array.isArray(hintsRaw) && hintsRaw.length
        ? hintsRaw.map((h) => String(h).toLowerCase().replace(/_/g, "-"))
        : r.id
          ? [String(r.id).toLowerCase().replace(/_/g, "-")]
          : [];
    for (const h of hints) {
      if (h.length >= 3 && n.includes(h) && h.length > bestLen) {
        bestLen = h.length;
        best = r;
      }
    }
  }
  return best;
}

export function extraEnvJson(
  env: Record<string, string> | undefined,
  knownKeys: Set<string>,
): string {
  const o: Record<string, string> = {};
  for (const [k, v] of Object.entries(env || {})) {
    if (!knownKeys.has(k)) o[k] = v ?? "";
  }
  return JSON.stringify(o, null, 2);
}
