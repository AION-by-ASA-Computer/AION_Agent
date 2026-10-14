"use client";

import React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { KeyRound, LogOut, Menu, Moon, PanelLeftClose, PanelLeftOpen, Sun, X } from "lucide-react";
import { apiBase } from "@/lib/api";
import { adminPath } from "@/lib/paths";
import { getStoredUserId, setStoredAuth } from "@/lib/auth/storage";
import { fetchAuthStatus, resetAuthStatusCache } from "@/lib/auth/status";
import { AdminBrand } from "@/components/brand/AdminBrand";
import { VersionUpdateBanner } from "@/components/VersionUpdateBanner";
import { useT } from "@/lib/i18n/use-t";
import { cn } from "@/lib/cn";
import { ADMIN_NAV, isNavActive } from "@/lib/admin-nav";
import { setTheme, useTheme } from "@/lib/theme";

const COLLAPSED_KEY = "aion_admin_sidebar_collapsed";
// Hover wash that reads on both the light and the dark sidebar.
const HOVER = "hover:bg-black/[0.05] hover:text-foreground dark:hover:bg-white/[0.06]";

function initials(id: string | null): string {
  if (!id) return "A";
  const parts = id.replace(/@.*/, "").split(/[._\-\s]+/).filter(Boolean);
  const s = parts.length > 1 ? parts[0][0] + parts[1][0] : id.slice(0, 2);
  return s.toUpperCase();
}

