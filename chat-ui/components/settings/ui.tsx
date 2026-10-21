"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { CheckCircle2, Info, Loader2, Save, TriangleAlert, X, XCircle } from "lucide-react";

import { cn } from "@/lib/cn";

/*
 * Settings vocabulary shared with admin-ui (`admin-ui/components/settings/ui.tsx`).
 * Everything here renders inside `.settings-scope`, which re-bases Tailwind sizes to admin's scale.
 */

export const inputCls =
  "focus-ring w-full rounded-xl border border-border bg-background px-3.5 py-2.5 text-sm text-foreground placeholder:text-muted-foreground/70 transition-colors hover:border-foreground/25 focus:border-foreground/40 disabled:cursor-not-allowed disabled:opacity-60";
export const ghostBtn =
  "focus-ring inline-flex h-9 items-center gap-2 rounded-xl px-3 text-sm font-medium text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground disabled:opacity-50";
export const outlineBtn =
  "focus-ring inline-flex h-9 items-center gap-2 rounded-xl border border-border bg-card px-3 text-sm font-medium transition-colors hover:bg-secondary disabled:opacity-60";
export const solidBtn =
  "focus-ring inline-flex h-9 items-center gap-2 rounded-xl bg-foreground px-3.5 text-sm font-semibold text-background transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40";
export const dangerBtn =
  "focus-ring inline-flex h-9 items-center gap-2 rounded-xl bg-destructive px-3.5 text-sm font-semibold text-destructive-foreground transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40";
export const iconBtn =
  "focus-ring inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground disabled:opacity-50";

/** Heading of one settings section. */
export function SectionHead({ title, description, action }: { title: string; description?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-end gap-x-4 gap-y-3 pb-1">
      <div className="min-w-0 flex-1">
        <h2 className="text-balance text-xl font-semibold tracking-[-0.02em]">{title}</h2>
        {description && <p className="mt-1 max-w-[62ch] text-sm text-muted-foreground">{description}</p>}
      </div>
      {action}
    </div>
  );
}

/** Bordered block that groups related settings; its body is rows or a field grid. */
export function Group({
  title,
  description,
  action,
  footer,
  tone,
  children,
}: {
  title?: string;
  description?: ReactNode;
  action?: ReactNode;
  footer?: ReactNode;
  tone?: "warn";
  children?: ReactNode;
}) {
  return (
    <section
      className={cn(
        "overflow-hidden rounded-2xl border bg-card/60",
        tone === "warn" ? "border-warning/40" : "border-border",
      )}
    >
      {title && (
        <header
          className={cn(
            "flex flex-wrap items-start gap-x-4 gap-y-2 px-5 py-3.5",
            tone === "warn" ? "bg-warning/10" : "bg-secondary/60",
          )}
        >
          <div className="min-w-0 flex-1">
            <h3 className="text-[1.0714rem] font-semibold tracking-[-0.01em]">{title}</h3>
            {description && <p className="mt-0.5 text-xs text-muted-foreground">{description}</p>}
          </div>
          {action}
        </header>
      )}
      {children && <div className={cn(title && "border-t border-border")}>{children}</div>}
      {footer && (
        <div className="flex flex-wrap items-center justify-end gap-2 border-t border-border/60 px-5 py-3.5">{footer}</div>
      )}
    </section>
  );
}

export function FieldGrid({ children }: { children: ReactNode }) {
  return <div className="grid gap-x-5 gap-y-4 px-5 py-5 md:grid-cols-2">{children}</div>;
}

/** Label + control + hint. The label wraps the control, so clicking it focuses the field. */
export function Field({
  label,
  hint,
  wide,
  aside,
  children,
}: {
  label: string;
  hint?: ReactNode;
  wide?: boolean;
  /** Right-aligned extra on the hint line, e.g. a character counter. */
  aside?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className={cn("flex min-w-0 flex-col gap-1.5", wide && "md:col-span-2")}>
      <label className="flex flex-col gap-1.5">
        <span className="text-sm font-medium">{label}</span>
        {children}
      </label>
      {(hint || aside) && (
        <div className="flex items-start gap-3 text-xs text-muted-foreground">
          <p className="min-w-0 flex-1">{hint}</p>
          {aside}
        </div>
      )}
    </div>
  );
}

