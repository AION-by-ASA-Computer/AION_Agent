"use client";

import Link from "next/link";
import type { ReactNode } from "react";

type Props = {
  title: string;
  subtitle: string;
  backHref?: string;
  backLabel?: string;
  headerAction?: ReactNode;
  children: ReactNode;
};

/** Shared shell for chat-ui secondary routes (integrations, schedules, …). */
export function SecondaryPageLayout({
  title,
  subtitle,
  backHref = "/",
  backLabel = "← Chat",
  headerAction,
  children,
}: Props) {
  return (
    <div className="mx-auto max-w-3xl p-6 text-foreground">
      <div className="mb-6 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
          <p className="mt-1 text-sm text-muted-foreground">{subtitle}</p>
        </div>
        <div className="flex shrink-0 items-center gap-3">
          {headerAction}
          <Link
            href={backHref}
            className="focus-ring text-sm text-muted-foreground hover:text-foreground"
          >
            {backLabel}
          </Link>
        </div>
      </div>
      {children}
    </div>
  );
}
