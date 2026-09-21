"use client";

import React, { useEffect } from "react";
import { X } from "lucide-react";

export interface SlideOverProps {
  open: boolean;
  onClose: () => void;
  title: string | React.ReactNode;
  subtitle?: string | React.ReactNode;
  icon?: React.ReactNode;
  children: React.ReactNode;
  footer?: React.ReactNode;
  maxWidthClass?: string;
}

export function SlideOver({
  open,
  onClose,
  title,
  subtitle,
  icon,
  children,
  footer,
  maxWidthClass = "max-w-3xl lg:max-w-4xl",
}: SlideOverProps) {
  // Close on Escape key
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && open) {
        onClose();
      }
    };
    if (open) {
      document.addEventListener("keydown", handleKeyDown);
      document.body.style.overflow = "hidden";
    }
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.body.style.overflow = "";
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6 overflow-hidden">
      {/* Backdrop overlay */}
      <div
        onClick={onClose}
        className="fixed inset-0 bg-black/80 backdrop-blur-sm transition-opacity duration-200 animate-in fade-in"
        aria-hidden="true"
      />

      {/* Centered Modal Dialog */}
      <div
        className={`relative pointer-events-auto w-full ${maxWidthClass} max-h-[90vh] flex flex-col rounded-3xl border border-white/10 bg-[#161616] text-white shadow-2xl overflow-hidden animate-in zoom-in-95 duration-200 z-50`}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-white/10 px-6 py-4.5 bg-[#1a1a1a] shrink-0">
          <div className="flex items-center gap-3.5 min-w-0 pr-4">
            {icon && (
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-white/10 bg-white/5 text-blue-400">
                {icon}
              </div>
            )}
            <div className="min-w-0 flex-1">
              <div className="truncate text-lg font-bold text-white tracking-tight">
                {title}
              </div>
              {subtitle && (
                <div className="truncate text-xs text-gray-400 mt-0.5">
                  {subtitle}
                </div>
              )}
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-xl p-2 text-gray-400 hover:bg-white/10 hover:text-white transition cursor-pointer shrink-0"
            aria-label="Chiudi modale"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Scrollable Content Body */}
        <div className="flex-1 overflow-y-auto overflow-x-hidden p-6 space-y-6 custom-scrollbar bg-[#141414]">
          {children}
        </div>

        {/* Fixed Footer */}
        {footer && (
          <div className="border-t border-white/10 bg-[#1a1a1a] px-6 py-4 shrink-0 flex items-center justify-end gap-3 shadow-lg">
            {footer}
          </div>
        )}
      </div>
    </div>
  );
}