export function Switch({
  checked,
  onChange,
  label,
  disabled,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cn(
        "focus-ring relative inline-flex h-6 w-10 shrink-0 items-center rounded-full border transition-colors disabled:opacity-50",
        checked ? "border-transparent bg-foreground" : "border-border bg-secondary",
      )}
    >
      <span
        className={cn(
          "block h-4 w-4 rounded-full transition-transform duration-200 ease-out",
          checked ? "translate-x-4.75 bg-background" : "translate-x-0.75 bg-muted-foreground",
        )}
      />
    </button>
  );
}

/** One setting in a divided list: label and description on the left, its control on the right. */
export function Row({
  label,
  description,
  children,
  stack,
}: {
  label: ReactNode;
  description?: ReactNode;
  children: ReactNode;
  /** Put the control under the label on every width (wide controls such as sliders). */
  stack?: boolean;
}) {
  return (
    <li
      className={cn(
        "flex gap-x-6 gap-y-3 px-5 py-4",
        stack ? "flex-col" : "flex-col sm:flex-row sm:items-center",
      )}
    >
      <div className="min-w-0 flex-1">
        <div className="text-sm font-medium">{label}</div>
        {description && <p className="mt-0.5 text-xs text-muted-foreground">{description}</p>}
      </div>
      <div className={cn("min-w-0", !stack && "sm:shrink-0")}>{children}</div>
    </li>
  );
}

export function RowList({ children }: { children: ReactNode }) {
  return <ul className="divide-y divide-border/40">{children}</ul>;
}

