"use client";

import { useCallback, useEffect, useState } from "react";
import { ArrowUpCircle, X } from "lucide-react";
import { apiFetch } from "@/lib/api/headers";
import { apiBase } from "@/lib/api";
import { cn } from "@/lib/cn";

// localStorage key — stesso pattern di aion_admin_change_pw_skipped_until
const SKIP_KEY = "aion_admin_version_skipped_until";
const SKIP_DURATION_MS = 24 * 60 * 60 * 1000; // 24 ore

type VersionCheckData = {
  current: string;
  latest: string;
  update_available: boolean;
};

type Props = {
  className?: string;
};

function isDismissed(): boolean {
  if (typeof window === "undefined") return false;
  const v = localStorage.getItem(SKIP_KEY);
  if (!v) return false;
  const n = Number(v);
  return Number.isFinite(n) && n > Date.now();
}

function dismiss(): void {
  if (typeof window === "undefined") return;
  localStorage.setItem(SKIP_KEY, String(Date.now() + SKIP_DURATION_MS));
}

export function VersionUpdateBanner({ className }: Props) {
  const [data, setData] = useState<VersionCheckData | null>(null);
  const [hidden, setHidden] = useState(true); // nascosto fino al check

  const load = useCallback(async () => {
    // Se già dismisso, non fare nemmeno la chiamata API
    if (isDismissed()) return;

    try {
      const res = await apiFetch(`${apiBase()}/admin/version-check`);
      if (!res.ok) return;
      const json: VersionCheckData = await res.json();
      if (json.update_available) {
        setData(json);
        setHidden(false);
      }
    } catch {
      // Silenzioso: errore di rete non deve rompere la UI
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (hidden || !data) return null;

  const releaseUrl = `https://github.com/AION-by-ASA-Computer/AION_Agent/releases/tag/v${data.latest}`;
  const upgradeDocsUrl =
    "https://raw.githubusercontent.com/AION-by-ASA-Computer/AION_Agent/main/docs/opensource/releases.md";

  return (
    <div
      className={cn(
        "flex items-center justify-between gap-3 rounded-2xl border border-indigo-500/30 bg-indigo-500/10 px-4 py-3 text-sm shadow-sm backdrop-blur-sm",
        className,
      )}
      role="status"
      aria-live="polite"
    >
      <div className="flex items-center gap-2.5">
        <ArrowUpCircle
          className="h-4 w-4 shrink-0 text-indigo-400"
          aria-hidden
        />
        <span className="text-indigo-200">
          <span className="font-semibold">
            Nuova versione {data.latest} disponibile
          </span>{" "}
          <span className="text-indigo-300/70">(installata: {data.current})</span>
        </span>
      </div>

      <div className="flex items-center gap-3 shrink-0">
        <a
          href={releaseUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="text-xs font-medium text-indigo-300 underline underline-offset-2 hover:text-indigo-100 transition-colors"
          id="version-banner-changelog-link"
        >
          Changelog
        </a>
        <a
          href={upgradeDocsUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="text-xs font-medium text-indigo-300 underline underline-offset-2 hover:text-indigo-100 transition-colors"
          id="version-banner-upgrade-link"
        >
          Come aggiornare
        </a>
        <button
          type="button"
          id="version-banner-dismiss-btn"
          aria-label="Chiudi notifica aggiornamento"
          onClick={() => {
            dismiss();
            setHidden(true);
          }}
          className="ml-1 rounded-lg p-1 text-indigo-400 hover:bg-indigo-500/20 hover:text-indigo-100 transition-colors focus:outline-none focus:ring-2 focus:ring-indigo-500"
        >
          <X className="h-3.5 w-3.5" aria-hidden />
        </button>
      </div>
    </div>
  );
}
