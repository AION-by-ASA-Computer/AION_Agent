"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";
import { useT } from "@/lib/i18n/use-t";

import { apiBase } from "@/lib/config";
import {
  getStoredToken,
  setStoredAuth,
  isChangePwSkipped,
} from "@/lib/auth/storage";
import { fetchAuthStatus, resetAuthStatusCache } from "@/lib/auth/status";

/**
 * Client guard: se il backend ha `AION_CHAT_PASSWORD_AUTH=1`, redirige a
 * `/login` quando manca un token valido. Altrimenti e' un no-op.
 *
 * Vive sotto il RootLayout: avvolge tutte le pagine tranne /login (skip via
 * pathname). Il check e' idempotente e caching-friendly (vedi
 * `fetchAuthStatus`).
 */
export function AuthGate({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const t = useT();
  const [state, setState] = useState<"checking" | "ok" | "redirecting">(
    "checking"
  );

  useEffect(() => {
    let cancelled = false;
    const skip =
      pathname === "/login" ||
      pathname?.startsWith("/login/") ||
      pathname === "/change-password" ||
      pathname?.startsWith("/change-password/");
    if (skip) {
      setState("ok");
      return;
    }

    (async () => {
      const status = await fetchAuthStatus();
      if (cancelled) return;
      if (!status.password_auth_enabled) {
        setState("ok");
        return;
      }

      const token = getStoredToken();
      if (!token) {
        setState("redirecting");
        router.replace("/login");
        return;
      }

      try {
        const r = await fetch(`${apiBase()}/auth/me`, {
          headers: { Authorization: `Bearer ${token}` },
          cache: "no-store",
        });
        if (!r.ok) {
          setStoredAuth(null, null);
          resetAuthStatusCache();
          setState("redirecting");
          router.replace("/login");
          return;
        }
        const me = (await r.json().catch(() => ({}))) as {
          must_change_password?: boolean;
        };
        if (me.must_change_password && !isChangePwSkipped()) {
          // Redirect non-bloccante: l'utente puo' skipparlo dalla pagina.
          setState("redirecting");
          router.replace("/change-password");
          return;
        }
        if (!cancelled) setState("ok");
      } catch {
        if (!cancelled) {
          setState("ok");
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [pathname, router]);

  if (state === "ok") return <>{children}</>;

  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-3 bg-background text-muted-foreground">
      <Loader2 className="animate-spin text-primary" size={22} aria-hidden />
      <span className="text-sm">
        {state === "redirecting" ? t("authgate.redirecting") : t("authgate.checking")}
      </span>
    </div>
  );
}
