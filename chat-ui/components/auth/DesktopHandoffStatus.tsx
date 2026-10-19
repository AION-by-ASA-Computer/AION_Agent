"use client";

import { useT } from "@/lib/i18n/use-t";
import type { DesktopHandoffErrorCode } from "@/lib/auth/desktop";

export type DesktopHandoffState =
  | { phase: "working" }
  | { phase: "done" }
  | { phase: "error"; code: DesktopHandoffErrorCode };

export function DesktopHandoffStatus({
  state,
  onRetry,
}: {
  state: DesktopHandoffState;
  onRetry: () => void;
}) {
  const t = useT();
  if (state.phase === "working") {
    return (
      <p className="text-sm text-muted-foreground animate-pulse" role="status">
        {t("login.desktop.working")}
      </p>
    );
  }
  if (state.phase === "done") {
    return (
      <p className="max-w-sm text-center text-sm text-foreground" role="status">
        {t("login.desktop.done")}
      </p>
    );
  }
  const key = `login.desktop.error.${state.code}`;
  const msg = t(key);
  return (
    <div className="flex max-w-sm flex-col items-center gap-3 text-center">
      <p className="text-sm text-destructive" role="alert">
        {msg && msg !== key ? msg : t("login.desktop.error.generic")}
      </p>
      {state.code !== "redirect_not_allowed" && (
        <button
          type="button"
          onClick={onRetry}
          className="focus-ring rounded-aion bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
        >
          {t("login.desktop.retry")}
        </button>
      )}
      <p className="text-xs text-muted-foreground">{t("login.desktop.close_hint")}</p>
    </div>
  );
}
