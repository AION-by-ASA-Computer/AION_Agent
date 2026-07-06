"use client";

import { useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore } from "react";
import { createPortal } from "react-dom";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  Check,
  ChevronDown,
  ChevronUp,
  FileText,
  LogIn,
  LogOut,
  Moon,
  Settings,
  Sun,
} from "lucide-react";

import { cn } from "@/lib/cn";
import { setStoredAuth } from "@/lib/auth/storage";
import { useStoredToken } from "@/lib/auth/use-stored-auth";
import { getLocale, setLocale, subscribe, type Locale } from "@/lib/i18n/i18n-store";
import { LOCALE_OPTIONS, localeOption } from "@/lib/i18n/locale-options";
import { syncLanguagePreferenceToServer } from "@/lib/i18n/sync-language";
import { useT } from "@/lib/i18n/use-t";
import { useChatTheme } from "@/lib/theme/chat-theme";
import { profileInitials, resolveProfileColor } from "@/lib/profile/user-appearance";

export function SidebarProfileMenu({
  profileLabel,
  profileSubtitle,
  avatarUrl,
  profileColor,
  isLoggedIn,
  variant = "expanded",
}: {
  profileLabel: string;
  profileSubtitle?: string;
  avatarUrl?: string;
  profileColor?: string;
  isLoggedIn: boolean;
  variant?: "expanded" | "collapsed";
}) {
  const t = useT();
  const router = useRouter();
  const token = useStoredToken();
  const [open, setOpen] = useState(false);
  const [langOpen, setLangOpen] = useState(false);
  const [menuStyle, setMenuStyle] = useState<React.CSSProperties>({});
  const [theme, setTheme] = useChatTheme();
  const locale = useSyncExternalStore(subscribe, getLocale, () => "en" as Locale);
  const menuRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    if (!open || !triggerRef.current) return;
    const rect = triggerRef.current.getBoundingClientRect();
    if (variant === "collapsed") {
      setMenuStyle({
        position: "fixed",
        left: rect.right + 8,
        bottom: window.innerHeight - rect.bottom,
        width: 256,
        zIndex: 60,
      });
      return;
    }
    setMenuStyle({
      position: "fixed",
      left: rect.left,
      bottom: window.innerHeight - rect.top + 8,
      width: Math.max(rect.width, 248),
      zIndex: 60,
    });
  }, [open, variant, langOpen]);

  useEffect(() => {
    if (!open) {
      setLangOpen(false);
      return;
    }
    const onPointerDown = (event: MouseEvent) => {
      const target = event.target as Node;
      if (menuRef.current?.contains(target) || popoverRef.current?.contains(target)) return;
      setOpen(false);
    };
    document.addEventListener("mousedown", onPointerDown);
    return () => document.removeEventListener("mousedown", onPointerDown);
  }, [open]);

  const handleLanguageChange = async (code: Locale) => {
    setLocale(code);
    setLangOpen(false);
    if (token) {
      await syncLanguagePreferenceToServer(token, code);
    }
  };

  const handleLogout = () => {
    setStoredAuth(null, "default");
    window.dispatchEvent(new Event("storage"));
    setOpen(false);
    router.push("/login");
  };

  if (!isLoggedIn) {
    if (variant === "collapsed") {
      return (
        <Link
          href="/login"
          title={t("sidebar.login")}
          aria-label={t("sidebar.login")}
          className="inline-flex h-9 w-9 items-center justify-center rounded-md text-destructive transition hover:bg-destructive/10"
        >
          <LogIn className="h-4 w-4" aria-hidden />
        </Link>
      );
    }

    return (
      <Link
        href="/login"
        className="flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-sm text-destructive transition hover:bg-destructive/10"
      >
        <LogIn className="h-4 w-4 shrink-0" aria-hidden />
        <span className="font-medium">{t("sidebar.login")}</span>
      </Link>
    );
  }

  const currentLocale = localeOption(locale);
  const accentColor = resolveProfileColor({ profile_color: profileColor });
  const initials = profileInitials(profileLabel);

  const avatarNode = (
    <div
      className={cn(
        "flex shrink-0 items-center justify-center overflow-hidden rounded-full font-semibold text-white",
        variant === "collapsed" ? "h-9 w-9 text-xs" : "h-8 w-8 text-xs",
      )}
      style={{ backgroundColor: avatarUrl ? undefined : accentColor }}
    >
      {avatarUrl ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={avatarUrl} alt="" className="h-full w-full object-cover" />
      ) : (
        initials
      )}
    </div>
  );

  const popover = open ? (
    <div
      ref={popoverRef}
      style={menuStyle}
      className="overflow-hidden rounded-xl border border-border bg-card/95 p-1 shadow-lg backdrop-blur-md animate-in fade-in-0 zoom-in-95 duration-150"
      role="menu"
    >
      <div className="border-b border-border/45 px-3 py-2.5">
        <div className="truncate text-sm font-semibold text-foreground">{profileLabel}</div>
        {profileSubtitle ? (
          <div className="truncate text-xs text-muted-foreground">{profileSubtitle}</div>
        ) : null}
      </div>

      <div className="space-y-1 p-1">
        <div className="rounded-lg px-2.5 py-2">
          <div className="mb-2 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
            {t("sidebar.profile_menu.appearance")}
          </div>
          <div className="grid grid-cols-2 gap-1 rounded-lg bg-muted/40 p-0.5">
            <button
              type="button"
              role="menuitemradio"
              aria-checked={theme === "light"}
              onClick={() => setTheme("light")}
              className={cn(
                "focus-ring flex items-center justify-center gap-1.5 rounded-md px-2 py-1.5 text-xs font-medium transition",
                theme === "light"
                  ? "bg-background text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              <Sun className="h-3.5 w-3.5" aria-hidden />
              {t("sidebar.profile_menu.theme_light")}
            </button>
            <button
              type="button"
              role="menuitemradio"
              aria-checked={theme === "dark"}
              onClick={() => setTheme("dark")}
              className={cn(
                "focus-ring flex items-center justify-center gap-1.5 rounded-md px-2 py-1.5 text-xs font-medium transition",
                theme === "dark"
                  ? "bg-background text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              <Moon className="h-3.5 w-3.5" aria-hidden />
              {t("sidebar.profile_menu.theme_dark")}
            </button>
          </div>
        </div>

        <div className="rounded-lg px-1 py-0.5">
          <button
            type="button"
            onClick={() => setLangOpen((prev) => !prev)}
            className="focus-ring flex w-full items-center justify-between gap-2 rounded-lg px-2 py-2 text-left text-sm transition hover:bg-muted/55"
          >
            <span className="font-medium text-foreground">{t("sidebar.profile_menu.language")}</span>
            <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <span aria-hidden>{currentLocale.flag}</span>
              <span>{currentLocale.name}</span>
              {langOpen ? (
                <ChevronUp className="h-3.5 w-3.5" aria-hidden />
              ) : (
                <ChevronDown className="h-3.5 w-3.5" aria-hidden />
              )}
            </span>
          </button>
          {langOpen ? (
            <div className="mt-0.5 space-y-0.5 rounded-lg border border-border/40 bg-muted/20 p-1">
              {LOCALE_OPTIONS.map((lang) => (
                <button
                  key={lang.code}
                  type="button"
                  role="menuitemradio"
                  aria-checked={locale === lang.code}
                  onClick={() => void handleLanguageChange(lang.code)}
                  className={cn(
                    "focus-ring flex w-full items-center justify-between rounded-md px-2.5 py-1.5 text-xs font-medium transition",
                    locale === lang.code
                      ? "bg-primary/10 text-primary"
                      : "text-muted-foreground hover:bg-muted/50 hover:text-foreground",
                  )}
                >
                  <span className="flex items-center gap-2">
                    <span aria-hidden>{lang.flag}</span>
                    <span>{lang.name}</span>
                  </span>
                  {locale === lang.code ? <Check className="h-3.5 w-3.5" aria-hidden /> : null}
                </button>
              ))}
            </div>
          ) : null}
        </div>
      </div>

      <div className="space-y-0.5 border-t border-border/45 p-1">
        <Link
          href="/settings"
          role="menuitem"
          className="focus-ring flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm text-muted-foreground transition hover:bg-muted/55 hover:text-foreground"
          onClick={() => setOpen(false)}
        >
          <Settings className="h-4 w-4 shrink-0" aria-hidden />
          <span className="font-medium">{t("sidebar.settings")}</span>
        </Link>
        <Link
          href="/settings?tab=user-md"
          role="menuitem"
          className="focus-ring flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm text-muted-foreground transition hover:bg-muted/55 hover:text-foreground"
          onClick={() => setOpen(false)}
        >
          <FileText className="h-4 w-4 shrink-0" aria-hidden />
          <span className="font-medium">{t("sidebar.profile_menu.customize")}</span>
        </Link>
        <button
          type="button"
          role="menuitem"
          onClick={handleLogout}
          className="focus-ring flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm font-medium text-destructive transition hover:bg-destructive/10"
        >
          <LogOut className="h-4 w-4 shrink-0" aria-hidden />
          <span>{t("sidebar.profile_menu.logout")}</span>
        </button>
      </div>
    </div>
  ) : null;

  return (
    <div ref={menuRef} className={cn("relative", variant === "expanded" && "w-full")}>
      <button
        ref={triggerRef}
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        className={cn(
          "focus-ring transition",
          variant === "collapsed"
            ? "inline-flex h-9 w-9 items-center justify-center rounded-full bg-primary/15 text-xs font-semibold text-primary hover:bg-primary/20"
            : "flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-left hover:bg-muted/60",
          open && variant === "expanded" && "bg-muted/60",
        )}
        aria-expanded={open}
        aria-haspopup="menu"
        title={profileLabel}
      >
        {avatarNode}
        {variant === "expanded" ? (
          <>
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm font-medium">{profileLabel}</div>
              <div className="truncate text-xs text-muted-foreground">
                {profileSubtitle || t("sidebar.profile")}
              </div>
            </div>
            {open ? (
              <ChevronUp className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
            ) : (
              <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
            )}
          </>
        ) : null}
      </button>

      {typeof document !== "undefined" && popover ? createPortal(popover, document.body) : null}
    </div>
  );
}
