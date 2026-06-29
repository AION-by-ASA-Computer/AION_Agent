"use client";

import * as RadixSelect from "@radix-ui/react-select";
import { Check, ChevronDown, ChevronUp } from "lucide-react";
import { cn } from "@/lib/cn";

export type RadixSelectItem = { value: string; label: string };

type Props = {
  value: string;
  onValueChange: (value: string) => void;
  items: RadixSelectItem[];
  placeholder?: string;
  disabled?: boolean;
  id?: string;
  "aria-label"?: string;
  className?: string;
  triggerClassName?: string;
};

export function AppSelect({
  value,
  onValueChange,
  items,
  placeholder = "Seleziona…",
  disabled,
  id,
  "aria-label": ariaLabel,
  className,
  triggerClassName,
}: Props) {
  return (
    <RadixSelect.Root value={value} onValueChange={onValueChange} disabled={disabled}>
      <RadixSelect.Trigger
        id={id}
        aria-label={ariaLabel}
        className={cn(
          "focus-ring inline-flex h-9 min-w-[140px] max-w-[220px] shrink-0 items-center justify-between gap-2 rounded-aion border border-input bg-background px-3 py-2 text-left text-sm text-foreground shadow-sm data-[placeholder]:text-muted-foreground disabled:cursor-not-allowed disabled:opacity-50 [&>span]:truncate",
          triggerClassName,
          className
        )}
      >
        <RadixSelect.Value placeholder={placeholder} />
        <RadixSelect.Icon className="text-muted-foreground">
          <ChevronDown size={16} aria-hidden />
        </RadixSelect.Icon>
      </RadixSelect.Trigger>
      <RadixSelect.Portal>
        <RadixSelect.Content
          position="popper"
          sideOffset={4}
          className={cn(
            "z-50 max-h-[min(280px,var(--radix-select-content-available-height))] overflow-hidden rounded-aion border border-border bg-popover text-popover-foreground shadow-md",
            "data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0"
          )}
        >
          <RadixSelect.ScrollUpButton className="flex cursor-default items-center justify-center py-1 text-muted-foreground">
            <ChevronUp size={14} />
          </RadixSelect.ScrollUpButton>
          <RadixSelect.Viewport className="p-1">
            {items.map((item) => (
              <RadixSelect.Item
                key={item.value}
                value={item.value}
                className={cn(
                  "focus-ring relative flex cursor-pointer select-none items-center rounded-md py-2 pl-8 pr-3 text-sm outline-none data-[disabled]:pointer-events-none data-[highlighted]:bg-accent data-[highlighted]:text-accent-foreground data-[disabled]:opacity-50"
                )}
              >
                <span className="absolute left-2 flex size-3.5 items-center justify-center">
                  <RadixSelect.ItemIndicator>
                    <Check size={14} className="text-primary" />
                  </RadixSelect.ItemIndicator>
                </span>
                <RadixSelect.ItemText>{item.label}</RadixSelect.ItemText>
              </RadixSelect.Item>
            ))}
          </RadixSelect.Viewport>
          <RadixSelect.ScrollDownButton className="flex cursor-default items-center justify-center py-1 text-muted-foreground">
            <ChevronDown size={14} />
          </RadixSelect.ScrollDownButton>
        </RadixSelect.Content>
      </RadixSelect.Portal>
    </RadixSelect.Root>
  );
}
