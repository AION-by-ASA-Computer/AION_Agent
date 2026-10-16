"use client";

import { useState, type ReactNode } from "react";
import { Eye, EyeOff, Info, Loader2, TriangleAlert, Zap } from "lucide-react";
import { cn } from "@/lib/cn";
import { inputCls, outlineBtn } from "@/components/ui/classes";
import { Select } from "@/components/ui/Select";

/** Heading of one settings section. */
export function SectionHead({ title, description, action }: { title: string; description?: string; action?: ReactNode }) {
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
  children,
}: {
  title?: string;
  description?: string;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="overflow-hidden rounded-2xl border border-border bg-card/60">
      {title && (
        <header className="flex flex-wrap items-start gap-x-4 gap-y-2 bg-secondary/60 px-5 py-3.5">
          <div className="min-w-0 flex-1">
            <h3 className="text-[15px] font-semibold tracking-[-0.01em]">{title}</h3>
            {description && <p className="mt-0.5 text-xs text-muted-foreground">{description}</p>}
          </div>
          {action}
        </header>
      )}
      <div className={cn(title && "border-t border-border")}>{children}</div>
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
  env,
  wide,
  children,
}: {
  label: string;
  hint?: ReactNode;
  env?: string;
  wide?: boolean;
  children: ReactNode;
}) {
  return (
    <div className={cn("flex min-w-0 flex-col gap-1.5", wide && "md:col-span-2")}>
      <label className="flex flex-col gap-1.5">
        <span className="text-sm font-medium">{label}</span>
        {children}
      </label>
      {(hint || env) && (
        <p className="text-xs text-muted-foreground">
          {hint}
          {env && <span className={cn("font-mono text-[11.5px]", hint && "ml-1.5")}>{env}</span>}
        </p>
      )}
    </div>
  );
}

type TextProps = {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  mono?: boolean;
  type?: "text" | "number" | "url";
  disabled?: boolean;
  inputMode?: "numeric" | "url" | "text";
};

export function TextInput({ value, onChange, placeholder, mono, type = "text", disabled, inputMode }: TextProps) {
  return (
    <input
      type={type}
      inputMode={inputMode}
      value={value}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      autoComplete="off"
      spellCheck={false}
      className={cn(inputCls, mono && "font-mono text-[13px]", disabled && "opacity-60")}
    />
  );
}

export function SecretInput({
  value,
  onChange,
  placeholder,
  showLabel,
  hideLabel,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  showLabel: string;
  hideLabel: string;
}) {
  const [shown, setShown] = useState(false);
  return (
    <span className="relative block">
      <input
        type={shown ? "text" : "password"}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        autoComplete="new-password"
        spellCheck={false}
        className={cn(inputCls, "pr-11 font-mono text-[13px]")}
      />
      <button
        type="button"
        onClick={() => setShown((s) => !s)}
        aria-label={shown ? hideLabel : showLabel}
        aria-pressed={shown}
        className="focus-ring absolute right-1.5 top-1/2 inline-flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
      >
        {shown ? <EyeOff className="h-4 w-4" aria-hidden /> : <Eye className="h-4 w-4" aria-hidden />}
      </button>
    </span>
  );
}

export function Switch({ checked, onChange, label, disabled }: { checked: boolean; onChange: (v: boolean) => void; label: string; disabled?: boolean }) {
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
          checked ? "translate-x-[19px] bg-background" : "translate-x-[3px] bg-muted-foreground",
        )}
      />
    </button>
  );
}

/** One toggle in a divided list. */
export function ToggleRow({ label, description, checked, onChange }: { label: string; description?: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <li className="flex items-center gap-4 px-5 py-3.5">
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium">{label}</p>
        {description && <p className="mt-0.5 text-xs text-muted-foreground">{description}</p>}
      </div>
      <Switch checked={checked} onChange={onChange} label={label} />
    </li>
  );
}

