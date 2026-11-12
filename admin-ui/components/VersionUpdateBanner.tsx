"use client";

/**
 * "New version available" banner shown at the top of every admin page (AppShell).
 *
 * Data comes from `GET /admin/version-check` (src/api/version_check.py): when
 * the `aion-updater` sidecar is deployed the backend answers with the sidecar's
 * hop plan and `self_update_supported: true`, and the banner offers an
 * "Update now" button that opens `UpdateConfirmDialog` (one click applies every
 * pending release in sequence). Without the sidecar it only links to the
 * changelog and the manual upgrade guide, as before.
 *
 * The admin can dismiss it for 24h (localStorage, same pattern as
 * `aion_admin_change_pw_skipped_until`).
 */

import { useEffect, useState } from "react";
import { ArrowUpCircle, X } from "lucide-react";
import { apiFetch } from "@/lib/api/headers";
import { apiBase } from "@/lib/api";
import { cn } from "@/lib/cn";
import { solidBtn } from "@/components/ui/classes";
import { useT } from "@/lib/i18n/use-t";
import { isSemver } from "@/lib/update";
import { UpdateConfirmDialog } from "@/components/update/UpdateConfirmDialog";

// localStorage key — same pattern as aion_admin_change_pw_skipped_until
const SKIP_KEY = "aion_admin_version_skipped_until";
const SKIP_DURATION_MS = 24 * 60 * 60 * 1000; // 24 hours

/** Response of `GET /admin/version-check` (VersionCheckResponse in src/api/version_check.py). */
type VersionCheckData = {
  current: string;
  /** Target version: a release (X.Y.Z) or `local` in hybrid local-build mode. */
  latest: string;
  update_available: boolean;
  /** True when the aion-updater sidecar answered: the "Update now" button is shown. */
  self_update_supported?: boolean;
  /** "github" or "hybrid-local" (see install.sh `upgrade --plan`). */
  update_mode?: string | null;
};

type Props = {
  className?: string;
};

/** True while the admin's 24h dismissal is still active. */
function isDismissed(): boolean {
  if (typeof window === "undefined") return false;
  try {
    const v = localStorage.getItem(SKIP_KEY);
    if (!v) return false;
    const n = Number(v);
    return Number.isFinite(n) && n > Date.now();
  } catch {
    return false;
  }
}

/** Hide the banner for the next 24 hours. */
function dismiss(): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(SKIP_KEY, String(Date.now() + SKIP_DURATION_MS));
  } catch {
    // Storage blocked: the banner simply comes back on the next load.
  }
}

export function VersionUpdateBanner({ className }: Props) {
  const t = useT();
  const [data, setData] = useState<VersionCheckData | null>(null);
  const [hidden, setHidden] = useState(true); // hidden until the check completes
  const [confirmOpen, setConfirmOpen] = useState(false);

  // Load the version check once on mount (skipped entirely while dismissed).
  useEffect(() => {
    if (isDismissed()) return;
    let active = true;
    apiFetch(`${apiBase()}/admin/version-check`)
      .then((res) => (res.ok ? (res.json() as Promise<VersionCheckData>) : null))
      .then((json) => {
        if (active && json?.update_available) {
          setData(json);
          setHidden(false);
        }
      })
      .catch(() => {
        // Silent: a network error must not break the UI.
      });
    return () => {
      active = false;
    };
  }, []);

  if (hidden || !data) return null;

  // `local` (hybrid mode) has no release page: only real releases get a changelog link.
  const hasRelease = isSemver(data.latest);
  const releaseUrl = `https://github.com/AION-by-ASA-Computer/AION_Agent/releases/tag/v${data.latest}`;
  const upgradeDocsUrl =
    "https://raw.githubusercontent.com/AION-by-ASA-Computer/AION_Agent/main/docs/opensource/releases.md";
  const linkClass =
    "text-xs font-medium text-indigo-700 underline underline-offset-2 hover:text-indigo-900 dark:text-indigo-300 dark:hover:text-indigo-100 transition-colors";

  return (
    <>
      <div
        className={cn(
          "flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-border bg-card px-4 py-3 text-sm shadow-sm",
          className,
        )}
        role="status"
        aria-live="polite"
      >
        <div className="flex min-w-0 items-center gap-2.5">
          <ArrowUpCircle className="h-4 w-4 shrink-0 text-indigo-600 dark:text-indigo-400" aria-hidden />
          <span className="text-foreground">
            <span className="font-semibold">
              {hasRelease
                ? t("update.banner.title", { version: data.latest })
                : t("update.banner.title_local")}
            </span>{" "}
            <span className="text-muted-foreground">
              {t("update.banner.installed", { version: data.current })}
            </span>
          </span>
        </div>

        <div className="flex shrink-0 items-center gap-3">
          {hasRelease && (
            <a
              href={releaseUrl}
              target="_blank"
              rel="noopener noreferrer"
              className={linkClass}
              id="version-banner-changelog-link"
            >
              {t("update.banner.changelog")}
            </a>
          )}
          {data.self_update_supported ? (
            <button
              type="button"
              id="version-banner-update-btn"
              className={solidBtn}
              onClick={() => setConfirmOpen(true)}
            >
              {t("update.banner.update_now")}
            </button>
          ) : (
            <a
              href={upgradeDocsUrl}
              target="_blank"
              rel="noopener noreferrer"
              className={linkClass}
              id="version-banner-upgrade-link"
            >
              {t("update.banner.how_to")}
            </a>
          )}
          <button
            type="button"
            id="version-banner-dismiss-btn"
            aria-label={t("update.banner.dismiss_aria")}
            onClick={() => {
              dismiss();
              setHidden(true);
            }}
            className="ml-1 rounded-lg p-1 text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground focus:outline-none focus:ring-2 focus:ring-indigo-500"
          >
            <X className="h-3.5 w-3.5" aria-hidden />
          </button>
        </div>
      </div>
      {confirmOpen && <UpdateConfirmDialog onClose={() => setConfirmOpen(false)} />}
    </>
  );
}
