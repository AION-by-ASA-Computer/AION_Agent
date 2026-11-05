"use client";

/**
 * Admin Telegram page: the single place for the Telegram channel. Everything is split
 * into tabs so each task is one click away instead of one long scroll:
 *
 *   configuration (one shared form)      data (live lists)
 *   Connection · Policies · Chat    |    Assistants · Quotas · Activity
 *
 * The configuration form stays mounted behind every tab (see `TelegramConfigPanel`), so
 * unsaved edits survive tab switches; the lists mount only while their tab is open and
 * therefore always show fresh data. The active tab is mirrored in the URL hash so a
 * reload or a shared link lands on the same tab.
 */

import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from "react";
import { useT } from "@/lib/i18n/use-t";
import { cn } from "@/lib/cn";
import { PageToast, type ToastState } from "@/components/PageToast";
import { TelegramAuditLog } from "@/components/telegram/TelegramAuditLog";
import { TelegramBotsList } from "@/components/telegram/TelegramBotsList";
import { TelegramConfigPanel, type ConfigSection } from "@/components/telegram/TelegramConfigPanel";
import { TelegramQuotasList } from "@/components/telegram/TelegramQuotasList";
import { k, type Notify } from "@/components/telegram/shared";

const p = `${k}.page`;

type Tab = ConfigSection | "assistants" | "quotas" | "activity";

/** Tab order as shown; `group` draws the divider between the form tabs and the list tabs. */
const TABS: { id: Tab; label: string; group: "config" | "data" }[] = [
  { id: "connection", label: `${p}.tabs.connection`, group: "config" },
  { id: "policies", label: `${p}.tabs.policies`, group: "config" },
  { id: "chat", label: `${p}.tabs.chat`, group: "config" },
  { id: "assistants", label: `${p}.bots_title`, group: "data" },
  { id: "quotas", label: `${p}.quotas_title`, group: "data" },
  { id: "activity", label: `${p}.audit_title`, group: "data" },
];

const isTab = (v: string): v is Tab => TABS.some((x) => x.id === v);
const isConfigTab = (tab: Tab): tab is ConfigSection => tab === "connection" || tab === "policies" || tab === "chat";

export default function TelegramAdminPage() {
  const t = useT();
  const [toast, setToast] = useState<ToastState>(null);
  const notify: Notify = useCallback((message, variant = "info") => setToast({ message, variant }), []);
  // Bumped after a config save: the gateway restarts and the default quota may change,
  // so the lists reload.
  const [rev, setRev] = useState(0);
  const onSaved = useCallback(() => setRev((r) => r + 1), []);

  const [tab, setTab] = useState<Tab>("connection");
  // Tabs whose form fields hold unsaved edits (reported by the config panel).
  const [dirty, setDirty] = useState<ConfigSection[]>([]);
  const tabRefs = useRef<Partial<Record<Tab, HTMLButtonElement | null>>>({});

  // Restore the tab from the URL hash after hydration (reading it during render would
  // mismatch the server markup).
  useEffect(() => {
    const fromHash = window.location.hash.slice(1);
    // eslint-disable-next-line react-hooks/set-state-in-effect -- one-off read of the URL hash on mount
    if (isTab(fromHash)) setTab(fromHash);
  }, []);

  const select = useCallback((next: Tab) => {
    setTab(next);
    window.history.replaceState(null, "", `#${next}`);
  }, []);

  /** WAI-ARIA tabs: arrows move between tabs, Home/End jump to the ends. */
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const i = TABS.findIndex((x) => x.id === tab);
    const to =
      e.key === "ArrowRight" ? (i + 1) % TABS.length
        : e.key === "ArrowLeft" ? (i - 1 + TABS.length) % TABS.length
          : e.key === "Home" ? 0
            : e.key === "End" ? TABS.length - 1
              : -1;
    if (to < 0) return;
    e.preventDefault();
    select(TABS[to].id);
    tabRefs.current[TABS[to].id]?.focus();
  };

  /** One-line description of the open list tab (the form tabs carry their own group titles). */
  const listDesc =
    tab === "assistants" ? t(`${p}.bots_desc`) : tab === "quotas" ? t(`${p}.quotas_desc`) : tab === "activity" ? t(`${p}.audit_desc`) : null;

  return (
    <div className="mx-auto max-w-4xl pb-24">
      <header className="pb-6">
        <h1 className="text-balance text-2xl font-semibold tracking-[-0.02em] sm:text-3xl">{t(`${k}.title`)}</h1>
        <p className="mt-1 max-w-[62ch] text-sm text-muted-foreground">{t(`${k}.subtitle`)}</p>
      </header>

      <div
        role="tablist"
        aria-label={t(`${p}.tabs.aria`)}
        onKeyDown={onKeyDown}
        className="no-scrollbar mb-6 flex items-stretch gap-1 overflow-x-auto border-b border-border/60"
      >
        {TABS.map((x, i) => {
          const active = tab === x.id;
          const unsaved = isConfigTab(x.id) && dirty.includes(x.id);
          return (
            <div key={x.id} className="flex items-stretch gap-1">
              {/* Visual break between "set it up" tabs and "look at what exists" tabs. */}
              {i > 0 && x.group !== TABS[i - 1].group && <span aria-hidden className="mx-2 my-3 w-px bg-border" />}
              <button
                ref={(el) => {
                  tabRefs.current[x.id] = el;
                }}
                type="button"
                role="tab"
                id={`tg-tab-${x.id}`}
                aria-selected={active}
                aria-controls="tg-panel"
                tabIndex={active ? 0 : -1}
                onClick={() => select(x.id)}
                className={cn(
                  "focus-ring relative inline-flex h-11 shrink-0 items-center gap-2 px-3 text-sm font-medium transition-colors",
                  active ? "text-foreground" : "text-muted-foreground hover:text-foreground",
                )}
              >
                {t(x.label)}
                {unsaved && (
                  <>
                    <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-warning" />
                    <span className="sr-only">{t(`${p}.tabs.unsaved`)}</span>
                  </>
                )}
                <span
                  aria-hidden
                  className={cn("absolute inset-x-3 bottom-0 h-0.5 rounded-full bg-foreground transition-opacity", active ? "opacity-100" : "opacity-0")}
                />
              </button>
            </div>
          );
        })}
      </div>

      <div id="tg-panel" role="tabpanel" aria-labelledby={`tg-tab-${tab}`} className="flex flex-col gap-4">
        {/* Always mounted: it owns the unsaved edits and the save bar for the three form tabs. */}
        <TelegramConfigPanel
          t={t}
          notify={notify}
          section={isConfigTab(tab) ? tab : null}
          onSaved={onSaved}
          onDirtySections={setDirty}
        />

        {listDesc && <p className="max-w-[62ch] text-sm text-muted-foreground">{listDesc}</p>}
        {tab === "assistants" && <TelegramBotsList t={t} notify={notify} rev={rev} />}
        {tab === "quotas" && <TelegramQuotasList t={t} notify={notify} rev={rev} />}
        {tab === "activity" && <TelegramAuditLog t={t} rev={rev} />}
      </div>

      <PageToast toast={toast} onDismiss={() => setToast(null)} />
    </div>
  );
}
