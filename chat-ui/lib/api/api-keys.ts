import { apiBase } from "../config";
import { baseUserHeaders, jsonHeaders } from "./aion";

export type ApiKeyStatus = "active" | "expired" | "revoked";

export type ApiKeyItem = {
  id: string;
  name: string;
  prefix: string;
  scopes: string[];
  created_at: string;
  expires_at: string | null;
  last_used_at: string | null;
  revoked_at: string | null;
  status: ApiKeyStatus;
};

export type ApiKeyPolicy = {
  enabled: boolean;
  max_keys: number;
  active_count: number;
  max_ttl_days: number;
  allowed_scopes: string[];
};

export type ApiKeysResponse = {
  policy: ApiKeyPolicy;
  keys: ApiKeyItem[];
};

/** Returned only by the create call: includes the full secret, shown once. */
export type CreatedApiKey = ApiKeyItem & { key: string };

export type CreateApiKeyBody = {
  name: string;
  scopes: string[];
  expires_in_days: number;
};

/** Error raised by the API key client; ``code`` mirrors ``detail.code`` when present. */
export class ApiKeyError extends Error {
  code?: string;
  status: number;
  details?: Record<string, unknown>;

  constructor(message: string, status: number, code?: string, details?: Record<string, unknown>) {
    super(message);
    this.name = "ApiKeyError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

async function parseError(r: Response): Promise<ApiKeyError> {
  let detail: unknown;
  try {
    detail = ((await r.json()) as { detail?: unknown }).detail;
  } catch {
    /* ignore */
  }
  if (typeof detail === "string") return new ApiKeyError(detail, r.status);
  if (Array.isArray(detail)) {
    // Pydantic validation errors: [{loc, msg, type}, ...]
    const msg = detail
      .map((d) => (d && typeof d === "object" && "msg" in d ? String((d as { msg: unknown }).msg) : ""))
      .filter(Boolean)
      .join("; ");
    return new ApiKeyError(msg || `HTTP ${r.status}`, r.status, "validation_error");
  }
  if (detail && typeof detail === "object") {
    const obj = detail as Record<string, unknown>;
    const code = typeof obj.code === "string" ? obj.code : undefined;
    const message = typeof obj.message === "string" ? obj.message : code || `HTTP ${r.status}`;
    return new ApiKeyError(message, r.status, code, obj);
  }
  return new ApiKeyError(`HTTP ${r.status}`, r.status);
}

export async function listApiKeys(userId: string, token?: string | null): Promise<ApiKeysResponse> {
  const r = await fetch(`${apiBase()}/v1/me/api-keys`, {
    headers: baseUserHeaders(userId, token),
  });
  if (!r.ok) throw await parseError(r);
  return r.json();
}

export async function createApiKey(
  userId: string,
  token: string | null | undefined,
  body: CreateApiKeyBody,
): Promise<CreatedApiKey> {
  const r = await fetch(`${apiBase()}/v1/me/api-keys`, {
    method: "POST",
    headers: jsonHeaders(userId, token),
    body: JSON.stringify(body),
  });
  if (!r.ok) throw await parseError(r);
  return r.json();
}

export async function revokeApiKey(
  userId: string,
  token: string | null | undefined,
  keyId: string,
): Promise<ApiKeyItem> {
  const r = await fetch(`${apiBase()}/v1/me/api-keys/${encodeURIComponent(keyId)}`, {
    method: "DELETE",
    headers: baseUserHeaders(userId, token),
  });
  if (!r.ok) throw await parseError(r);
  return r.json();
}
