import { apiBase } from "../config";
import { baseUserHeaders } from "./aion";

export type TelegramLink = {
  tg_user_id: number;
  tg_username: string | null;
  tg_first_name: string | null;
  linked_at: string | null;
  last_seen_at: string | null;
};

export type TelegramStatus = {
  /** Integrazione attiva sul server (Admin → Telegram → Attiva). */
  enabled: boolean;
  /** Bot manager connesso a Telegram: senza, non si possono generare link. */
  available: boolean;
  bot_username: string | null;
  pairing_ttl_min: number;
  /** Chat sul bot manager attiva (Admin → Telegram); di default si chatta con gli assistenti. */
  manager_chat?: boolean;
  link: TelegramLink | null;
};

/** Link monouso di collegamento: `url` apre il bot con `/start pair_<code>`. */
export type TelegramPairingLink = {
  url: string;
  bot_username: string;
  expires_at: string;
  qr_svg: string | null;
};

/** Error raised by the Telegram client; ``code`` mirrors ``detail.code`` when present. */
export class TelegramApiError extends Error {
  code?: string;
  status: number;

  constructor(message: string, status: number, code?: string) {
    super(message);
    this.name = "TelegramApiError";
    this.status = status;
    this.code = code;
  }
}

async function parseError(r: Response): Promise<TelegramApiError> {
  let detail: unknown;
  try {
    detail = ((await r.json()) as { detail?: unknown }).detail;
  } catch {
    /* ignore */
  }
  if (typeof detail === "string") return new TelegramApiError(detail, r.status);
  if (detail && typeof detail === "object") {
    const obj = detail as Record<string, unknown>;
    const code = typeof obj.code === "string" ? obj.code : undefined;
    const message = typeof obj.message === "string" ? obj.message : code || `HTTP ${r.status}`;
    return new TelegramApiError(message, r.status, code);
  }
  return new TelegramApiError(`HTTP ${r.status}`, r.status);
}

export async function getTelegramStatus(userId: string, token?: string | null): Promise<TelegramStatus> {
  const r = await fetch(`${apiBase()}/v1/me/telegram`, {
    headers: baseUserHeaders(userId, token),
    cache: "no-store",
  });
  if (!r.ok) throw await parseError(r);
  return r.json();
}

export async function createTelegramLink(userId: string, token?: string | null): Promise<TelegramPairingLink> {
  const r = await fetch(`${apiBase()}/v1/me/telegram/link`, {
    method: "POST",
    headers: baseUserHeaders(userId, token),
  });
  if (!r.ok) throw await parseError(r);
  return r.json();
}

export async function unlinkTelegram(userId: string, token?: string | null): Promise<void> {
  const r = await fetch(`${apiBase()}/v1/me/telegram/link`, {
    method: "DELETE",
    headers: baseUserHeaders(userId, token),
  });
  if (!r.ok) throw await parseError(r);
}

export type TelegramBotStatus = "provisioning" | "active" | "suspended" | "error";

/** Personal assistant created from the manager bot with /newbot. */
export type TelegramBot = {
  id: number;
  username: string | null;
  name: string | null;
  status: TelegramBotStatus;
  /** personal: only the owner; shared: every linked AION user, also in groups. */
  mode: "personal" | "shared";
  profile_slug: string | null;
  profile_name: string | null;
  project_slug: string | null;
  /** t.me link, only when the assistant is active. */
  url: string | null;
  created_at: string | null;
};

export async function listTelegramBots(userId: string, token?: string | null): Promise<TelegramBot[]> {
  const r = await fetch(`${apiBase()}/v1/me/telegram/bots`, {
    headers: baseUserHeaders(userId, token),
    cache: "no-store",
  });
  if (!r.ok) throw await parseError(r);
  return ((await r.json()) as { data: TelegramBot[] }).data;
}
