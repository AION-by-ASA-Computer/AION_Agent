/**
 * Password policy (client-side checklist only: the backend is authoritative).
 * Mirrors `password_policy_violations` in src/data/user_password.py and
 * admin-ui/lib/passwordPolicy.ts: keep the three in sync.
 */

export const PASSWORD_MIN_LENGTH = 8;
export const PASSWORD_MAX_LENGTH = 512;

export type PasswordRule =
  | "too_short"
  | "too_long"
  | "lowercase"
  | "uppercase"
  | "digit"
  | "symbol"
  | "contains_username";

const RULES: { code: PasswordRule; ok: (pw: string, ident: string) => boolean }[] = [
  { code: "too_short", ok: (pw) => [...pw].length >= PASSWORD_MIN_LENGTH },
  { code: "too_long", ok: (pw) => [...pw].length <= PASSWORD_MAX_LENGTH },
  { code: "lowercase", ok: (pw) => /\p{Ll}/u.test(pw) },
  { code: "uppercase", ok: (pw) => /\p{Lu}/u.test(pw) },
  { code: "digit", ok: (pw) => /\p{Nd}/u.test(pw) },
  { code: "symbol", ok: (pw) => /[^\p{L}\p{N}\s]/u.test(pw) },
  { code: "contains_username", ok: (pw, ident) => ident.length < 3 || !pw.toLowerCase().includes(ident) },
];

/**
 * Stato di ogni regola per la checklist. `too_long` compare solo se violata,
 * `contains_username` solo se l'identificativo ha almeno 3 caratteri.
 */
export function checkPassword(password: string, identifier = ""): { code: PasswordRule; ok: boolean }[] {
  const ident = identifier.trim().toLowerCase();
  return RULES.map((r) => ({ code: r.code, ok: r.ok(password, ident) })).filter(
    (r) => (r.code !== "contains_username" || ident.length >= 3) && (r.code !== "too_long" || !r.ok),
  );
}

export const isPasswordValid = (password: string, identifier = "") =>
  checkPassword(password, identifier).every((r) => r.ok);

/** Estrae i codici `violations` da un 422 `{detail:{code:"password_policy", violations:[...]}}`. */
export function policyViolationsFromDetail(detail: unknown): PasswordRule[] | null {
  if (!detail || typeof detail !== "object" || Array.isArray(detail)) return null;
  const d = detail as { code?: unknown; violations?: unknown };
  if (d.code !== "password_policy") return null;
  return Array.isArray(d.violations) ? d.violations.filter((v): v is PasswordRule => typeof v === "string") : [];
}
