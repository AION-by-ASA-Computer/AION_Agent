"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Brain, Cpu, Globe, Loader2, Mail, RotateCcw, Save, ScanLine, ShieldCheck, Timer } from "lucide-react";
import { apiFetch } from "@/lib/api/headers";
import { apiBase } from "@/lib/api";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";
import { probeBaseUrlFromOcrServiceUrl } from "@/lib/llm-probe";
import { PageToast, type ToastState } from "@/components/PageToast";
import { outlineBtn, solidBtn } from "@/components/ui/classes";
import { ModelsSection } from "@/components/settings/ModelsSection";
import { MemorySection } from "@/components/settings/MemorySection";
import { WebSection } from "@/components/settings/WebSection";
import { OcrSection, clearedOcr, type OcrMode } from "@/components/settings/OcrSection";
import { SandboxSection } from "@/components/settings/SandboxSection";
import { RetentionSection } from "@/components/settings/RetentionSection";
import { SmtpSection } from "@/components/settings/SmtpSection";
import { K, type Notify, type SectionCtx, type Settings } from "@/components/settings/types";

const k = K;

const SECTIONS = [
  { id: "models", icon: Cpu },
  { id: "memory", icon: Brain },
  { id: "web", icon: Globe },
  { id: "ocr", icon: ScanLine },
  { id: "sandbox", icon: ShieldCheck },
  { id: "retention", icon: Timer },
  { id: "smtp", icon: Mail },
] as const;
type SectionId = (typeof SECTIONS)[number]["id"];

// Models, Sandbox and SMTP persist on their own; the rest saves through the page bar.
const SELF_SAVING: SectionId[] = ["models", "sandbox", "smtp"];

const isSection = (v: string): v is SectionId => SECTIONS.some((s) => s.id === v);
const positive = (v: string | undefined) => {
  if (!v) return true;
  const n = parseInt(v, 10);
  return !isNaN(n) && n > 0;
};

