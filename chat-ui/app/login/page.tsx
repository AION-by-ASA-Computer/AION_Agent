"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { apiBase } from "@/lib/config";
import { setStoredAuth } from "@/lib/auth/storage";
import { fetchAuthStatus } from "@/lib/auth/status";
import { ChatBrand } from "@/components/brand/ChatBrand";
import { initLocaleFromStorage } from "@/lib/i18n/i18n-store";
import { syncLanguagePreferenceToServer } from "@/lib/i18n/sync-language";
import { useT } from "@/lib/i18n/use-t";

export default function LoginPage() {
  const t = useT();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [authRequired, setAuthRequired] = useState<boolean | null>(null);

  useEffect(() => {
    let cancelled = false;
    void fetchAuthStatus().then((s) => {
      if (!cancelled) setAuthRequired(s.password_auth_enabled);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    const r = await fetch(`${apiBase()}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    const raw = await r.text();
    let j: { detail?: string | unknown[]; access_token?: string; user_id?: string };
    try {
      j = raw ? (JSON.parse(raw) as typeof j) : {};
    } catch {
      setErr(
        r.status === 404
          ? `Endpoint non trovato. Imposta NEXT_PUBLIC_AION_API_URL (es. http://localhost:8001) e avvia l'API FastAPI.`
          : "Risposta non valida dal server."
      );
      return;
    }
    if (!r.ok) {
      const d = j.detail;
      const msg =
        typeof d === "string"
          ? d
          : Array.isArray(d) && d[0] && typeof (d[0] as { msg?: string }).msg === "string"
            ? (d[0] as { msg: string }).msg
            : "Login failed";
      setErr(msg);
      return;
    }
    if (j.access_token && j.user_id) {
      setStoredAuth(j.access_token, j.user_id);
      initLocaleFromStorage();
      await syncLanguagePreferenceToServer(j.access_token);
      window.location.href = "/";
    }
  }

  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-6 bg-background px-4 text-foreground">
      <ChatBrand className="mb-2 h-20" />
      <h1 className="text-xl font-semibold tracking-tight text-foreground sr-only">AION Chat — login</h1>
      <form onSubmit={submit} className="flex w-full max-w-sm flex-col gap-3">
        <input
          className="focus-ring rounded-aion border border-input bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground"
          placeholder="Username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          autoComplete="username"
        />
        <input
          type="password"
          className="focus-ring rounded-aion border border-input bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground"
          placeholder="Password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete="current-password"
        />
        {err && (
          <p className="text-sm text-destructive" role="alert">
            {err}
          </p>
        )}
        <button
          type="submit"
          className="focus-ring rounded-aion bg-primary py-2.5 text-sm font-medium text-primary-foreground hover:bg-primary/90"
        >
          {t("login.btn")}
        </button>
      </form>
      {/* Il bypass "chat senza login" e' permesso solo se AION_CHAT_PASSWORD_AUTH e' disattivato lato server. */}
      {authRequired === false && (
        <Link href="/" className="focus-ring text-xs text-primary underline-offset-2 hover:underline">
          {t("login.no_auth")}
        </Link>
      )}
    </div>
  );
}