/** Two to four mutually exclusive options shown side by side. */
export function Segmented<V extends string>({
  value,
  onChange,
  options,
  label,
  className,
}: {
  value: V;
  onChange: (v: V) => void;
  options: { value: V; label: string; icon?: ReactNode }[];
  label: string;
  className?: string;
}) {
  return (
    <div role="radiogroup" aria-label={label} className={cn("inline-flex gap-1 rounded-xl border border-border bg-secondary/60 p-1", className)}>
      {options.map((o) => {
        const on = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={on}
            onClick={() => onChange(o.value)}
            className={cn(
              "focus-ring inline-flex h-8 flex-1 items-center justify-center gap-2 whitespace-nowrap rounded-lg px-3 text-sm transition-colors",
              on
                ? "bg-background font-medium text-foreground shadow-[0_1px_2px_rgba(0,0,0,0.12)]"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {o.icon}
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

export function Note({ tone = "info", children }: { tone?: "info" | "warn" | "error"; children: ReactNode }) {
  const Icon = tone === "info" ? Info : TriangleAlert;
  return (
    <div
      className={cn(
        "flex items-start gap-2.5 rounded-xl px-3.5 py-3 text-sm",
        tone === "error" ? "bg-destructive/10 text-destructive" : "bg-secondary/60 text-muted-foreground",
      )}
      role={tone === "info" ? undefined : "alert"}
    >
      <Icon className={cn("mt-0.5 h-4 w-4 shrink-0", tone === "warn" && "text-warning")} aria-hidden />
      <div className="min-w-0 flex-1 leading-relaxed">{children}</div>
    </div>
  );
}

export function Mono({ children, className }: { children: ReactNode; className?: string }) {
  return <span className={cn("font-mono text-[0.893em] text-foreground/80", className)}>{children}</span>;
}

/** Small status chip; `tone` picks the colour, never decoration. */
export function Badge({ tone = "neutral", children }: { tone?: "neutral" | "success" | "warning" | "danger"; children: ReactNode }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md px-1.5 py-0.5 text-xs font-medium",
        tone === "success" && "bg-success/12 text-success",
        tone === "warning" && "bg-warning/12 text-warning",
        tone === "danger" && "bg-destructive/12 text-destructive",
        tone === "neutral" && "bg-secondary text-muted-foreground",
      )}
    >
      {children}
    </span>
  );
}

/** Modal on the native <dialog>: focus trap, Escape and inert background come from the browser. */
export function Dialog({
  title,
  description,
  closeLabel,
  onClose,
  children,
  className,
}: {
  title: string;
  description?: string;
  closeLabel: string;
  onClose: () => void;
  children: ReactNode;
  className?: string;
}) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (el && !el.open) el.showModal();
  }, []);

  return (
    <dialog
      ref={ref}
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
      onClick={(e) => {
        if (e.target === ref.current) onClose();
      }}
      className={cn(
        "m-auto max-h-[calc(100dvh-2rem)] w-[calc(100%-2rem)] max-w-lg overflow-y-auto rounded-3xl border border-border bg-card p-0 text-foreground shadow-[0_24px_60px_-20px_rgba(0,0,0,0.45)] backdrop:bg-black/55",
        className,
      )}
    >
      <div className="flex items-start gap-4 px-6 pb-2 pt-6">
        <div className="min-w-0 flex-1">
          <h2 className="text-balance text-lg font-semibold tracking-[-0.015em]">{title}</h2>
          {description && <p className="mt-1 text-sm text-muted-foreground">{description}</p>}
        </div>
        <button type="button" onClick={onClose} aria-label={closeLabel} className={cn(iconBtn, "-mr-2 -mt-1 h-9 w-9 rounded-xl")}>
          <X className="h-4 w-4" aria-hidden />
        </button>
      </div>
      <div className="px-6 pb-6">{children}</div>
    </dialog>
  );
}

/** Bottom bar for pages whose edits are drafts until saved. */
export function SaveBar({
  label,
  discardLabel,
  saveLabel,
  savingLabel,
  saving,
  canSave,
  onDiscard,
  onSave,
}: {
  label: string;
  discardLabel: string;
  saveLabel: string;
  savingLabel: string;
  saving: boolean;
  canSave: boolean;
  onDiscard: () => void;
  onSave: () => void;
}) {
  return (
    <div className="sticky bottom-0 z-30 border-t border-border bg-background/95 px-4 py-3 backdrop-blur-sm sm:px-6">
      <div className="mx-auto flex max-w-[calc(72rem*var(--settings-k))] flex-wrap items-center justify-end gap-3">
        <span className="mr-auto text-sm text-muted-foreground" role="status">
          {label}
        </span>
        <button type="button" className={outlineBtn} onClick={onDiscard} disabled={saving}>
          {discardLabel}
        </button>
        <button type="button" className={solidBtn} onClick={onSave} disabled={!canSave}>
          {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <Save className="h-3.5 w-3.5" aria-hidden />}
          {saving ? savingLabel : saveLabel}
        </button>
      </div>
    </div>
  );
}

export type ToastState = { message: string; variant: "success" | "error" } | null;

export function Toast({ toast, onDismiss, dismissLabel }: { toast: ToastState; onDismiss: () => void; dismissLabel: string }) {
  useEffect(() => {
    if (!toast) return;
    const id = window.setTimeout(onDismiss, 4000);
    return () => window.clearTimeout(id);
  }, [toast, onDismiss]);

  return (
    <div aria-live="polite" className="pointer-events-none fixed bottom-6 right-6 z-[100] flex max-w-[min(28rem,calc(100vw-3rem))] justify-end">
      {toast && (
        <div
          role="status"
          className="pointer-events-auto flex items-start gap-3 rounded-xl border border-border bg-popover py-3 pl-4 pr-2 text-sm text-popover-foreground shadow-[0_18px_40px_-16px_rgba(0,0,0,0.5)]"
        >
          {toast.variant === "success" ? (
            <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" aria-hidden />
          ) : (
            <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" aria-hidden />
          )}
          <p className="min-w-0 flex-1 leading-snug">{toast.message}</p>
          <button type="button" onClick={onDismiss} aria-label={dismissLabel} className={cn(iconBtn, "-my-1 h-7 w-7")}>
            <X className="h-3.5 w-3.5" aria-hidden />
          </button>
        </div>
      )}
    </div>
  );
}
