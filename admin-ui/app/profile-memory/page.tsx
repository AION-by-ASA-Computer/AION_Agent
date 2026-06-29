"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { apiFetch } from "@/lib/api/headers"
import {
  Sparkles,
  Database,
  User,
  KeyRound,
  Loader2,
  RefreshCw,
  Save,
  BookOpen,
  Info,
  CheckCircle2,
} from "lucide-react";
import { apiBase } from "@/lib/api";
import { PageToast, type ToastState } from "@/components/PageToast";

type ProfileRow = { name: string; description?: string; slug?: string };

type Meta = {
  profile_slug: string;
  soul_read_path: string | null;
  soul_write_path: string;
  soul_exists: boolean;
  memory_path: string;
  memory_max_chars: number;
  user_max_chars: number;
  soul_max_chars: number;
  users: string[];
  soul_memory_user_split_enabled: boolean;
};

export default function ProfileMemoryPage() {
  const [toast, setToast] = useState<ToastState>(null);
  const show = (message: string, variant: "success" | "error" = "success") =>
    setToast({ message, variant });

  const [profiles, setProfiles] = useState<ProfileRow[]>([]);
  const [slug, setSlug] = useState("");
  const [adminToken, setAdminToken] = useState("");
  const [meta, setMeta] = useState<Meta | null>(null);
  const [soul, setSoul] = useState("");
  const [memory, setMemory] = useState("");
  const [userId, setUserId] = useState("default");
  const [userMd, setUserMd] = useState("");
  const [loading, setLoading] = useState(false);
  const [tab, setTab] = useState<"soul" | "memory" | "user">("soul");

  useEffect(() => {
    const t = sessionStorage.getItem("aion_admin_memory_token");
    if (t) setAdminToken(t);
  }, []);

  const authHeaders = useCallback(
    (json = false): HeadersInit => {
      const h: Record<string, string> = {};
      if (json) h["Content-Type"] = "application/json";
      const tok = adminToken || sessionStorage.getItem("aion_admin_memory_token") || "";
      if (tok) h["Authorization"] = `Bearer ${tok}`;
      return h;
    },
    [adminToken]
  );

  useEffect(() => {
    apiFetch(`${apiBase()}/admin/profiles`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((data: ProfileRow[]) => {
        const list = Array.isArray(data) ? data : [];
        setProfiles(list);
        if (list.length) {
          setSlug((prev) => {
            if (prev) return prev;
            const p0 = list[0];
            return p0.slug || p0.name.replace(/\s+/g, "_").toLowerCase();
          });
        }
      })
      .catch(() => show("Impossibile caricare i profili. Verifica NEXT_PUBLIC_AION_API_URL e che l’API sia avviata.", "error"));
  }, []);

  const loadMeta = async () => {
    if (!slug) return;
    const r = await apiFetch(`${apiBase()}/admin/profile-memory/${encodeURIComponent(slug)}/meta`, {
      headers: authHeaders(false),
    });
    if (r.status === 401 || r.status === 403) {
      show("Token admin richiesto o non valido (AION_ADMIN_MEMORY_TOKEN).", "error");
      return;
    }
    if (!r.ok) {
      show(`Metadati: errore ${r.status}`, "error");
      return;
    }
    const j = (await r.json()) as Meta;
    setMeta(j);
  };

  const loadAll = async () => {
    if (!slug) return;
    setLoading(true);
    try {
      await loadMeta();
      const [rs, rm, ru] = await Promise.all([
        apiFetch(`${apiBase()}/admin/profile-memory/${encodeURIComponent(slug)}/soul`, { headers: authHeaders(false) }),
        apiFetch(`${apiBase()}/admin/profile-memory/${encodeURIComponent(slug)}/memory`, { headers: authHeaders(false) }),
        apiFetch(
          `${apiBase()}/admin/profile-memory/${encodeURIComponent(slug)}/users/${encodeURIComponent(userId.trim() || "default")}`,
          { headers: authHeaders(false) }
        ),
      ]);
      if (rs.ok) {
        const j = await rs.json();
        setSoul(j.content ?? "");
      }
      if (rm.ok) {
        const j = await rm.json();
        setMemory(j.content ?? "");
      }
      if (ru.ok) {
        const j = await ru.json();
        setUserMd(j.content ?? "");
      }
      show("Contenuti aggiornati.");
    } catch (e) {
      show(String(e), "error");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!slug) return;
    loadAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- ricarica al cambio profilo / token
  }, [slug, adminToken]);

  const persistToken = () => {
    sessionStorage.setItem("aion_admin_memory_token", adminToken);
    show("Token salvato in questa sessione browser.");
  };

  const put = async (path: string, body: { content: string }) => {
    const r = await apiFetch(`${apiBase()}/admin/profile-memory/${encodeURIComponent(slug)}${path}`, {
      method: "PUT",
      headers: authHeaders(true),
      body: JSON.stringify(body),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error((err as { detail?: string }).detail || r.statusText);
    }
  };

  const soulChars = soul.length;
  const memChars = memory.length;
  const userChars = userMd.length;

  const limits = useMemo(
    () => ({
      soul: meta?.soul_max_chars ?? 12000,
      mem: meta?.memory_max_chars ?? 2200,
      user: meta?.user_max_chars ?? 1400,
    }),
    [meta]
  );

  const profileLabel = profiles.find(
    (p) => (p.slug || p.name.replace(/\s+/g, "_").toLowerCase()) === slug
  )?.name;

  return (
    <div className="mx-auto max-w-5xl space-y-8 pb-16">
      <PageToast toast={toast} onDismiss={() => setToast(null)} />

      {/* Hero */}
      <header className="relative overflow-hidden rounded-2xl border border-[#262626] bg-gradient-to-br from-violet-950/40 via-[#0d0d0d] to-[#0a0a0a] p-8">
        <div className="pointer-events-none absolute -right-20 -top-20 h-64 w-64 rounded-full bg-violet-600/10 blur-3xl" />
        <div className="relative flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
          <div className="space-y-3">
            <div className="inline-flex items-center gap-2 rounded-full border border-violet-500/30 bg-violet-500/10 px-3 py-1 text-[11px] font-bold uppercase tracking-wider text-violet-300">
              <Sparkles className="h-3.5 w-3.5" /> Memoria agente (Hermes)
            </div>
            <h1 className="text-3xl font-bold tracking-tight text-white md:text-4xl">
              Identità e preferenze
            </h1>
            <p className="max-w-2xl text-sm leading-relaxed text-gray-400">
              Qui modifichi i file che il modello può leggere nel system prompt quando{" "}
              <code className="rounded bg-black/50 px-1.5 py-0.5 text-violet-300">AION_SOUL_MEMORY_USER_SPLIT=1</code> è
              attivo sul backend. Tre livelli: <strong className="text-gray-200">SOUL</strong> (chi è l’agente),{" "}
              <strong className="text-gray-200">MEMORY</strong> (fatti operativi condivisi per profilo),{" "}
              <strong className="text-gray-200">USER</strong> (preferenze per singolo utente).
            </p>
          </div>
          <div className="glass-card flex shrink-0 flex-col gap-2 rounded-xl p-4 text-xs text-gray-400">
            <div className="flex items-center gap-2 text-gray-300">
              <Info className="h-4 w-4 text-violet-400" />
              <span className="font-semibold">Endpoint API</span>
            </div>
            <code className="break-all rounded-lg bg-black/40 px-2 py-1.5 text-[11px] text-gray-300">{apiBase()}</code>
          </div>
        </div>
      </header>

      {/* Controls */}
      <section className="glass-card space-y-4 rounded-2xl p-6">
        <div className="grid gap-4 md:grid-cols-2">
          <div className="space-y-2">
            <label className="text-xs font-bold uppercase tracking-wide text-gray-500">Profilo</label>
            <select
              value={slug}
              onChange={(e) => setSlug(e.target.value)}
              className="w-full rounded-xl border border-[#333] bg-[#111] px-4 py-3 text-sm text-white outline-none transition focus:border-violet-500 focus:ring-1 focus:ring-violet-500"
            >
              {profiles.length === 0 && <option value="">— Nessun profilo —</option>}
              {profiles.map((p) => {
                const s = p.slug || p.name.replace(/\s+/g, "_").toLowerCase();
                return (
                  <option key={p.name} value={s}>
                    {p.name} · {s}
                  </option>
                );
              })}
            </select>
            {profileLabel && <p className="text-xs text-gray-500">Nome: {profileLabel}</p>}
          </div>
          <div className="space-y-2">
            <label className="flex items-center gap-2 text-xs font-bold uppercase tracking-wide text-gray-500">
              <KeyRound className="h-3.5 w-3.5" />
              Token admin (solo se imposti <code className="text-gray-600">AION_ADMIN_MEMORY_TOKEN</code>)
            </label>
            <div className="flex gap-2">
              <input
                type="password"
                value={adminToken}
                onChange={(e) => setAdminToken(e.target.value)}
                onBlur={persistToken}
                placeholder="Incolla il bearer token"
                className="min-w-0 flex-1 rounded-xl border border-[#333] bg-[#111] px-4 py-3 text-sm outline-none focus:border-violet-500"
              />
              <button
                type="button"
                onClick={persistToken}
                className="shrink-0 rounded-xl border border-[#333] bg-[#1a1a1a] px-4 text-xs font-bold text-gray-300 hover:bg-[#252525]"
              >
                Salva
              </button>
            </div>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-3 border-t border-[#262626] pt-4">
          <button
            type="button"
            disabled={loading || !slug}
            onClick={() => loadAll()}
            className="inline-flex items-center gap-2 rounded-xl bg-violet-600 px-5 py-2.5 text-sm font-bold text-white shadow-lg shadow-violet-900/30 transition hover:bg-violet-500 disabled:opacity-50"
          >
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            Ricarica tutto
          </button>
          {meta && (
            <div className="flex flex-wrap items-center gap-2 text-xs text-gray-500">
              <CheckCircle2 className="h-4 w-4 text-emerald-500" />
              Split prompt:{" "}
              <span className={meta.soul_memory_user_split_enabled ? "text-emerald-400" : "text-amber-400"}>
                {meta.soul_memory_user_split_enabled ? "attivo" : "disattivo"}
              </span>
            </div>
          )}
        </div>
      </section>

      {/* Meta summary cards */}
      {meta && (
        <div className="grid gap-3 sm:grid-cols-3">
          <div className="rounded-xl border border-violet-500/20 bg-violet-950/20 p-4">
            <div className="mb-1 flex items-center gap-2 text-[11px] font-bold uppercase tracking-wide text-violet-400">
              <BookOpen className="h-4 w-4" /> SOUL
            </div>
            <p className="text-xs text-gray-500">File identità agente</p>
            <p className="mt-2 truncate text-[11px] text-gray-600" title={meta.soul_write_path}>
              {meta.soul_exists ? "Presente" : "Da creare"} · max {meta.soul_max_chars} caratteri
            </p>
          </div>
          <div className="rounded-xl border border-sky-500/20 bg-sky-950/20 p-4">
            <div className="mb-1 flex items-center gap-2 text-[11px] font-bold uppercase tracking-wide text-sky-400">
              <Database className="h-4 w-4" /> MEMORY
            </div>
            <p className="text-xs text-gray-500">Memoria operativa del profilo</p>
            <p className="mt-2 truncate text-[11px] text-gray-600" title={meta.memory_path}>
              max {meta.memory_max_chars} caratteri
            </p>
          </div>
          <div className="rounded-xl border border-amber-500/20 bg-amber-950/20 p-4">
            <div className="mb-1 flex items-center gap-2 text-[11px] font-bold uppercase tracking-wide text-amber-400">
              <User className="h-4 w-4" /> USER
            </div>
            <p className="text-xs text-gray-500">Preferenze per utente</p>
            <p className="mt-2 text-[11px] text-gray-600">max {meta.user_max_chars} caratteri · {meta.users.length} utenti con file</p>
          </div>
        </div>
      )}

      {/* Tabs + editors */}
      <div className="overflow-hidden rounded-2xl border border-[#262626] bg-[#0d0d0d]">
        <div className="flex border-b border-[#262626] bg-[#111]">
          {(
            [
              ["soul", "SOUL", "Identità dell’agente", Sparkles],
              ["memory", "MEMORY", "Fatti condivisi (profilo)", Database],
              ["user", "USER", "Preferenze utente", User],
            ] as const
          ).map(([id, title, sub, Icon]) => (
            <button
              key={id}
              type="button"
              onClick={() => setTab(id)}
              className={`flex flex-1 flex-col items-start gap-0.5 px-4 py-4 text-left transition sm:flex-row sm:items-center sm:gap-3 sm:px-6 ${
                tab === id
                  ? "border-b-2 border-violet-500 bg-violet-500/5 text-white"
                  : "border-b-2 border-transparent text-gray-500 hover:bg-white/[0.03] hover:text-gray-300"
              }`}
            >
              <Icon className={`hidden h-5 w-5 sm:block ${tab === id ? "text-violet-400" : ""}`} />
              <div>
                <div className="text-sm font-bold">{title}</div>
                <div className="text-[11px] font-medium text-gray-500">{sub}</div>
              </div>
            </button>
          ))}
        </div>

        <div className="p-6">
          {tab === "user" && (
            <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-end">
              <div className="flex-1 space-y-2">
                <label className="text-xs font-bold text-gray-500">Utente (ID cartella)</label>
                <input
                  value={userId}
                  onChange={(e) => setUserId(e.target.value)}
                  className="w-full rounded-xl border border-[#333] bg-[#111] px-4 py-3 text-sm"
                  placeholder="es. demo, mario, email@azienda.it"
                />
              </div>
              <button
                type="button"
                onClick={async () => {
                  setLoading(true);
                  try {
                    const r = await apiFetch(
                      `${apiBase()}/admin/profile-memory/${encodeURIComponent(slug)}/users/${encodeURIComponent(userId.trim() || "default")}`,
                      { headers: authHeaders(false) }
                    );
                    if (r.ok) {
                      const j = await r.json();
                      setUserMd(j.content ?? "");
                      await loadMeta();
                      show("USER caricato.");
                    } else show("Errore caricamento USER", "error");
                  } finally {
                    setLoading(false);
                  }
                }}
                className="rounded-xl border border-[#333] bg-[#1a1a1a] px-4 py-3 text-xs font-bold text-gray-200 hover:bg-[#222]"
              >
                Carica questo utente
              </button>
            </div>
          )}

          {meta?.users && meta.users.length > 0 && tab === "user" && (
            <div className="mb-4">
              <p className="mb-2 text-xs font-bold uppercase text-gray-500">Utenti con file esistente</p>
              <div className="flex flex-wrap gap-2">
                {meta.users.map((u) => (
                  <button
                    key={u}
                    type="button"
                    onClick={() => {
                      setUserId(u);
                      setLoading(true);
                      apiFetch(
                        `${apiBase()}/admin/profile-memory/${encodeURIComponent(slug)}/users/${encodeURIComponent(u)}`,
                        { headers: authHeaders(false) }
                      )
                        .then((r) => r.json())
                        .then((j) => setUserMd(j.content ?? ""))
                        .finally(() => setLoading(false));
                    }}
                    className="rounded-full border border-[#333] bg-[#1a1a1a] px-3 py-1.5 text-xs font-mono text-violet-300 hover:border-violet-500/50"
                  >
                    {u}
                  </button>
                ))}
              </div>
            </div>
          )}

          {tab === "soul" && (
            <p className="mb-3 text-sm text-gray-500">
              Definisce tono e comportamento base dell’agente per questo profilo. Viene letto all’inizio del prompt se il file esiste.
            </p>
          )}
          {tab === "memory" && (
            <p className="mb-3 text-sm text-gray-500">
              Note operative condivise tra tutte le sessioni di questo profilo (non legate a un singolo login utente).
            </p>
          )}
          {tab === "user" && (
            <p className="mb-3 text-sm text-gray-500">
              Preferenze dell’utente finale (linguaggio, formato risposte, vincoli). Un file per combinazione profilo + utente.
            </p>
          )}

          <div className="relative">
            <textarea
              value={tab === "soul" ? soul : tab === "memory" ? memory : userMd}
              onChange={(e) => {
                const v = e.target.value;
                if (tab === "soul") setSoul(v);
                else if (tab === "memory") setMemory(v);
                else setUserMd(v);
              }}
              disabled={!slug}
              className="min-h-[280px] w-full resize-y rounded-xl border border-[#333] bg-[#080808] px-4 py-4 font-mono text-sm leading-relaxed text-gray-200 outline-none focus:border-violet-500/60"
              spellCheck={false}
            />
            <div className="mt-2 flex justify-between text-[11px] text-gray-500">
              <span>
                {tab === "soul" && `${soulChars} / ${limits.soul}`}
                {tab === "memory" && `${memChars} / ${limits.mem}`}
                {tab === "user" && `${userChars} / ${limits.user}`}
                {" · "}caratteri
              </span>
              {loading && (
                <span className="flex items-center gap-1 text-violet-400">
                  <Loader2 className="h-3 w-3 animate-spin" /> Salvataggio…
                </span>
              )}
            </div>
          </div>

          <div className="mt-6 flex flex-wrap gap-3">
            <button
              type="button"
              disabled={!slug || loading}
              onClick={async () => {
                setLoading(true);
                try {
                  if (tab === "soul") await put("/soul", { content: soul });
                  else if (tab === "memory") await put("/memory", { content: memory });
                  else {
                    await put(`/users/${encodeURIComponent(userId.trim() || "default")}`, { content: userMd });
                  }
                  await loadMeta();
                  show("Salvato con successo.");
                } catch (e: unknown) {
                  show(e instanceof Error ? e.message : String(e), "error");
                } finally {
                  setLoading(false);
                }
              }}
              className="inline-flex items-center gap-2 rounded-xl bg-violet-600 px-6 py-3 text-sm font-bold text-white hover:bg-violet-500 disabled:opacity-50"
            >
              <Save className="h-4 w-4" />
              Salva {tab === "soul" ? "SOUL" : tab === "memory" ? "MEMORY" : "USER"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
