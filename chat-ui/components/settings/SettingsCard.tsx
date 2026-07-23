import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

export function SettingsCard({
  title,
  description,
  icon,
  children,
  className,
}: {
  title: string;
  description?: string;
  icon?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      className={cn(
        "rounded-2xl border border-border/50 bg-card/45 p-5 shadow-sm backdrop-blur-xl sm:p-6",
        className,
      )}
    >
      <div className="mb-5 border-b border-border/45 pb-4">
        <div className="flex items-center gap-2.5">
          {icon ? <span className="text-primary">{icon}</span> : null}
          <h2 className="text-sm font-semibold text-foreground">{title}</h2>
        </div>
        {description ? (
          <p className="mt-2 text-xs leading-relaxed text-muted-foreground">{description}</p>
        ) : null}
      </div>
      {children}
    </section>
  );
}

export function SettingsFieldRow({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <div className="grid gap-2 border-b border-border/35 py-4 last:border-b-0 sm:grid-cols-[minmax(9rem,11rem)_1fr] sm:items-start sm:gap-6">
      <div className="pt-1">
        <div className="text-xs font-semibold text-foreground">{label}</div>
        {hint ? <p className="mt-1 text-[0.786em] leading-snug text-muted-foreground">{hint}</p> : null}
      </div>
      <div className="min-w-0">{children}</div>
    </div>
  );
}
