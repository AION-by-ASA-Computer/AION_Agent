"use client";

import { cn } from "@/lib/cn";
import {
  CHAT_FONT_SIZE_MAX,
  CHAT_FONT_SIZE_MIN,
  CHAT_FONT_SIZE_STEP,
} from "@/lib/theme/chat-font-scale";

type Props = {
  value: number;
  onChange: (value: number) => void;
  className?: string;
  "aria-label"?: string;
};

export function FontSizeSlider({
  value,
  onChange,
  className,
  "aria-label": ariaLabel,
}: Props) {
  const pct =
    ((value - CHAT_FONT_SIZE_MIN) / (CHAT_FONT_SIZE_MAX - CHAT_FONT_SIZE_MIN)) * 100;

  return (
    <div className={cn("flex max-w-sm items-center gap-3", className)}>
      <span
        className="select-none font-semibold leading-none text-muted-foreground"
        style={{ fontSize: "calc(var(--aion-chat-font-size, 14px) * 0.82)" }}
        aria-hidden
      >
        A
      </span>
      <div className="relative min-w-0 flex-1 pt-1 pb-1">
        <div
          className="pointer-events-none absolute top-1/2 right-0 left-0 h-1 -translate-y-1/2 rounded-full bg-muted"
          aria-hidden
        />
        <div
          className="pointer-events-none absolute top-1/2 left-0 h-1 -translate-y-1/2 rounded-full bg-primary/70"
          style={{ width: `${pct}%` }}
          aria-hidden
        />
        <input
          type="range"
          min={CHAT_FONT_SIZE_MIN}
          max={CHAT_FONT_SIZE_MAX}
          step={CHAT_FONT_SIZE_STEP}
          value={value}
          onChange={(e) => onChange(Number(e.target.value))}
          aria-label={ariaLabel}
          className="font-size-slider focus-ring relative z-[1] w-full cursor-pointer appearance-none bg-transparent"
        />
      </div>
      <span
        className="select-none font-semibold leading-none text-muted-foreground"
        style={{ fontSize: "calc(var(--aion-chat-font-size, 14px) * 1.12)" }}
        aria-hidden
      >
        A
      </span>
    </div>
  );
}
