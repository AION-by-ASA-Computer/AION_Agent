"use client";

import { useEffect } from "react";
import { CheckCircle2, XCircle, X, AlertTriangle } from "lucide-react";

export type ToastState = { message: string; variant: "success" | "error" | "warning" } | null;

export function PageToast({
  toast,
  onDismiss,
}: {
  toast: ToastState;
  onDismiss: () => void;
}) {
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(onDismiss, 5000);
    return () => clearTimeout(t);
  }, [toast, onDismiss]);

  if (!toast) return null;
  const variant = toast.variant;
  const ok = variant === "success";
  const warn = variant === "warning";
  const borderBg =
    ok
      ? "border-emerald-500/40 bg-emerald-950/90 text-emerald-100"
      : warn
        ? "border-amber-500/40 bg-amber-950/90 text-amber-100"
        : "border-red-500/40 bg-red-950/90 text-red-100";
  return (
    <div
      className={`fixed bottom-6 right-6 z-[100] flex max-w-md items-start gap-3 rounded-xl border px-4 py-3 shadow-2xl backdrop-blur-md ${borderBg}`}
      role="status"
    >
      {ok ? (
        <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-emerald-400" />
      ) : warn ? (
        <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-400" />
      ) : (
        <XCircle className="mt-0.5 h-5 w-5 shrink-0 text-red-400" />
      )}
      <p className="text-md leading-snug pr-6">{toast.message}</p>
      <button
        type="button"
        onClick={onDismiss}
        className="absolute right-2 top-2 rounded-lg p-1 opacity-70 hover:opacity-100"
        aria-label="Chiudi"
      >
        <X className="h-4 w-4" />
      </button>
    </div>
  );
}
