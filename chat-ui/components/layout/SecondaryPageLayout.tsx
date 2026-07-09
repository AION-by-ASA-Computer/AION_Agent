"use client";

import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

type Props = {
  title: string;
  subtitle: string;
  backHref?: string;
  backLabel?: string;
  headerAction?: ReactNode;
  headerIcon?: ReactNode;
  children: ReactNode;
  className?: string;
};

/** Shared shell for chat-ui secondary routes (integrations, schedules, …). */
export function SecondaryPageLayout({
  title,
  subtitle,
  backHref = "/",
  backLabel = "← Chat",
  headerAction,
  headerIcon,
  children,
  className,
}: Props) {
  return (
    <div className={cn("mx-auto max-w-3xl px-4 py-6 text-foreground sm:px-6", className)}>
      <header className="mb-8 rounded-2xl border border-border/60 bg-card/40 p-5 shadow-sm backdrop-blur-xl">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="flex min-w-0 items-start gap-3.5">
            {headerIcon ? (
              <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl border border-primary/20 bg-primary/10 text-primary">
                {headerIcon}
              </div>
            ) : null}
            <div className="min-w-0">
              <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">{title}</h1>
              <p className="mt-1 text-sm leading-relaxed text-muted-foreground">{subtitle}</p>
            </div>
          </div>
          <div className="flex shrink-0 flex-wrap items-center gap-2">
            {headerAction}
            <Link
              href={backHref}
              className="focus-ring inline-flex items-center gap-1.5 rounded-xl border border-border/70 bg-background/60 px-3 py-2 text-sm font-medium text-muted-foreground transition hover:bg-muted hover:text-foreground"
            >
              <ArrowLeft className="h-4 w-4" aria-hidden />
              {backLabel.replace(/^←\s*/, "")}
            </Link>
          </div>
        </div>
      </header>
      {children}
    </div>
  );
}