export default function SettingsPage() {
  const t = useT();
  const [settings, setSettings] = useState<Settings>({});
  const [baseline, setBaseline] = useState<{ settings: Settings; ocrMode: OcrMode } | null>(null);
  const [ocrMode, setOcrMode] = useState<OcrMode>("local");
  const [rev, setRev] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);
  const [saving, setSaving] = useState(false);
  const [restarting, setRestarting] = useState(false);
  const [toast, setToast] = useState<ToastState>(null);
  const [active, setActive] = useState<SectionId>("models");
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const notify: Notify = useCallback((message, variant = "info") => setToast({ message, variant }), []);

  const fetchSettings = useCallback(async () => {
    try {
      const res = await apiFetch(`${apiBase()}/admin/settings`);
      if (!res.ok) throw new Error(String(res.status));
      const data = await res.json();
      const s: Settings = data.settings || {};
      const mode: OcrMode = (s.AION_OCR_BASE_URL || "").trim() ? "remote" : "local";
      setSettings(s);
      setOcrMode(mode);
      setBaseline({ settings: s, ocrMode: mode });
      setRev((r) => r + 1);
      setLoadFailed(false);
    } catch {
      setLoadFailed(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch on mount
    void fetchSettings();
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [fetchSettings]);

  // Section follows the URL hash so a link can open a given section.
  useEffect(() => {
    const read = () => {
      const h = window.location.hash.replace("#", "");
      if (isSection(h)) setActive(h);
    };
    read();
    window.addEventListener("hashchange", read);
    return () => window.removeEventListener("hashchange", read);
  }, []);

  const go = (id: SectionId) => {
    setActive(id);
    history.replaceState(null, "", `#${id}`);
  };

  const set = useCallback((key: string, value: string) => setSettings((p) => ({ ...p, [key]: value })), []);
  const setMany = useCallback((patch: Settings) => setSettings((p) => ({ ...p, ...patch })), []);

  const dirty = useMemo(() => {
    if (!baseline) return false;
    if (ocrMode !== baseline.ocrMode) return true;
    const keys = new Set([...Object.keys(baseline.settings), ...Object.keys(settings)]);
    for (const key of keys) if ((baseline.settings[key] ?? "") !== (settings[key] ?? "")) return true;
    return false;
  }, [baseline, settings, ocrMode]);

  const pollHealth = useCallback(async () => {
    const max = 30;
    let attempt = 0;
    await new Promise((r) => setTimeout(r, 2000));
    pollRef.current = setInterval(async () => {
      attempt++;
      try {
        const res = await fetch(`${apiBase()}/health`);
        if (res.ok && (await res.json()).status === "ok") {
          if (pollRef.current) clearInterval(pollRef.current);
          setRestarting(false);
          notify(t(`${k}.page.restarted`), "success");
          void fetchSettings();
          return;
        }
      } catch {
        /* backend still coming back */
      }
      if (attempt >= max) {
        if (pollRef.current) clearInterval(pollRef.current);
        setRestarting(false);
        notify(t(`${k}.page.restart_slow`), "error");
        void fetchSettings();
      }
    }, 1500);
  }, [fetchSettings, notify, t]);

  const onRestart = useCallback(() => {
    setRestarting(true);
    void pollHealth();
  }, [pollHealth]);

  const validate = (): string | null => {
    if (ocrMode === "remote") {
      const url = (settings.AION_OCR_BASE_URL || "").trim();
      if (url) {
        const base = probeBaseUrlFromOcrServiceUrl(url);
        if (!base || !/^https?:\/\//.test(base)) return t(`${k}.page.v_ocr_url`);
      }
      if (!positive(settings.AION_OCR_MAX_TOKENS)) return t(`${k}.page.v_ocr_tokens`);
      if (!positive(settings.AION_OCR_TIMEOUT)) return t(`${k}.page.v_ocr_timeout`);
      if (!positive(settings.AION_OCR_MAX_IMAGE_BYTES)) return t(`${k}.page.v_ocr_bytes`);
    }
    const emb = (settings.AION_EMBEDDING_URL || "").trim();
    if (emb && !/^https?:\/\//.test(emb)) return t(`${k}.page.v_emb_url`);
    if (!positive(settings.AION_WEB_FETCH_MAX_CHARS)) return t(`${k}.page.v_fetch_chars`);
    if (!positive(settings.AION_WEB_SEARCH_MAX_RESULTS)) return t(`${k}.page.v_search_results`);
    if (!positive(settings.AION_WEB_SEARCH_TIMEOUT_SEC)) return t(`${k}.page.v_search_timeout`);
    return null;
  };

  const save = useCallback(async () => {
    const problem = validate();
    if (problem) return notify(problem, "error");
    setSaving(true);
    const payload = { ...settings, ...(ocrMode === "local" ? clearedOcr() : {}) };
    try {
      const res = await apiFetch(`${apiBase()}/admin/settings`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ settings: payload }),
      });
      if (res.ok) {
        const data = await res.json();
        if (data.restarting) onRestart();
        else {
          notify(t(`${k}.page.saved`), "success");
          void fetchSettings();
        }
      } else {
        const err = await res.json().catch(() => ({}));
        notify(err.detail || t(`${k}.page.err_save`), "error");
      }
    } catch {
      notify(t(`${k}.page.err_network`), "error");
    } finally {
      setSaving(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settings, ocrMode, fetchSettings, notify, onRestart, t]);

  const discard = () => {
    if (!baseline) return;
    setSettings(baseline.settings);
    setOcrMode(baseline.ocrMode);
    setRev((r) => r + 1);
  };

  // Ctrl/Cmd+S saves the page instead of the browser's "save page".
  const canSave = dirty && !saving && !restarting;
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && !e.altKey && e.key.toLowerCase() === "s") {
        e.preventDefault();
        if (canSave) void save();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [canSave, save]);

  // Leaving with unsaved edits asks the browser to confirm.
  useEffect(() => {
    if (!dirty) return;
    const onLeave = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", onLeave);
    return () => window.removeEventListener("beforeunload", onLeave);
  }, [dirty]);

  const ctx: SectionCtx = { t, settings, set, setMany, notify, onRestart };
  const usesBar = !SELF_SAVING.includes(active);

  if (loading) {
    return (
      <div className="flex h-[50vh] items-center justify-center gap-2 text-sm text-muted-foreground" role="status">
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
        {t(`${k}.page.loading`)}
      </div>
    );
  }

  if (loadFailed) {
    return (
      <div className="mx-auto flex max-w-md flex-col items-start gap-3 py-24">
        <h1 className="text-xl font-semibold tracking-[-0.02em]">{t(`${k}.page.load_failed`)}</h1>
        <p className="text-sm text-muted-foreground">{t(`${k}.page.load_failed_hint`)}</p>
        <button type="button" className={outlineBtn} onClick={() => { setLoading(true); void fetchSettings(); }}>
          <RotateCcw className="h-3.5 w-3.5" aria-hidden />
          {t(`${k}.page.retry`)}
        </button>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-6xl pb-24">
      <header className="pb-6">
        <h1 className="text-balance text-2xl font-semibold tracking-[-0.02em] sm:text-3xl">{t(`${k}.page.title`)}</h1>
        <p className="mt-1 max-w-[62ch] text-sm text-muted-foreground">{t(`${k}.page.subtitle`)}</p>
      </header>

      <div className="grid gap-6 lg:grid-cols-[13rem_minmax(0,1fr)] lg:gap-10">
        <nav aria-label={t(`${k}.page.nav`)} className="-mx-4 overflow-x-auto px-4 lg:mx-0 lg:overflow-visible lg:px-0">
          <ul className="flex gap-1 lg:sticky lg:top-6 lg:flex-col">
            {SECTIONS.map(({ id, icon: Icon }) => (
              <li key={id} className="shrink-0">
                <button
                  type="button"
                  onClick={() => go(id)}
                  aria-current={active === id ? "page" : undefined}
                  className={cn(
                    "focus-ring flex w-full items-center gap-2.5 whitespace-nowrap rounded-xl px-3 py-2 text-sm transition-colors",
                    active === id ? "bg-secondary font-medium text-foreground" : "text-muted-foreground hover:bg-secondary/50 hover:text-foreground",
                  )}
                >
                  <Icon className="h-4 w-4 shrink-0" aria-hidden />
                  {t(`${k}.nav.${id}`)}
                </button>
              </li>
            ))}
          </ul>
        </nav>

        <div className="min-w-0">
          {/* All sections stay mounted so connection tests and drafts survive switching tabs. */}
          <div hidden={active !== "models"}><ModelsSection t={t} notify={notify} /></div>
          <div hidden={active !== "memory"}><MemorySection key={`m${rev}`} {...ctx} /></div>
          <div hidden={active !== "web"}><WebSection {...ctx} /></div>
          <div hidden={active !== "ocr"}><OcrSection key={`o${rev}`} {...ctx} mode={ocrMode} setMode={setOcrMode} /></div>
          <div hidden={active !== "sandbox"}><SandboxSection t={t} notify={notify} onRestart={onRestart} /></div>
          <div hidden={active !== "retention"}><RetentionSection {...ctx} /></div>
          <div hidden={active !== "smtp"}><SmtpSection t={t} notify={notify} /></div>
        </div>
      </div>

      {usesBar && dirty && (
        <div className="fixed inset-x-0 bottom-0 z-30 border-t border-border bg-background/95 px-4 py-3 lg:left-[var(--sidebar-width,0px)]">
          <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-end gap-3">
            <span className="mr-auto text-sm text-muted-foreground" role="status">{t(`${k}.page.unsaved`)}</span>
            <button type="button" className={outlineBtn} onClick={discard} disabled={saving}>
              {t(`${k}.page.discard`)}
            </button>
            <button type="button" className={solidBtn} onClick={() => void save()} disabled={!canSave}>
              {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <Save className="h-3.5 w-3.5" aria-hidden />}
              {saving ? t(`${k}.page.saving`) : t(`${k}.page.save`)}
            </button>
          </div>
        </div>
      )}

      {restarting && (
        <div role="alertdialog" aria-modal="true" aria-labelledby="restart-title" className="fixed inset-0 z-50 flex items-center justify-center bg-background/90 p-6">
          <div className="flex max-w-sm flex-col items-center gap-3 text-center">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" aria-hidden />
            <h2 id="restart-title" className="text-lg font-semibold">{t(`${k}.page.restarting`)}</h2>
            <p className="text-sm text-muted-foreground">{t(`${k}.page.restarting_hint`)}</p>
          </div>
        </div>
      )}

      <PageToast toast={toast} onDismiss={() => setToast(null)} />
    </div>
  );
}
