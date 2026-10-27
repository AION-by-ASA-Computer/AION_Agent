"use client";

import { Check, Circle, X } from "lucide-react";

import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";
import {
  PASSWORD_MAX_LENGTH,
  PASSWORD_MIN_LENGTH,
  checkPassword,
  type PasswordRule,
} from "@/lib/auth/passwordPolicy";

export function passwordRuleLabel(t: ReturnType<typeof useT>, code: PasswordRule): string {
  return t(`password_policy.rules.${code}`, { min: PASSWORD_MIN_LENGTH, max: PASSWORD_MAX_LENGTH });
}

/** Messaggio per un 422 `password_policy` del backend. */
export function passwordPolicyErrorMessage(t: ReturnType<typeof useT>, violations: PasswordRule[]): string {
  const known = violations.filter((v) => t(`password_policy.rules.${v}`) !== `password_policy.rules.${v}`);
  if (known.length === 0) return t("password_policy.server_error_generic");
  return t("password_policy.server_error", { list: known.map((v) => passwordRuleLabel(t, v)).join(", ") });
}

/**
 * Checklist live della policy password. Le regole non ancora soddisfatte
 * restano neutre finche' il campo e' vuoto, poi diventano rosse.
 */
export function PasswordChecklist({
  password,
  identifier = "",
  id,
  className,
}: {
  password: string;
  identifier?: string;
  id?: string;
  className?: string;
}) {
  const t = useT();
  const rules = checkPassword(password, identifier);
  const touched = password.length > 0;

  return (
    <ul id={id} aria-live="polite" className={cn("grid gap-1 text-xs sm:grid-cols-2", className)}>
      {rules.map((r) => {
        const Icon = r.ok ? Check : touched ? X : Circle;
        return (
          <li
            key={r.code}
            className={cn(
              "flex items-center gap-1.5",
              r.ok ? "text-success" : touched ? "text-destructive" : "text-muted-foreground",
            )}
          >
            <Icon className={cn("shrink-0", r.ok || touched ? "h-3.5 w-3.5" : "h-3 w-3")} aria-hidden />
            <span>
              {passwordRuleLabel(t, r.code)}
              <span className="sr-only"> — {r.ok ? t("password_policy.met") : t("password_policy.not_met")}</span>
            </span>
          </li>
        );
      })}
    </ul>
  );
}
