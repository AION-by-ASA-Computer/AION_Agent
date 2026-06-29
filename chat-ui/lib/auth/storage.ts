const TOKEN = "aion_chat_token";
const USER = "aion_chat_user_id";
const SKIP = "aion_chat_change_pw_skipped_until";

export function getStoredToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN);
}

export function setStoredAuth(token: string | null, userId: string | null) {
  if (typeof window === "undefined") return;
  if (token) localStorage.setItem(TOKEN, token);
  else localStorage.removeItem(TOKEN);
  if (userId) localStorage.setItem(USER, userId);
  else localStorage.removeItem(USER);
}

export function getStoredUserId(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(USER);
}

export function setChangePwSkipUntil(ts: number) {
  if (typeof window === "undefined") return;
  localStorage.setItem(SKIP, String(ts));
}

export function isChangePwSkipped(now: number = Date.now()): boolean {
  if (typeof window === "undefined") return false;
  const v = localStorage.getItem(SKIP);
  if (!v) return false;
  const n = Number(v);
  return Number.isFinite(n) && n > now;
}
