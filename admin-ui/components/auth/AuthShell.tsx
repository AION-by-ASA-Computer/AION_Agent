import type { ReactNode } from "react";
import { AlertCircle, CheckCircle2 } from "lucide-react";

import { cn } from "@/lib/cn";
import { AdminBrand } from "@/components/brand/AdminBrand";

/** Controlli condivisi dalle schermate di accesso (login, 2FA, cambio password, link SSO). */
export const authInputCls =
  "focus-ring w-full rounded-xl border border-border bg-background px-3.5 py-2.5 text-sm text-foreground placeholder:text-muted-foreground transition-colors hover:border-foreground/25 focus:border-foreground/40";

export const authPrimaryBtnCls =
  "focus-ring inline-flex h-10 w-full items-center justify-center gap-2 rounded-xl bg-foreground px-4 text-sm font-semibold text-background transition-[opacity,transform] duration-200 hover:opacity-90 active:scale-[0.99] disabled:cursor-not-allowed disabled:opacity-40 disabled:active:scale-100";

export const authOutlineBtnCls =
  "focus-ring inline-flex h-11 w-full items-center justify-center gap-3 rounded-xl border border-border bg-card px-4 text-sm font-semibold text-foreground transition-colors duration-200 hover:bg-secondary disabled:cursor-not-allowed disabled:opacity-60";

export const authQuietBtnCls =
  "focus-ring inline-flex items-center justify-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium text-muted-foreground transition-colors duration-200 hover:bg-secondary hover:text-foreground disabled:opacity-50";

/**
 * Cornice delle schermate di accesso: logo, superficie card come composer e
 * impostazioni (bordo morbido, card/85, blur) e un unico ingresso animato.
 */
export function AuthShell({
  children,
  footer,
  className,
}: {
  children: ReactNode;
  footer?: ReactNode;
  className?: string;
}) {
  return (
    <div className="relative flex min-h-[100dvh] w-full flex-col items-center justify-center overflow-x-hidden bg-background px-4 py-10 text-foreground sm:py-16">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 top-0 h-[26rem] bg-[radial-gradient(55%_100%_at_50%_0%,hsl(var(--primary)/0.09),transparent)]"
      />
      <div className="auth-enter relative flex w-full max-w-[24rem] flex-col items-center gap-7">
        <AdminBrand className="h-12 max-w-[160px] sm:h-14 sm:max-w-[180px]" />
        <section
          className={cn(
            "w-full rounded-2xl border border-border/70 bg-card/80 p-6 shadow-[0_10px_32px_-16px_hsl(var(--foreground)/0.22)] backdrop-blur-sm sm:p-7",
            className,
          )}
        >
          {children}
        </section>
        {footer}
      </div>
    </div>
  );
}

export function AuthHeading({
  title,
  description,
  icon,
  srOnly = false,
  as: Heading = "h1",
}: {
  title: ReactNode;
  description?: ReactNode;
  icon?: ReactNode;
  srOnly?: boolean;
  as?: "h1" | "h2";
}) {
  if (srOnly) return <Heading className="sr-only">{title}</Heading>;
  return (
    <div className="mb-6 flex flex-col items-center gap-3 text-center">
      {icon ? (
        <div className="flex size-10 items-center justify-center rounded-xl bg-primary/10 text-primary">
          {icon}
        </div>
      ) : null}
      <div className="space-y-1.5">
        <Heading className="text-lg font-semibold tracking-tight text-balance text-foreground">{title}</Heading>
        {description ? (
          <p className="text-sm leading-relaxed text-pretty text-muted-foreground">{description}</p>
        ) : null}
      </div>
    </div>
  );
}

export function AuthAlert({
  tone = "error",
  children,
}: {
  tone?: "error" | "success";
  children: ReactNode;
}) {
  const error = tone === "error";
  const Icon = error ? AlertCircle : CheckCircle2;
  return (
    <div
      role={error ? "alert" : "status"}
      className={cn(
        "flex items-start gap-2 rounded-xl border px-3 py-2.5 text-xs leading-relaxed",
        error
          ? "border-destructive/40 bg-destructive/10 text-destructive dark:text-red-300"
          : "border-success/40 bg-success/10 text-success",
      )}
    >
      <Icon className="mt-px h-4 w-4 shrink-0" aria-hidden />
      <span className="min-w-0 break-words">{children}</span>
    </div>
  );
}

export function AuthDivider({ label }: { label: ReactNode }) {
  return (
    <div className="aion-section-label flex items-center gap-3">
      <span className="h-px flex-1 bg-border/70" aria-hidden />
      {label}
      <span className="h-px flex-1 bg-border/70" aria-hidden />
    </div>
  );
}

/** Logo ufficiale del provider SSO (Microsoft o Google). */
export function SsoProviderIcon({ provider, className = "h-5 w-5" }: { provider: string; className?: string }) {
  if (provider === "microsoft") {
    return (
      <svg className={cn("shrink-0", className)} viewBox="0 0 21 21" fill="none" aria-hidden>
        <path d="M0 0H10V10H0V0Z" fill="#f25022" />
        <path d="M11 0H21V10H11V0Z" fill="#7fba00" />
        <path d="M0 11H10V21H0V11Z" fill="#00a4ef" />
        <path d="M11 11H21V21H11V11Z" fill="#ffb900" />
      </svg>
    );
  }
  if (provider === "google") {
    return (
      <svg className={cn("shrink-0", className)} viewBox="0 0 48 48" aria-hidden>
        <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z" />
        <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z" />
        <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z" />
        <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z" />
      </svg>
    );
  }
  return null;
}