export function ToggleList({ children }: { children: ReactNode }) {
  return <ul className="divide-y divide-border/40">{children}</ul>;
}

/** Mutually exclusive options laid out as radio rows. */
export function ChoiceList<V extends string>({
  value,
  onChange,
  options,
  label,
}: {
  value: V;
  onChange: (v: V) => void;
  label: string;
  options: { value: V; title: string; description: ReactNode; badge?: string }[];
}) {
  return (
    <div role="radiogroup" aria-label={label} className="divide-y divide-border/40">
      {options.map((o) => {
        const on = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={on}
            onClick={() => onChange(o.value)}
            className="focus-ring flex w-full items-start gap-3.5 px-5 py-4 text-left transition-colors hover:bg-secondary/50"
          >
            <span
              aria-hidden
              className={cn(
                "mt-0.5 flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-full border transition-colors",
                on ? "border-foreground" : "border-muted-foreground/50",
              )}
            >
              <span className={cn("h-2 w-2 rounded-full bg-foreground transition-transform", on ? "scale-100" : "scale-0")} />
            </span>
            <span className="min-w-0 flex-1">
              <span className="flex flex-wrap items-center gap-2 text-sm font-medium">
                {o.title}
                {o.badge && <span className="rounded-md bg-secondary px-1.5 py-0.5 text-[11px] font-medium text-muted-foreground">{o.badge}</span>}
              </span>
              <span className="mt-0.5 block text-xs leading-relaxed text-muted-foreground">{o.description}</span>
            </span>
          </button>
        );
      })}
    </div>
  );
}

export function Note({ tone = "info", children }: { tone?: "info" | "warn"; children: ReactNode }) {
  const Icon = tone === "warn" ? TriangleAlert : Info;
  return (
    <div className="flex items-start gap-2.5 rounded-xl bg-secondary/60 px-3.5 py-3 text-sm text-muted-foreground" role={tone === "warn" ? "alert" : undefined}>
      <Icon className={cn("mt-0.5 h-4 w-4 shrink-0", tone === "warn" && "text-warning")} aria-hidden />
      <div className="min-w-0 flex-1 leading-relaxed">{children}</div>
    </div>
  );
}

export function Mono({ children }: { children: ReactNode }) {
  return <span className="font-mono text-[12.5px] text-foreground/80">{children}</span>;
}

/** Test-connection button with its result line. */
export function ProbeBar({
  probing,
  onProbe,
  label,
  ok,
  okText,
}: {
  probing: boolean;
  onProbe: () => void;
  label: string;
  ok: boolean;
  okText: string;
}) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 md:col-span-2">
      <button type="button" onClick={onProbe} disabled={probing} className={outlineBtn}>
        {probing ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <Zap className="h-3.5 w-3.5" aria-hidden />}
        {label}
      </button>
      <span role="status" className="text-sm tabular-nums text-success">
        {ok && okText}
      </span>
    </div>
  );
}

/** Model chooser: a dropdown of discovered ids, or free text when discovery found none. */
export function ModelField({
  label,
  tested,
  manual,
  ids,
  value,
  onChange,
  hintBefore,
  manualPlaceholder,
  manualLabel,
  hint,
}: {
  label: string;
  tested: boolean;
  manual: boolean;
  ids: string[];
  value: string;
  onChange: (v: string) => void;
  hintBefore: string;
  manualPlaceholder: string;
  manualLabel: string;
  hint?: ReactNode;
}) {
  if (!tested) {
    return (
      <div className="md:col-span-2">
        <Note>{hintBefore}</Note>
      </div>
    );
  }
  if (manual) {
    return (
      <Field label={manualLabel} wide hint={hint}>
        <TextInput value={value} onChange={onChange} mono placeholder={manualPlaceholder} />
      </Field>
    );
  }
  return (
    <Field label={label} wide hint={hint}>
      <Select value={value} onChange={onChange} options={ids.map((id) => ({ value: id, label: id }))} aria-label={label} />
    </Field>
  );
}
