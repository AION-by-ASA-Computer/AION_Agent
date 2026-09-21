"use client";

import React from "react";

interface SwitchProps {
  id?: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
  label?: React.ReactNode;
  description?: React.ReactNode;
  className?: string;
}

export function Switch({
  id,
  checked,
  onChange,
  disabled = false,
  label,
  description,
  className = "",
}: SwitchProps) {
  const switchId = id || React.useId();

  return (
    <div className={`flex items-start justify-between gap-3 ${className}`}>
      {label || description ? (
        <label
          htmlFor={switchId}
          className={`flex flex-1 cursor-pointer flex-col select-none ${
            disabled ? "cursor-not-allowed opacity-60" : ""
          }`}
        >
          {label ? (
            <span className="text-sm font-medium text-foreground">{label}</span>
          ) : null}
          {description ? (
            <span className="text-xs text-muted-foreground">{description}</span>
          ) : null}
        </label>
      ) : null}
      <button
        type="button"
        role="switch"
        id={switchId}
        aria-checked={checked}
        disabled={disabled}
        onClick={() => !disabled && onChange(!checked)}
        className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer items-center rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 ${
          checked ? "bg-primary" : "bg-muted"
        } ${disabled ? "cursor-not-allowed opacity-50" : ""}`}
      >
        <span
          aria-hidden="true"
          className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-background shadow-lg ring-0 transition duration-200 ease-in-out ${
            checked ? "translate-x-5" : "translate-x-0"
          }`}
        />
      </button>
    </div>
  );
}
