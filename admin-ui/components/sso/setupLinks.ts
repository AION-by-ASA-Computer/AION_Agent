import type { ToastState } from "@/components/PageToast";

type T = (key: string, vars?: Record<string, string | number>) => string;

type LinkEntry = { user_id: string; identifier: string; email: string | null; reason?: string };

/** Outcome of a batch of password-setup emails. The links themselves never reach the admin. */
export type SetupLinks = { sent: LinkEntry[]; failed: LinkEntry[]; missing_email: LinkEntry[] };

const k = "admin_users.migration";

/** Localized text for an email error code, or the code itself. */
export function linkErrorText(t: T, code: string | null | undefined): string {
  if (!code) return "";
  const key = `admin_users.email_errors.${code.split(":")[0]}`;
  const msg = t(key);
  return msg === key ? code : msg;
}

/** One toast summing up who got the email, who didn't and why. */
export function setupLinksToast(t: T, links: SetupLinks | null | undefined): ToastState {
  if (!links) return null;
  const sent = links.sent?.length ?? 0;
  const failed = links.failed ?? [];
  const missing = links.missing_email ?? [];
  if (!failed.length && !missing.length) {
    if (!sent) return null;
    return {
      message: sent === 1 && links.sent[0].email ? t(`${k}.links_sent_one`, { email: links.sent[0].email }) : t(`${k}.links_sent`, { count: sent }),
      variant: "success",
    };
  }
  const parts: string[] = [];
  if (sent) parts.push(t(`${k}.links_sent`, { count: sent }));
  if (failed.length)
    parts.push(
      t(`${k}.links_failed`, {
        names: failed.map((f) => f.identifier).join(", "),
        error: linkErrorText(t, failed[0].reason),
      }),
    );
  if (missing.length) parts.push(t(`${k}.links_missing_email`, { names: missing.map((m) => m.identifier).join(", ") }));
  return { message: parts.join(" "), variant: sent ? "warning" : "error" };
}
