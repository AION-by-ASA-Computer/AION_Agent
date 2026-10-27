/**
 * Password policy for the admin's own password change.
 * Mirrors `password_policy_violations` in src/data/user_password.py: keep the two in sync.
 */

export const PASSWORD_MIN_LENGTH = 8;
export const PASSWORD_MAX_LENGTH = 512;

export type PasswordRule = "too_short" | "lowercase" | "uppercase" | "digit" | "symbol" | "contains_username";

const RULES: { code: PasswordRule; ok: (pw: string, ident: string) => boolean }[] = [
  { code: "too_short", ok: (pw) => [...pw].length >= PASSWORD_MIN_LENGTH && [...pw].length <= PASSWORD_MAX_LENGTH },
  { code: "lowercase", ok: (pw) => /\p{Ll}/u.test(pw) },
  { code: "uppercase", ok: (pw) => /\p{Lu}/u.test(pw) },
  { code: "digit", ok: (pw) => /\p{Nd}/u.test(pw) },
  { code: "symbol", ok: (pw) => /[^\p{L}\p{N}\s]/u.test(pw) },
  { code: "contains_username", ok: (pw, ident) => ident.length < 3 || !pw.toLowerCase().includes(ident) },
];

export function checkPassword(password: string, identifier = ""): { code: PasswordRule; ok: boolean }[] {
  const ident = identifier.trim().toLowerCase();
  return RULES.filter((r) => r.code !== "contains_username" || ident.length >= 3).map((r) => ({ code: r.code, ok: r.ok(password, ident) }));
}

export const isPasswordValid = (password: string, identifier = "") => checkPassword(password, identifier).every((r) => r.ok);
