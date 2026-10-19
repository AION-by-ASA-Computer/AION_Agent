import { apiBase } from "@/lib/config";

/**
 * Login desktop via browser (PKCE + loopback).
 * L'app desktop apre /login?desktop=1&state=&challenge=&redirect=; a login completato
 * la pagina web chiama POST /auth/desktop/handoff e naviga a `${redirect}?code=&state=`.
 * Le validazioni qui sono solo un controllo di sanita' lato client: il server e' autoritativo.
 */

export type DesktopRequest = { challenge: string; state: string; redirect: string };

export type DesktopHandoffErrorCode =
  | "redirect_not_allowed"
  | "invalid_challenge"
  | "unauthorized"
  | "network"
  | "invalid_response"
  | "generic";

export class DesktopHandoffError extends Error {
  readonly code: DesktopHandoffErrorCode;
  constructor(code: DesktopHandoffErrorCode) {
    super(code);
    this.code = code;
    this.name = "DesktopHandoffError";
  }
}

const STORAGE_KEY = "aion_desktop_login";
const CHALLENGE_RE = /^[A-Za-z0-9_-]{43}$/;
const STATE_RE = /^[A-Za-z0-9_-]{8,256}$/;
const LOOPBACK_HOSTS = new Set(["127.0.0.1", "localhost", "[::1]"]);

export function isValidDesktopRequest(r: Partial<DesktopRequest> | null | undefined): r is DesktopRequest {
  if (!r || typeof r.challenge !== "string" || typeof r.state !== "string" || typeof r.redirect !== "string") {
    return false;
  }
  if (!CHALLENGE_RE.test(r.challenge) || !STATE_RE.test(r.state)) return false;
  try {
    const u = new URL(r.redirect);
    return (
      u.protocol === "http:" &&
      LOOPBACK_HOSTS.has(u.hostname) &&
      u.pathname === "/callback" &&
      !u.username &&
      !u.password &&
      !u.hash
    );
  } catch {
    return false;
  }
}

/** Parsa i parametri dalla query string; ritorna null se non in modalita' desktop o se non validi. */
export function parseDesktopParams(search: string): DesktopRequest | null {
  const p = new URLSearchParams(search);
  if (p.get("desktop") !== "1") return null;
  const req = {
    challenge: p.get("challenge") ?? "",
    state: p.get("state") ?? "",
    redirect: p.get("redirect") ?? "",
  };
  return isValidDesktopRequest(req) ? req : null;
}

export function getPendingDesktop(): DesktopRequest | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<DesktopRequest>;
    return isValidDesktopRequest(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

export function clearPendingDesktop(): void {
  if (typeof window === "undefined") return;
  try {
    sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    /* ignore */
  }
}

/**
 * Legge `?desktop=1&...` dall'URL di /login. Se presente e valido lo salva in sessionStorage
 * (sopravvive al giro SSO) e lo ritorna; se assente ritorna la richiesta gia' pendente (o null).
 * Se `desktop=1` e' presente ma i parametri non sono validi, scarta ogni richiesta pendente.
 */
export function readDesktopParams(): DesktopRequest | null {
  if (typeof window === "undefined") return null;
  const search = window.location.search;
  if (new URLSearchParams(search).get("desktop") === "1") {
    const req = parseDesktopParams(search);
    if (req) {
      try {
        sessionStorage.setItem(STORAGE_KEY, JSON.stringify(req));
      } catch {
        /* ignore */
      }
      return req;
    }
    clearPendingDesktop();
    return null;
  }
  return getPendingDesktop();
}

/** Costruisce `${redirect}?code=...&state=...` senza concatenare stringhe. */
export function buildDesktopTarget(req: DesktopRequest, code: string): string {
  const u = new URL(req.redirect);
  u.searchParams.set("code", code);
  u.searchParams.set("state", req.state);
  return u.toString();
}

/**
 * POST /auth/desktop/handoff con il token appena ottenuto. Ritorna l'URL loopback di destinazione
 * e cancella la richiesta pendente. In caso di errore la richiesta resta pendente (retry possibile).
 */
export async function completeDesktopHandoff(token: string, req?: DesktopRequest | null): Promise<string> {
  const request = req ?? getPendingDesktop();
  if (!request) throw new DesktopHandoffError("generic");
  let res: Response;
  try {
    res = await fetch(`${apiBase()}/auth/desktop/handoff`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({
        challenge: request.challenge,
        state: request.state,
        redirect: request.redirect,
      }),
    });
  } catch {
    throw new DesktopHandoffError("network");
  }
  const j = (await res.json().catch(() => ({}))) as {
    code?: unknown;
    detail?: { code?: string } | string | unknown;
  };
  if (!res.ok) {
    const d = j.detail;
    const c = d && typeof d === "object" && !Array.isArray(d) ? (d as { code?: string }).code : undefined;
    if (c === "redirect_not_allowed" || c === "invalid_challenge") throw new DesktopHandoffError(c);
    if (res.status === 401) throw new DesktopHandoffError("unauthorized");
    throw new DesktopHandoffError("generic");
  }
  if (typeof j.code !== "string" || !j.code) throw new DesktopHandoffError("invalid_response");
  const target = buildDesktopTarget(request, j.code);
  clearPendingDesktop();
  return target;
}
