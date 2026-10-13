"use client";

import { useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { Check, ChevronDown } from "lucide-react";
import { cn } from "@/lib/cn";
import { inputCls } from "@/components/ui/classes";

export interface SelectOption<V extends string = string> {
  value: V;
  label: string;
  /** Secondary line under the label (shown in the list, not in the trigger). */
  description?: string;
  /** Leading visual, e.g. a lucide icon. Shown in both list and trigger. */
  icon?: ReactNode;
  disabled?: boolean;
}

export interface SelectProps<V extends string = string> {
  value: V;
  onChange: (value: V) => void;
  options: SelectOption<V>[];
  /** Shown in the trigger when no option matches `value`. */
  placeholder?: string;
  /** Accessible name when the select is not wrapped in a <label>. */
  "aria-label"?: string;
  id?: string;
  /** Submits the value with a surrounding <form>. */
  name?: string;
  disabled?: boolean;
  invalid?: boolean;
  /** `md` matches inputCls fields, `sm` matches toolbar buttons (h-9). */
  size?: "md" | "sm";
  className?: string;
  /** Extra classes for the floating list. */
  listClassName?: string;
}

const GAP = 6;
const MAX_LIST = 288;

/**
 * Styled single-select (WAI-ARIA select-only combobox).
 * - Keyboard: arrows, Home/End, Enter/Space, Escape, Tab, type-ahead.
 * - The list is portaled into the closest <dialog> (or body), so it stays above native
 *   modals and is never clipped by overflow containers.
 * - Drop-in for <select>: `value` / `onChange(value)` / `options`.
 */
export function Select<V extends string = string>({
  value,
  onChange,
  options,
  placeholder,
  id,
  name,
  disabled,
  invalid,
  size = "md",
  className,
  listClassName,
  ...rest
}: SelectProps<V>) {
  const uid = useId();
  const listId = `${uid}-list`;
  const btn = useRef<HTMLButtonElement>(null);
  const list = useRef<HTMLUListElement>(null);
  const typed = useRef({ text: "", at: 0 });
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [pos, setPos] = useState<{ top?: number; bottom?: number; left: number; width: number; maxHeight: number } | null>(null);
  const [host, setHost] = useState<HTMLElement | null>(null);

  const selectedIndex = useMemo(() => options.findIndex((o) => o.value === value), [options, value]);
  const selected = selectedIndex >= 0 ? options[selectedIndex] : null;

  const enabledIdx = useMemo(() => options.map((o, i) => (o.disabled ? -1 : i)).filter((i) => i >= 0), [options]);
  const step = useCallback(
    (from: number, dir: 1 | -1) => {
      if (enabledIdx.length === 0) return -1;
      const at = enabledIdx.indexOf(from);
      if (at === -1) return dir === 1 ? enabledIdx[0] : enabledIdx[enabledIdx.length - 1];
      return enabledIdx[Math.min(enabledIdx.length - 1, Math.max(0, at + dir))];
    },
    [enabledIdx],
  );

  const place = useCallback(() => {
    const el = btn.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const below = window.innerHeight - r.bottom - GAP - 8;
    const above = r.top - GAP - 8;
    const wanted = Math.min(MAX_LIST, options.length * 44 + 12);
    const up = below < Math.min(wanted, 160) && above > below;
    const room = Math.max(120, Math.min(MAX_LIST, up ? above : below));
    const width = r.width;
    const left = Math.max(8, Math.min(window.innerWidth - width - 8, r.left));
    setPos(
      up
        ? { bottom: window.innerHeight - r.top + GAP, left, width, maxHeight: room }
        : { top: r.bottom + GAP, left, width, maxHeight: room },
    );
  }, [options.length]);

  const openList = useCallback(() => {
    if (disabled) return;
    setHost((btn.current?.closest("dialog") as HTMLElement | null) ?? document.body);
    setActive(selectedIndex >= 0 && !options[selectedIndex].disabled ? selectedIndex : step(-1, 1));
    setOpen(true);
  }, [disabled, options, selectedIndex, step]);

  const close = useCallback((refocus = true) => {
    setOpen(false);
    if (refocus) btn.current?.focus();
  }, []);

  const choose = useCallback(
    (i: number) => {
      const o = options[i];
      if (!o || o.disabled) return;
      if (o.value !== value) onChange(o.value);
      close();
    },
    [close, onChange, options, value],
  );

  useLayoutEffect(() => {
    if (open) place();
  }, [open, place]);

  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => {
      const n = e.target as Node;
      if (!list.current?.contains(n) && !btn.current?.contains(n)) setOpen(false);
    };
    const onScroll = (e: Event) => {
      if (list.current?.contains(e.target as Node)) return;
      place();
    };
    document.addEventListener("mousedown", away);
    window.addEventListener("scroll", onScroll, true);
    window.addEventListener("resize", place);
    return () => {
      document.removeEventListener("mousedown", away);
      window.removeEventListener("scroll", onScroll, true);
      window.removeEventListener("resize", place);
    };
  }, [open, place]);

  useEffect(() => {
    if (!open || active < 0) return;
    list.current?.querySelector<HTMLElement>(`[data-i="${active}"]`)?.scrollIntoView({ block: "nearest" });
  }, [open, active]);

  const typeahead = (key: string) => {
    const now = Date.now();
    const t = typed.current;
    t.text = now - t.at > 600 ? key : t.text + key;
    t.at = now;
    const q = t.text.toLowerCase();
    const from = open ? active : selectedIndex;
    const order = [...options.keys()];
    const rotated = [...order.slice(from + 1), ...order.slice(0, from + 1)];
    const hit = rotated.find((i) => !options[i].disabled && options[i].label.toLowerCase().startsWith(q));
    if (hit === undefined) return;
    if (open) setActive(hit);
    else if (options[hit].value !== value) onChange(options[hit].value);
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (disabled) return;
    const k = e.key;
    if (!open) {
      if (k === "ArrowDown" || k === "ArrowUp" || k === "Enter" || k === " ") {
        e.preventDefault();
        openList();
      } else if (k.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
        typeahead(k);
      }
      return;
    }
    if (k === "Escape") {
      // Keep the surrounding <dialog> from closing with the list.
      e.preventDefault();
      e.stopPropagation();
      close();
    } else if (k === "ArrowDown") {
      e.preventDefault();
      setActive((a) => step(a, 1));
    } else if (k === "ArrowUp") {
      e.preventDefault();
      setActive((a) => step(a, -1));
    } else if (k === "Home") {
      e.preventDefault();
      setActive(enabledIdx[0] ?? -1);
    } else if (k === "End") {
      e.preventDefault();
      setActive(enabledIdx[enabledIdx.length - 1] ?? -1);
    } else if (k === "Enter" || k === " ") {
      e.preventDefault();
      choose(active);
    } else if (k === "Tab") {
      setOpen(false);
    } else if (k.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
      typeahead(k);
    }
  };

  return (
    <>
      <button
        ref={btn}
        id={id}
        type="button"
        role="combobox"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        aria-activedescendant={open && active >= 0 ? `${uid}-o${active}` : undefined}
        aria-label={rest["aria-label"]}
        aria-invalid={invalid || undefined}
        disabled={disabled}
        onClick={() => (open ? close(false) : openList())}
        onKeyDown={onKeyDown}
        className={cn(
          inputCls,
          "flex cursor-pointer items-center gap-2.5 text-left disabled:cursor-not-allowed disabled:opacity-60",
          size === "sm" && "h-9 py-0 pl-3 pr-2.5",
          open && "border-foreground/40",
          invalid && "border-destructive/60",
          className,
        )}
      >
        {selected?.icon && (
          <span className="flex shrink-0 text-muted-foreground" aria-hidden>
            {selected.icon}
          </span>
        )}
        <span className={cn("min-w-0 flex-1 truncate", !selected && "text-muted-foreground/70")}>
          {selected ? selected.label : placeholder ?? " "}
        </span>
        <ChevronDown
          className={cn("h-4 w-4 shrink-0 text-muted-foreground transition-transform duration-150", open && "rotate-180")}
          aria-hidden
        />
      </button>
      {name && <input type="hidden" name={name} value={value} />}

      {open &&
        pos &&
        host &&
        createPortal(
          <ul
            ref={list}
            id={listId}
            role="listbox"
            tabIndex={-1}
            aria-label={rest["aria-label"]}
            style={{ position: "fixed", top: pos.top, bottom: pos.bottom, left: pos.left, width: pos.width, maxHeight: pos.maxHeight }}
            className={cn(
              "z-[100] overflow-y-auto overscroll-contain rounded-2xl border border-border bg-popover p-1.5 text-popover-foreground shadow-[0_18px_40px_-16px_rgba(0,0,0,0.5)]",
              listClassName,
            )}
            onMouseDown={(e) => e.preventDefault()}
          >
            {options.map((o, i) => {
              const isSel = i === selectedIndex;
              return (
                <li
                  key={o.value}
                  id={`${uid}-o${i}`}
                  data-i={i}
                  role="option"
                  aria-selected={isSel}
                  aria-disabled={o.disabled || undefined}
                  onMouseMove={() => !o.disabled && active !== i && setActive(i)}
                  onClick={() => choose(i)}
                  className={cn(
                    "flex cursor-pointer items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm transition-colors",
                    i === active && "bg-secondary",
                    o.disabled && "cursor-not-allowed opacity-45",
                  )}
                >
                  {o.icon && (
                    <span className="flex shrink-0 text-muted-foreground" aria-hidden>
                      {o.icon}
                    </span>
                  )}
                  <span className="min-w-0 flex-1">
                    <span className={cn("block truncate", isSel && "font-semibold")}>{o.label}</span>
                    {o.description && <span className="block text-xs text-muted-foreground">{o.description}</span>}
                  </span>
                  {isSel && <Check className="h-4 w-4 shrink-0 text-foreground" aria-hidden />}
                </li>
              );
            })}
          </ul>,
          host,
        )}
    </>
  );
}
