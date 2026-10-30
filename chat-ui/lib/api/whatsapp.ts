import { apiBase } from "../config";
import { baseUserHeaders } from "./aion";

export type WhatsAppStatus = {
  channel_enabled: boolean;
  display_phone_number: string | null;
  linked: boolean;
  wa_profile_name: string | null;
  phone_hint: string | null;
  linked_at: string | null;
};

/** One-time link code: the user sends `COLLEGA <code>` to the company number before `expires_at`. */
export type WhatsAppLinkCode = {
  code: string;
  expires_at: string;
  wa_link: string;
  qr_svg: string;
};

/** Error raised by the WhatsApp client; ``code`` mirrors ``detail.code`` when present. */
export class WhatsAppError extends Error {
  code?: string;
  status: number;

  constructor(message: string, status: number, code?: string) {
    super(message);
    this.name = "WhatsAppError";
    this.status = status;
    this.code = code;
  }
}

async function parseError(r: Response): Promise<WhatsAppError> {
  let detail: unknown;
  try {
    detail = ((await r.json()) as { detail?: unknown }).detail;
  } catch {
    /* ignore */
  }
  if (typeof detail === "string") return new WhatsAppError(detail, r.status);
  if (detail && typeof detail === "object" && !Array.isArray(detail)) {
    const obj = detail as Record<string, unknown>;
    const code = typeof obj.code === "string" ? obj.code : undefined;
    const message = typeof obj.message === "string" ? obj.message : code || `HTTP ${r.status}`;
    return new WhatsAppError(message, r.status, code);
  }
  return new WhatsAppError(`HTTP ${r.status}`, r.status);
}

export async function getWhatsAppStatus(userId: string, token?: string | null): Promise<WhatsAppStatus> {
  const r = await fetch(`${apiBase()}/v1/me/whatsapp`, {
    headers: baseUserHeaders(userId, token),
  });
  if (!r.ok) throw await parseError(r);
  return r.json();
}

export async function createWhatsAppLinkCode(
  userId: string,
  token: string | null | undefined,
): Promise<WhatsAppLinkCode> {
  const r = await fetch(`${apiBase()}/v1/me/whatsapp/link-code`, {
    method: "POST",
    headers: baseUserHeaders(userId, token),
  });
  if (!r.ok) throw await parseError(r);
  return r.json();
}

export async function unlinkWhatsApp(userId: string, token: string | null | undefined): Promise<{ ok: boolean }> {
  const r = await fetch(`${apiBase()}/v1/me/whatsapp`, {
    method: "DELETE",
    headers: baseUserHeaders(userId, token),
  });
  if (!r.ok) throw await parseError(r);
  return r.json();
}
