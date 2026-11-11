"use client";

/**
 * Confirmation dialog for the one-click upgrade.
 *
 * Opened by the "Update now" button of `VersionUpdateBanner`. It loads a fresh
 * hop plan (current → … → target) so the admin sees exactly which releases
 * will be applied, warns about downtime/backups, then calls
 * `POST /admin/update/start` and fires `UPDATE_STARTED_EVENT`, which makes
 * `UpdateProgressOverlay` (mounted in AppShell) take over.
 */

import { useEffect, useState } from "react";
import { ArrowRight, ExternalLink, Loader2, ArrowUpCircle } from "lucide-react";
import { Dialog } from "@/components/profiles/Dialog";
import { ghostBtn, solidBtn } from "@/components/ui/classes";
import { useT } from "@/lib/i18n/use-t";
import {
  fetchUpdatePlan,
  startUpdate,
  UPDATE_STARTED_EVENT,
  type UpdatePlan,
  type UpdateStartError,
} from "@/lib/update";

/** Map backend/sidecar error codes to translated messages. */
function errorMessage(t: (k: string) => string, err: UpdateStartError): string {
  switch (err.code) {
    case "upgrade_running":
    case "upgrade_locked":
      return t("update.confirm.error_running");
    case "no_update":
      return t("update.confirm.error_no_update");
    case "updater_not_configured":
    case "updater_unreachable":
      return t("update.confirm.error_unavailable");
    default:
      return err.message || t("update.confirm.error_generic");
  }
}

export function UpdateConfirmDialog({ onClose }: { onClose: () => void }) {
  const t = useT();
  const [plan, setPlan] = useState<UpdatePlan | null>(null);
  const [planError, setPlanError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);

  // Load a fresh plan on open: the banner's data may be a few minutes old.
  useEffect(() => {
    let active = true;
    fetchUpdatePlan()
      .then((p) => active && setPlan(p))
      .catch((err: UpdateStartError) => active && setPlanError(errorMessage(t, err)));
    return () => {
      active = false;
    };
  }, [t]);

  const confirm = async () => {
    setStarting(true);
    setStartError(null);
    try {
      const status = await startUpdate();
      window.dispatchEvent(new CustomEvent(UPDATE_STARTED_EVENT, { detail: status }));
      onClose();
    } catch (err) {
      const e = err as UpdateStartError;
      if (e.code === "upgrade_running") {
        // Someone else already started it: just show the progress.
        window.dispatchEvent(new CustomEvent(UPDATE_STARTED_EVENT));
        onClose();
        return;
      }
      setStartError(errorMessage(t, e));
      setStarting(false);
    }
  };

  const hops = plan?.hops ?? [];

  return (
    <Dialog title={t("update.confirm.title")} closeLabel={t("update.confirm.cancel")} onClose={onClose}>
      <div className="flex flex-col gap-5">
        {!plan && !planError && (
          <p className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
            {t("update.confirm.loading_plan")}
          </p>
        )}

        {planError && <p className="text-sm text-destructive">{planError}</p>}

        {plan && (
          <>
            <div>
              <p className="text-sm font-medium">{t("update.confirm.chain_label")}</p>
              {/* Version path, e.g. 1.6.2 → 1.6.3 → 1.7.0 */}
              <p className="mt-2 flex flex-wrap items-center gap-1.5 font-mono text-sm">
                <span className="rounded-md bg-secondary px-1.5 py-0.5">{plan.current}</span>
                {hops.map((hop) => (
                  <span key={hop.version} className="inline-flex items-center gap-1.5">
                    <ArrowRight className="h-3.5 w-3.5 text-muted-foreground" aria-hidden />
                    <span className="rounded-md bg-secondary px-1.5 py-0.5">{hop.version}</span>
                  </span>
                ))}
              </p>
              <ul className="mt-3 flex flex-col gap-1 text-sm">
                {hops.map((hop) => (
                  <li key={hop.version} className="flex items-center gap-2">
                    <span className="font-mono">{hop.version}</span>
                    {hop.release_url ? (
                      <a
                        href={hop.release_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1 text-xs text-muted-foreground underline underline-offset-2 hover:text-foreground"
                      >
                        {t("update.confirm.release_notes")}
                        <ExternalLink className="h-3 w-3" aria-hidden />
                      </a>
                    ) : (
                      <span className="text-xs text-muted-foreground">{t("update.confirm.local_hop")}</span>
                    )}
                  </li>
                ))}
              </ul>
            </div>

            <ul className="flex list-disc flex-col gap-1.5 pl-5 text-sm text-muted-foreground">
              <li>{t("update.confirm.warning_downtime")}</li>
              <li>{t("update.confirm.warning_backup")}</li>
              <li>{t("update.confirm.warning_keep_open")}</li>
            </ul>
          </>
        )}

        {startError && <p className="text-sm text-destructive">{startError}</p>}

        <div className="flex justify-end gap-2">
          <button type="button" className={ghostBtn} onClick={onClose}>
            {t("update.confirm.cancel")}
          </button>
          <button
            type="button"
            className={solidBtn}
            disabled={!plan || hops.length === 0 || starting}
            onClick={() => void confirm()}
          >
            {starting ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
            ) : (
              <ArrowUpCircle className="h-3.5 w-3.5" aria-hidden />
            )}
            {starting ? t("update.confirm.starting") : t("update.confirm.confirm")}
          </button>
        </div>
      </div>
    </Dialog>
  );
}