export default function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() || "";
  const t = useT();
  const theme = useTheme();
  const readEmbedded = () =>
    typeof window !== "undefined" && new URLSearchParams(window.location.search).get("embedded") === "1";
  const readUser = () => (typeof window !== "undefined" ? getStoredUserId() : null);
  const [embedded, setEmbedded] = React.useState(readEmbedded);
  const [userId, setUserId] = React.useState(readUser);
  const [collapsed, setCollapsed] = React.useState(() => {
    try {
      return typeof window !== "undefined" && localStorage.getItem(COLLAPSED_KEY) === "1";
    } catch {
      return false;
    }
  });
  const [mobileOpen, setMobileOpen] = React.useState(false);
  // With SSO on, passwords are managed by the identity provider: hide the change-password shortcut.
  const [ssoEnabled, setSsoEnabled] = React.useState(false);
  React.useEffect(() => {
    let alive = true;
    void fetchAuthStatus().then((st) => alive && setSsoEnabled(st.sso_enabled));
    return () => {
      alive = false;
    };
  }, []);
  const [lastPath, setLastPath] = React.useState(pathname);
  if (lastPath !== pathname) {
    // Route changed: refresh identity/embed flags and close the mobile drawer.
    setLastPath(pathname);
    setEmbedded(readEmbedded());
    setUserId(readUser());
    setMobileOpen(false);
  }

  React.useEffect(() => {
    if (!mobileOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setMobileOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [mobileOpen]);

  const toggleCollapsed = () => {
    setCollapsed((c) => {
      const next = !c;
      try {
        localStorage.setItem(COLLAPSED_KEY, next ? "1" : "0");
      } catch {
        // ignore
      }
      return next;
    });
  };

  const isAuthPage =
    pathname === "/login" ||
    pathname.startsWith("/login/") ||
    pathname === "/change-password" ||
    pathname === "/first-setup";

  if (isAuthPage) {
    // Auth pages (login / change-password): no sidebar, full screen.
    return <main className="h-[100dvh] w-screen overflow-auto bg-background">{children}</main>;
  }

  function logout() {
    setStoredAuth(null, null);
    resetAuthStatusCache();
    window.location.replace(adminPath("/login"));
  }

  const version = process.env.NEXT_PUBLIC_AION_VERSION
    ? `v${process.env.NEXT_PUBLIC_AION_VERSION.replace(/^v/, "")}`
    : t("admin_nav.version_unknown");

  if (embedded) {
    return (
      <main className="h-[100dvh] overflow-auto bg-background">
        <div className="mx-auto w-full max-w-[96rem] p-4 sm:p-6">{children}</div>
      </main>
    );
  }

  const nextTheme = theme === "dark" ? "light" : "dark";
  const themeLabel = t(nextTheme === "light" ? "admin_nav.theme_light" : "admin_nav.theme_dark");
  const ThemeIcon = nextTheme === "light" ? Sun : Moon;

  // On mobile the drawer always shows labels, whatever the desktop rail state is.
  const renderSidebar = (rail: boolean) => (
    <div className="flex h-full min-h-0 flex-col">
      <div className={cn("flex shrink-0 items-center gap-2", rail ? "justify-center px-2 pb-3 pt-3" : "px-4 pb-3 pt-3.5")}>
        {!rail && (
          <Link href="/" className="focus-ring min-w-0 flex-1 rounded-lg" aria-label={t("admin_nav.dashboard")}>
            <AdminBrand className="max-w-[120px]" />
          </Link>
        )}
        <button
          type="button"
          onClick={toggleCollapsed}
          className={`focus-ring ml-auto hidden h-9 w-9 shrink-0 items-center justify-center rounded-xl text-muted-foreground transition-colors ${HOVER} lg:inline-flex`}
          aria-label={rail ? t("admin_nav.expand") : t("admin_nav.collapse")}
          title={rail ? t("admin_nav.expand") : t("admin_nav.collapse")}
        >
          {rail ? <PanelLeftOpen className="h-4 w-4" /> : <PanelLeftClose className="h-4 w-4" />}
        </button>
        <button
          type="button"
          onClick={() => setMobileOpen(false)}
          className={`focus-ring ml-auto inline-flex h-9 w-9 items-center justify-center rounded-xl text-muted-foreground ${HOVER} lg:hidden`}
          aria-label={t("admin_nav.close_menu")}
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <nav className={cn("no-scrollbar min-h-0 flex-1 overflow-y-auto pb-3", rail ? "px-2" : "px-3")} aria-label={t("admin_nav.aria")}>
        {ADMIN_NAV.map((group) => (
          <div key={group.id} className={cn(group.labelKey && "mt-4")}>
            {group.labelKey &&
              (rail ? (
                <div className="mx-auto mb-2 h-px w-6 bg-sidebar-border" aria-hidden />
              ) : (
                <div className="mb-1 px-3 text-[10.5px] font-bold uppercase tracking-widest text-muted-foreground/60">
                  {t(group.labelKey)}
                </div>
              ))}
            <ul className="space-y-0.5">
              {group.items.map((item) => {
                const active = isNavActive(pathname, item.href);
                const label = t(item.labelKey);
                return (
                  <li key={item.id}>
                    <Link
                      href={item.href}
                      aria-current={active ? "page" : undefined}
                      title={rail ? label : undefined}
                      className={cn(
                        "focus-ring group flex items-center rounded-xl border text-sm transition-[background-color,color,transform] duration-200",
                        rail ? "mx-auto h-9 w-9 justify-center" : "gap-3 px-3 py-2",
                        active
                          ? "border-primary/15 bg-primary/[0.08] font-semibold text-foreground dark:border-white/10 dark:bg-white/10"
                          : `border-transparent font-medium text-muted-foreground ${HOVER}`,
                        !rail && !active && "hover:translate-x-0.5",
                      )}
                    >
                      <item.icon
                        className={cn("h-4 w-4 shrink-0", active ? "text-primary" : "opacity-80 group-hover:opacity-100")}
                        aria-hidden
                      />
                      {rail ? <span className="sr-only">{label}</span> : <span className="truncate">{label}</span>}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>

      <div className={cn("shrink-0 border-t border-sidebar-border/60", rail ? "space-y-1 p-2" : "p-3")}>
        {rail ? (
          <>
            <div
              className="mx-auto flex h-9 w-9 items-center justify-center rounded-full bg-secondary text-xs font-semibold"
              title={userId ?? undefined}
            >
              {initials(userId)}
            </div>
            <button
              type="button"
              onClick={() => setTheme(nextTheme)}
              className={`focus-ring mx-auto flex h-9 w-9 items-center justify-center rounded-xl text-muted-foreground ${HOVER}`}
              aria-label={themeLabel}
              title={themeLabel}
            >
              <ThemeIcon className="h-4 w-4" />
            </button>
            {!ssoEnabled && (
            <Link
              href="/change-password"
              className={`focus-ring mx-auto flex h-9 w-9 items-center justify-center rounded-xl text-muted-foreground ${HOVER}`}
              aria-label={t("admin_nav.change_password")}
              title={t("admin_nav.change_password")}
            >
              <KeyRound className="h-4 w-4" />
            </Link>
            )}
            <button
              type="button"
              onClick={logout}
              className={`focus-ring mx-auto flex h-9 w-9 items-center justify-center rounded-xl text-muted-foreground ${HOVER}`}
              aria-label={t("admin_nav.logout")}
              title={t("admin_nav.logout")}
            >
              <LogOut className="h-4 w-4" />
            </button>
          </>
        ) : (
          <div className="flex items-center gap-2.5">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-secondary text-xs font-semibold">
              {initials(userId)}
            </div>
            <div className="min-w-0 flex-1 leading-tight">
              <div className="truncate text-sm font-medium" title={userId ?? undefined}>
                {userId ?? t("admin_nav.admin")}
              </div>
              <div className="truncate text-[11px] tabular-nums text-muted-foreground">{version}</div>
            </div>
            <button
              type="button"
              onClick={() => setTheme(nextTheme)}
              className={`focus-ring inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-muted-foreground ${HOVER}`}
              aria-label={themeLabel}
              title={themeLabel}
            >
              <ThemeIcon className="h-4 w-4" />
            </button>
            {!ssoEnabled && (
            <Link
              href="/change-password"
              className={`focus-ring inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-muted-foreground ${HOVER}`}
              aria-label={t("admin_nav.change_password")}
              title={t("admin_nav.change_password")}
            >
              <KeyRound className="h-4 w-4" />
            </Link>
            )}
            <button
              type="button"
              onClick={logout}
              className={`focus-ring inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-muted-foreground ${HOVER}`}
              aria-label={t("admin_nav.logout")}
              title={t("admin_nav.logout")}
            >
              <LogOut className="h-4 w-4" />
            </button>
          </div>
        )}
      </div>
    </div>
  );

  return (
    <div className="grid h-[100dvh] grid-cols-1 bg-background lg:grid-cols-[auto_minmax(0,1fr)]">
      <aside
        className={cn(
          "hidden lg:my-3 lg:ml-3 lg:block lg:h-[calc(100dvh-1.5rem)] lg:overflow-hidden lg:rounded-3xl lg:border lg:border-black/[0.07] lg:bg-sidebar lg:shadow-[0_8px_24px_-14px_rgba(0,0,0,0.18)] dark:lg:border-white/[0.09] dark:lg:bg-sidebar/80 dark:lg:shadow-[0_12px_32px_-12px_rgba(0,0,0,0.55)] lg:transition-[width] lg:duration-300 lg:ease-[cubic-bezier(0.16,1,0.3,1)]",
          collapsed ? "lg:w-16" : "lg:w-64",
        )}
      >
        {renderSidebar(collapsed)}
      </aside>

      {mobileOpen && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <button
            type="button"
            className="absolute inset-0 bg-black/30 backdrop-blur-[2px] dark:bg-black/50"
            aria-label={t("admin_nav.close_menu")}
            onClick={() => setMobileOpen(false)}
          />
          <aside className="absolute inset-y-3 left-3 w-[min(18rem,calc(100vw-1.5rem))] overflow-hidden rounded-3xl border border-black/[0.07] bg-sidebar shadow-[0_16px_40px_-12px_rgba(0,0,0,0.3)] dark:border-white/[0.09] dark:shadow-[0_16px_40px_-12px_rgba(0,0,0,0.7)]">
            {renderSidebar(false)}
          </aside>
        </div>
      )}

      <main className="min-h-0 min-w-0 overflow-y-auto">
        <header className="sticky top-0 z-20 flex h-14 items-center gap-3 border-b border-border/40 bg-background/85 px-4 backdrop-blur-sm sm:px-6 lg:px-8">
          <button
            type="button"
            onClick={() => setMobileOpen(true)}
            className={`focus-ring -ml-1 inline-flex h-9 w-9 items-center justify-center rounded-xl text-muted-foreground ${HOVER} lg:hidden`}
            aria-label={t("admin_nav.open_menu")}
          >
            <Menu className="h-5 w-5" />
          </button>
          <div className="lg:hidden">
            <AdminBrand className="max-w-[96px]" />
          </div>
          <div className="ml-auto flex min-w-0 items-center gap-2 text-xs text-muted-foreground">
            <span className="hidden shrink-0 sm:inline">{t("admin_nav.api")}</span>
            <span className="truncate font-mono text-foreground/80" title={apiBase()}>
              {apiBase()}
            </span>
          </div>
        </header>
        <VersionUpdateBanner className="mx-4 mt-4 sm:mx-6 lg:mx-8" />
        <div className="mx-auto w-full max-w-[96rem] px-4 py-6 sm:px-6 lg:px-8">{children}</div>
      </main>
    </div>
  );
}
