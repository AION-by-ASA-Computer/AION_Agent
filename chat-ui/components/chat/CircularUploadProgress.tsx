"use client";

import { AlertCircle, Check } from "lucide-react";

import { cn } from "@/lib/cn";

export type CircularUploadStatus = "uploading" | "done" | "error";

export function CircularUploadProgress({
  value,
  status,
  size = 20,
  className,
}: {
  value: number;
  status: CircularUploadStatus;
  size?: number;
  className?: string;
}) {
  const stroke = 2;
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const clamped = Math.max(0, Math.min(100, value));
  const offset = circumference - (clamped / 100) * circumference;

  if (status === "error") {
    return (
      <span
        className={cn("inline-flex shrink-0 items-center justify-center text-destructive", className)}
        style={{ width: size, height: size }}
        aria-hidden
      >
        <AlertCircle size={size - 4} />
      </span>
    );
  }

  if (status === "done") {
    return (
      <span
        className={cn(
          "inline-flex shrink-0 items-center justify-center rounded-full bg-emerald-500/15 text-emerald-600 dark:text-emerald-400",
          className,
        )}
        style={{ width: size, height: size }}
        aria-hidden
      >
        <Check size={size - 6} strokeWidth={2.5} />
      </span>
    );
  }

  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      className={cn("shrink-0 -rotate-90", className)}
      aria-hidden
    >
      <circle
        cx={size / 2}
        cy={size / 2}
        r={radius}
        fill="none"
        stroke="currentColor"
        strokeWidth={stroke}
        className="text-muted-foreground/25"
      />
      <circle
        cx={size / 2}
        cy={size / 2}
        r={radius}
        fill="none"
        stroke="currentColor"
        strokeWidth={stroke}
        strokeLinecap="round"
        className="text-primary transition-[stroke-dashoffset] duration-150"
        strokeDasharray={circumference}
        strokeDashoffset={offset}
      />
    </svg>
  );
}
