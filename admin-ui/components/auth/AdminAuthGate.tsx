"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Loader2, ShieldOff } from "lucide-react";

import { apiBase } from "@/lib/api";
import { adminPath } from "@/lib/paths";
import {
  getStoredToken,
  setStoredAuth,
  isChangePwSkipped,
} from "@/lib/auth/storage";
import { fetchAuthStatus, resetAuthStatusCache } from "@/lib/auth/status";

type GateState =
  | "checking"
  | "ok"
  | "redirecting"
  | "must_change_password"
  | "no_admin_role";

/**
 * Guard globale dell'admin-ui.
 *
 * Comportamento (admin SEMPRE protetto di default, stile Grafana):
 * - Se ``AION_ADMIN_PASSWORD_AUTH=0`` (escape hatch dev) e nessun token,
 *   la UI passa senza login.
 * - Altrimenti: richiede token in localStorage. Se manca o e' invalido,
 *   redirect a ``/login`` (preserva ``next``).
 * - Se l'utente non ha il ruolo ``admin``, mostra "Accesso negato".
 * - Se ``must_change_password=true`` e l'utente non ha ancora "skippato",
 *   redirige a ``/change-password`` (skippabile per 24h).
 */
export function AdminAuthGate({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [state, setState] = useState<GateState>("checking");

  const skip =
    pathname === "/login" ||
    pathname?.startsWith("/login/") ||
    pathname === "/change-password" ||
    pathname?.startsWith("/change-password/");

  useEffect(() => {
    if (skip) {
      setState("ok");
      return;
    }
    let cancelled = false;

    (async () => {
      const status = await fetchAuthStatus();
      if (cancelled) return;

      const adminAuthOn = status.admin_password_auth_enabled !== false;
      const token = getStoredToken();

      if (!adminAuthOn) {
        setState("ok");
        return;
      }

      if (!token) {
        setState("redirecting");
        const next = pathname ? encodeURIComponent(pathname) : "";
        router.replace(next ? `/login?next=${next}` : "/login");
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
          const next = pathname ? encodeURIComponent(pathname) : "";
          router.replace(next ? `/login?next=${next}` : "/login");
          return;
        }
        const me = (await r.json()) as {
          roles?: string[];
          must_change_password?: boolean;
        };
        const roles = Array.isArray(me.roles) ? me.roles : [];
        if (!roles.includes("admin")) {
          setState("no_admin_role");
          return;
        }
        if (me.must_change_password && !isChangePwSkipped()) {
          setState("must_change_password");
          router.replace("/change-password");
          return;
        }
        setState("ok");
      } catch {
        // Errore di rete: non sloggare. apiFetch interceptera' eventuali 401
        // sulle chiamate successive.
        setState("ok");
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [pathname, router, skip]);

  if (state === "ok") return <>{children}</>;

  if (state === "no_admin_role") {
    return (
      <div className="min-h-screen w-full flex flex-col items-center justify-center gap-4 bg-[#0a0a0a] text-white p-8 text-center">
        <ShieldOff className="text-red-400" size={48} aria-hidden />
        <h1 className="text-2xl font-bold">Accesso negato</h1>
        <p className="text-sm text-gray-400 max-w-md">
          Il tuo account non ha il ruolo <code className="px-1.5 py-0.5 rounded bg-white/5 border border-white/10 text-gray-300">admin</code>.
          Chiedi a un amministratore di assegnarti il ruolo, oppure effettua
          login con un altro utente.
        </p>
        <button
          className="mt-2 px-4 py-2 rounded-xl bg-emerald-500/20 text-emerald-300 hover:bg-emerald-500/30 border border-emerald-500/30 transition"
          onClick={() => {
            setStoredAuth(null, null);
            resetAuthStatusCache();
            window.location.replace(adminPath("/login"));
          }}
        >
          Logout e cambia utente
        </button>
      </div>
    );
  }

  return (
    <div className="min-h-screen w-full flex flex-col items-center justify-center gap-3 bg-[#0a0a0a] text-gray-400">
      <Loader2 className="animate-spin text-emerald-400" size={22} aria-hidden />
      <span className="text-sm">
        {state === "redirecting"
          ? "Reindirizzamento al login…"
          : state === "must_change_password"
          ? "Cambio password richiesto…"
          : "Verifica accesso amministratore…"}
      </span>
    </div>
  );
}
