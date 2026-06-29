"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  ArrowLeft,
  Settings,
  User,
  CheckCircle,
  AlertTriangle,
  FileText,
  HelpCircle,
  LogOut,
  Save,
  Check,
  ShieldCheck,
  ChevronDown,
  Clock,
} from "lucide-react";
import { useStoredUserId, useStoredToken } from "@/lib/auth/use-stored-auth";
import { setStoredAuth } from "@/lib/auth/storage";
import { cn } from "@/lib/cn";
import { apiBase } from "@/lib/config";
import { useT } from "@/lib/i18n/use-t";
import { detectBrowserLocale, setLocale, type Locale } from "@/lib/i18n/i18n-store";
import { syncLanguagePreferenceToServer } from "@/lib/i18n/sync-language";

// Template di istruzioni di default se non presenti in localStorage per ciascuna lingua
const DEFAULT_USER_MD_BY_LANG: Record<string, string> = {
  it: `# Le mie preferenze ed istruzioni
- Preferisci spiegazioni chiare e concise strutturate con elenchi puntati.
- Quando scrivi del codice, aggiungi commenti esplicativi in italiano.
- Organizza i dati complessi o le metriche in tabelle Markdown.
- Mantieni un tono professionale ma amichevole.
`,
  en: `# My preferences and instructions
- Prefer clear and concise explanations structured with bullet points.
- When writing code, add explanatory comments in English.
- Organize complex data or metrics in Markdown tables.
- Maintain a professional but friendly tone.
`,
  es: `# Mis preferencias e instrucciones
- Prefiere explicaciones claras y concisas estructuradas con viñetas.
- Al escribir código, añade comentarios explicativos en español.
- Organiza datos complejos o métricas en tablas Markdown.
- Mantén un tono profesional pero amable.
`,
  fr: `# Mes préférences et instructions
- Préfère des explications claires et concises structurées avec des puces.
- Lors de l'écriture de code, ajoute des commentaires explicatifs en français.
- Organise les données complexes ou les métriques dans des tableaux Markdown.
- Maintiens un ton professionnel mais amical.
`,
  de: `# Meine Präferenzen und Anweisungen
- Bevorzuge klare und prägnante Erklärungen, die mit Aufzählungspunkten strukturiert sind.
- Füge beim Schreiben von Code erklärende Kommentare in Deutsch hinzu.
- Organisiere komplexe Daten oder Metriken in Markdown-Tabellen.
- Behalte einen professionellen, aber freundlichen Ton bei.
`,
};

export default function SettingsPage() {
  const router = useRouter();
  const currentUserId = useStoredUserId();
  const currentToken = useStoredToken();

  const t = useT();
  const [mounted, setMounted] = useState(false);
  const [activeTab, setActiveTab] = useState<"account" | "user-md">("account");

  // Stati per le impostazioni locali
  const [userIdInput, setUserIdInput] = useState("");
  const [userMdContent, setUserMdContent] = useState("");
  const [selectedLanguage, setSelectedLanguage] = useState<Locale | string>("en");
  const [isLangDropdownOpen, setIsLangDropdownOpen] = useState(false);

  // Stati per il profilo backend
  const [backendIdentifier, setBackendIdentifier] = useState("");
  const [backendDisplayName, setBackendDisplayName] = useState("");
  const [backendEmail, setBackendEmail] = useState("");

  // Stati per la gestione profili e USER.md da backend
  const [profiles, setProfiles] = useState<Array<{ name: string; slug: string; description?: string }>>([]);
  const [selectedProfile, setSelectedProfile] = useState<string>("");
  const [loadingProfiles, setLoadingProfiles] = useState(false);
  const [loadingUserMd, setLoadingUserMd] = useState(false);
  const [savingUserMd, setSavingUserMd] = useState(false);

  // Stati per feedback visivo
  const [toastMessage, setToastMessage] = useState<string | null>(null);
  const [toastType, setToastType] = useState<"success" | "error">("success");

  // Reindirizzamento se non loggati
  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    if (mounted && !currentToken) {
      router.replace("/login");
    }
  }, [mounted, currentToken, router]);

  // Inizializzazione stati da localStorage e backend
  useEffect(() => {
    if (!mounted) return;
    setUserIdInput(currentUserId);

    const storedLang = localStorage.getItem("aion_chat_language") || detectBrowserLocale();
    if (storedLang && ["it", "en", "es", "fr", "de"].includes(storedLang)) {
      setSelectedLanguage(storedLang);
    }

    const storedUserMd = localStorage.getItem("aion_chat_user_instructions");
    const defaultText = DEFAULT_USER_MD_BY_LANG[storedLang] || DEFAULT_USER_MD_BY_LANG["en"];
    setUserMdContent(storedUserMd || defaultText);

    if (currentToken) {
      const fetchUserData = async () => {
        try {
          const res = await fetch(`${apiBase()}/auth/me`, {
            headers: {
              "Authorization": `Bearer ${currentToken}`
            }
          });
          if (res.ok) {
            const data = await res.json();
            if (data.metadata?.language) {
              const lang = data.metadata.language;
              if (["it", "en", "es", "fr", "de"].includes(lang)) {
                setSelectedLanguage(lang);
                setLocale(lang as Locale);
                localStorage.setItem("aion_chat_language", lang);
                // Aggiorna istruzioni se sono quelle di default vecchie o vuote
                setUserMdContent((current) => {
                  const isDefault = Object.values(DEFAULT_USER_MD_BY_LANG).some(
                    (val) => val.trim() === current.trim()
                  );
                  if (isDefault || !current.trim()) {
                    return DEFAULT_USER_MD_BY_LANG[lang] || DEFAULT_USER_MD_BY_LANG["en"];
                  }
                  return current;
                });
              }
            } else if (currentToken) {
              const localLang = localStorage.getItem("aion_chat_language") || detectBrowserLocale();
              if (["it", "en", "es", "fr", "de"].includes(localLang)) {
                void syncLanguagePreferenceToServer(currentToken, localLang as Locale);
              }
            }
            setBackendIdentifier(data.identifier || "");
            setBackendDisplayName(data.display_name || "");
            setBackendEmail(data.email || "");
          }
        } catch (err) {
          console.error("Errore recupero preferenze:", err);
        }
      };
      fetchUserData();
    }
  }, [currentUserId, currentToken, mounted]);

  // Recupera l'elenco dei profili all'avvio
  useEffect(() => {
    if (!mounted) return;

    const fetchProfilesList = async () => {
      setLoadingProfiles(true);
      try {
        const res = await fetch(`${apiBase()}/profiles`, {
          headers: {
            "Authorization": currentToken ? `Bearer ${currentToken}` : "",
          },
        });
        if (res.ok) {
          const data = await res.json();
          setProfiles(data);
          if (data.length > 0) {
            const storedProfile = localStorage.getItem("aion_chat_selected_profile_user_md");
            const initialProfile = data.find((p: any) => p.slug === storedProfile) || data[0];
            setSelectedProfile(initialProfile.slug);
          }
        }
      } catch (err) {
        console.error("Errore recupero profili:", err);
      } finally {
        setLoadingProfiles(false);
      }
    };

    fetchProfilesList();
  }, [mounted, currentToken]);

  // Recupera USER.md quando cambia il profilo selezionato o l'utente
  useEffect(() => {
    if (!mounted || !selectedProfile || !currentUserId) return;

    const fetchUserMd = async () => {
      setLoadingUserMd(true);
      try {
        const res = await fetch(
          `${apiBase()}/admin/profile-memory/${encodeURIComponent(selectedProfile)}/users/${encodeURIComponent(currentUserId)}`,
          {
            headers: {
              "Authorization": currentToken ? `Bearer ${currentToken}` : "",
            },
          }
        );
        if (res.ok) {
          const data = await res.json();
          setUserMdContent(data.content || "");
        } else {
          setUserMdContent("");
        }
      } catch (err) {
        console.error("Errore recupero USER.md:", err);
        setUserMdContent("");
      } finally {
        setLoadingUserMd(false);
      }
    };

    fetchUserMd();
    localStorage.setItem("aion_chat_selected_profile_user_md", selectedProfile);
  }, [selectedProfile, currentUserId, currentToken, mounted]);

  const showToast = useCallback((msg: string, type: "success" | "error" = "success") => {
    setToastMessage(msg);
    setToastType(type);
    window.setTimeout(() => setToastMessage(null), 3000);
  }, []);


  const handleUpdateProfileField = async (
    field: "identifier" | "display_name" | "email",
    value: string
  ) => {
    const trimmed = value.trim();
    if (field === "identifier" && !trimmed) {
      showToast(t("toast.username_empty"), "error");
      return;
    }

    if (currentToken) {
      try {
        const res = await fetch(`${apiBase()}/auth/me`, {
          method: "PATCH",
          headers: {
            "Authorization": `Bearer ${currentToken}`,
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            [field]: trimmed || null,
          }),
        });

        if (res.ok) {
          const data = await res.json();
          setBackendIdentifier(data.identifier || "");
          setBackendDisplayName(data.display_name || "");
          setBackendEmail(data.email || "");

          let fieldLabel = "";
          if (field === "identifier") fieldLabel = t("field.username");
          else if (field === "display_name") fieldLabel = t("field.displayname");
          else if (field === "email") fieldLabel = t("field.email");

          showToast(t("toast.field_updated", { field: fieldLabel }));
        } else {
          const errData = await res.json();
          const errMsg = errData.detail || t("toast.server_error");
          showToast(errMsg, "error");
        }
      } catch (err) {
        console.error("Errore salvataggio profilo:", err);
        showToast(t("toast.conn_error"), "error");
      }
    } else {
      showToast(t("toast.no_token"), "error");
    }
  };


  // Salva la lingua preferita
  const handleSaveLanguage = async (lang: Locale) => {
    setSelectedLanguage(lang);
    setLocale(lang); // Aggiorna lo store globale

    // Se l'area di testo contiene le istruzioni predefinite di una delle lingue (o è vuota),
    // aggiorniamo l'area con la nuova lingua predefinita
    const isDefault = Object.values(DEFAULT_USER_MD_BY_LANG).some(
      (val) => val.trim() === userMdContent.trim()
    );
    if (isDefault || !userMdContent.trim()) {
      const nextDefault = DEFAULT_USER_MD_BY_LANG[lang] || DEFAULT_USER_MD_BY_LANG["en"];
      setUserMdContent(nextDefault);
    }

    if (currentToken) {
      const ok = await syncLanguagePreferenceToServer(currentToken, lang);
      if (ok) {
        showToast(t("toast.language_saved"));
      } else {
        showToast(t("toast.language_server_error"), "error");
      }
    } else {
      showToast(t("toast.language_local"));
    }
  };

  // Salva le istruzioni USER.md sul backend per il profilo selezionato
  const handleSaveUserMd = async () => {
    if (userMdContent.length > 1400) {
      showToast(t("toast.usermd_overlimit"), "error");
      return;
    }
    if (!selectedProfile) {
      showToast(t("toast.usermd_no_profile"), "error");
      return;
    }

    setSavingUserMd(true);
    try {
      const res = await fetch(
        `${apiBase()}/admin/profile-memory/${encodeURIComponent(selectedProfile)}/users/${encodeURIComponent(currentUserId)}`,
        {
          method: "PUT",
          headers: {
            "Content-Type": "application/json",
            "Authorization": currentToken ? `Bearer ${currentToken}` : "",
          },
          body: JSON.stringify({ content: userMdContent }),
        }
      );

      if (res.ok) {
        localStorage.setItem("aion_chat_user_instructions", userMdContent);
        showToast(t("toast.usermd_saved"));
      } else {
        const errData = await res.json().catch(() => ({}));
        const errMsg = errData.detail || t("toast.server_error");
        showToast(errMsg, "error");
      }
    } catch (err) {
      console.error("Errore salvataggio USER.md:", err);
      showToast(t("toast.conn_error"), "error");
    } finally {
      setSavingUserMd(false);
    }
  };

  const handleLogout = () => {
    setStoredAuth(null, "default");
    window.dispatchEvent(new Event("storage"));
    showToast(t("toast.logout"));
    setUserIdInput("default");
  };

  const charCount = userMdContent.length;
  const isOverLimit = charCount > 1400;

  if (!mounted) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background text-foreground">
        <div className="h-5 w-5 animate-spin rounded-full border-2 border-primary border-t-transparent" />
      </div>
    );
  }

  return (
    <div className="flex min-h-screen w-full flex-col bg-background text-foreground transition-colors duration-300">

      {/* Header Premium con sfocatura glassmorphism */}
      <header className="sticky top-0 z-40 w-full border-b border-border bg-card/70 px-4 py-3 backdrop-blur-md">
        <div className="mx-auto flex max-w-5xl items-center justify-between">
          <div className="flex items-center gap-3">
            <button
              onClick={() => router.back()}
              className="focus-ring flex h-8 w-8 items-center justify-center rounded-lg border border-border bg-muted/40 text-muted-foreground transition-all hover:bg-muted hover:text-foreground active:scale-95"
              title={t("settings.back")}
            >
              <ArrowLeft size={15} />
            </button>
            <div className="flex items-center gap-2">
              <Settings className="h-4.5 w-4.5 text-primary " />
              <h1 className="text-sm font-semibold tracking-tight text-foreground select-none">
                {t("settings.title")}
              </h1>
            </div>
          </div>
        </div>
      </header>

      {/* Main Container */}
      <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-8 md:py-12">
        <div className="grid gap-8 md:grid-cols-[220px_1fr]">

          {/* Sidebar interna delle impostazioni */}
          <nav className="flex flex-row md:flex-col gap-1 overflow-x-auto pr-5 pb-2 md:pb-0 border-b md:border-b-0 md:border-r border-border/50">
            <button
              onClick={() => setActiveTab("account")}
              className={cn(
                "flex items-center gap-2.5 rounded-lg px-3 py-2 text-xs font-semibold transition-all whitespace-nowrap md:w-full text-left",
                activeTab === "account"
                  ? "bg-primary/10 text-primary"
                  : "text-muted-foreground hover:bg-muted/50 hover:text-foreground"
              )}
            >
              <User size={18} />
              <span>{t("settings.tab.account")}</span>
            </button>

            <button
              onClick={() => setActiveTab("user-md")}
              className={cn(
                "flex items-center gap-2.5 rounded-lg px-3 py-2 text-xs font-semibold transition-all whitespace-nowrap md:w-full text-left",
                activeTab === "user-md"
                  ? "bg-primary/10 text-primary"
                  : "text-muted-foreground hover:bg-muted/50 hover:text-foreground"
              )}
            >
              <FileText size={18} />
              <span>{t("settings.tab.usermd")}</span>
            </button>
          </nav>

          {/* Area Contenuto */}
          <div className="min-h-[400px] flex flex-col gap-6">

            {/* TAB: Profilo & Account */}
            {activeTab === "account" && (
              <section className="space-y-6 animate-[fadeIn_0.2s_ease-out]">
                <div className="rounded-2xl border border-border/50 bg-card/50 backdrop-blur-xl p-6 space-y-4 shadow-sm hover:border-border/80 transition-all duration-300 relative z-20">
                  <div className="flex items-center gap-2 border-b border-border/50 pb-3">
                    <User className="h-4.5 w-4.5 text-primary" />
                    <h2 className="text-sm font-semibold text-foreground">{t("settings.section.profile.title")}</h2>
                  </div>
                  <p className="text-xs text-muted-foreground leading-relaxed">
                    {t("settings.section.profile.desc")}
                  </p>

                  {/* Impostazioni Profilo Backend (solo se autenticati) */}
                  {currentToken && (
                    <div className="space-y-4 pt-4 border-t border-border/40">

                      {/* Nome Utente */}
                      <div className="space-y-2 max-w-md">
                        <label className="text-[10px] font-bold tracking-wider uppercase text-muted-foreground/80">{t("settings.field.username")}</label>
                        <div className="flex gap-2.5">
                          <input
                            type="text"
                            value={backendIdentifier}
                            onChange={(e) => setBackendIdentifier(e.target.value)}
                            placeholder={t("settings.placeholder.username")}
                            className="flex-1 rounded-xl border border-border/50 bg-background/40 px-4 py-2.5 text-sm text-foreground outline-none focus:border-primary focus:ring-1 focus:ring-primary focus:bg-background/60 transition-all"
                          />
                          <button
                            onClick={() => handleUpdateProfileField("identifier", backendIdentifier)}
                            className="focus-ring flex items-center justify-center gap-1.5 rounded-xl bg-primary px-4 py-2.5 text-sm font-semibold text-primary-foreground shadow-sm transition hover:bg-primary/90 active:scale-98"
                          >
                            <Check size={15} aria-hidden />
                            <span>{t("settings.btn.update")}</span>
                          </button>
                        </div>
                      </div>

                      {/* Display Name */}
                      <div className="space-y-2 max-w-md">
                        <label className="text-[10px] font-bold tracking-wider uppercase text-muted-foreground/80">{t("settings.field.displayname")}</label>
                        <div className="flex gap-2.5">
                          <input
                            type="text"
                            value={backendDisplayName}
                            onChange={(e) => setBackendDisplayName(e.target.value)}
                            placeholder={t("settings.placeholder.displayname")}
                            className="flex-1 rounded-xl border border-border/50 bg-background/40 px-4 py-2.5 text-sm text-foreground outline-none focus:border-primary focus:ring-1 focus:ring-primary focus:bg-background/60 transition-all"
                          />
                          <button
                            onClick={() => handleUpdateProfileField("display_name", backendDisplayName)}
                            className="focus-ring flex items-center justify-center gap-1.5 rounded-xl bg-primary px-4 py-2.5 text-sm font-semibold text-primary-foreground shadow-sm transition hover:bg-primary/90 active:scale-98"
                          >
                            <Check size={15} aria-hidden />
                            <span>{t("settings.btn.update")}</span>
                          </button>
                        </div>
                      </div>

                      {/* Email */}
                      <div className="space-y-2 max-w-md">
                        <label className="text-[10px] font-bold tracking-wider uppercase text-muted-foreground/80">{t("settings.field.email")}</label>
                        <div className="flex gap-2.5">
                          <input
                            type="email"
                            value={backendEmail}
                            onChange={(e) => setBackendEmail(e.target.value)}
                            placeholder={t("settings.placeholder.email")}
                            className="flex-1 rounded-xl border border-border/50 bg-background/40 px-4 py-2.5 text-sm text-foreground outline-none focus:border-primary focus:ring-1 focus:ring-primary focus:bg-background/60 transition-all"
                          />
                          <button
                            onClick={() => handleUpdateProfileField("email", backendEmail)}
                            className="focus-ring flex items-center justify-center gap-1.5 rounded-xl bg-primary px-4 py-2.5 text-sm font-semibold text-primary-foreground shadow-sm transition hover:bg-primary/90 active:scale-98"
                          >
                            <Check size={15} aria-hidden />
                            <span>{t("settings.btn.update")}</span>
                          </button>
                        </div>
                      </div>
                    </div>
                  )}

                  {currentToken && (
                    <div className="pt-4 border-t border-border/40">
                      <Link
                        href="/schedules"
                        className="inline-flex items-center gap-2 rounded-xl border border-border/50 bg-muted/30 px-4 py-3 text-sm font-medium text-foreground hover:bg-muted/50 transition-colors"
                      >
                        <Clock size={16} aria-hidden />
                        {t("sidebar.schedules")}
                      </Link>
                    </div>
                  )}

                  {/* Lingua di Riferimento */}
                  <div className="space-y-2 max-w-md pt-4 border-t border-border/40 relative z-30">
                    <label className="text-[10px] font-bold tracking-wider uppercase text-muted-foreground/80">{t("settings.section.language.label")}</label>
                    <div className="relative">
                      {/* Dropdown Trigger */}
                      <button
                        type="button"
                        onClick={() => setIsLangDropdownOpen(!isLangDropdownOpen)}
                        className="flex w-full items-center justify-between gap-2.5 rounded-xl border border-border/50 bg-background/40 px-4 py-2.5 text-sm text-foreground outline-none focus:border-primary focus:ring-1 focus:ring-primary focus:bg-background/60 hover:bg-background/50 hover:border-border transition-all cursor-pointer select-none"
                      >
                        <div className="flex items-center gap-2.5">
                          <span className="text-base leading-none">
                            {(() => {
                              switch (selectedLanguage) {
                                case "en": return "🇬🇧";
                                case "es": return "🇪🇸";
                                case "fr": return "🇫🇷";
                                case "de": return "🇩🇪";
                                default: return "🇮🇹";
                              }
                            })()}
                          </span>
                          <span className="font-semibold text-xs text-foreground">
                            {(() => {
                              switch (selectedLanguage) {
                                case "en": return "English";
                                case "es": return "Español";
                                case "fr": return "Français";
                                case "de": return "Deutsch";
                                default: return "Italiano";
                              }
                            })()}
                          </span>
                        </div>
                        <ChevronDown
                          size={14}
                          className={cn(
                            "text-muted-foreground transition-transform duration-300",
                            isLangDropdownOpen && "rotate-180"
                          )}
                        />
                      </button>

                      {/* Dropdown Menu Overlay */}
                      {isLangDropdownOpen && (
                        <>
                          <div
                            className="fixed inset-0 z-40"
                            onClick={() => setIsLangDropdownOpen(false)}
                          />
                          <div className="absolute left-0 right-0 mt-1.5 z-50 rounded-xl border border-border/60 bg-card/95 backdrop-blur-xl p-1.5 shadow-xl animate-[fadeIn_0.15s_ease-out] flex flex-col gap-0.5">
                            {([
                              { code: "it", name: "Italiano", desc: "Italiano", flag: "🇮🇹" },
                              { code: "en", name: "English", desc: "Inglese", flag: "🇬🇧" },
                              { code: "es", name: "Español", desc: "Spagnolo", flag: "🇪🇸" },
                              { code: "fr", name: "Français", desc: "Francese", flag: "🇫🇷" },
                              { code: "de", name: "Deutsch", desc: "Tedesco", flag: "🇩🇪" },
                            ] as const).map((lang) => (
                              <button
                                key={lang.code}
                                type="button"
                                onClick={() => {
                                  handleSaveLanguage(lang.code);
                                  setIsLangDropdownOpen(false);
                                }}
                                className={cn(
                                  "flex items-center justify-between w-full rounded-lg px-3 py-2 text-xs font-semibold text-left transition-all cursor-pointer hover:bg-muted/50",
                                  selectedLanguage === lang.code
                                    ? "bg-primary/10 text-primary"
                                    : "text-muted-foreground hover:text-foreground"
                                )}
                              >
                                <div className="flex items-center gap-2.5">
                                  <span className="text-base leading-none">{lang.flag}</span>
                                  <span>{lang.name}</span>
                                </div>
                                {selectedLanguage === lang.code && (
                                  <Check size={14} className="text-primary" />
                                )}
                              </button>
                            ))}
                          </div>
                        </>
                      )}
                    </div>
                    <p className="text-[11px] text-muted-foreground mt-1.5 leading-normal">
                      {t("settings.section.language.desc")}
                    </p>
                  </div>
                </div>

                <div className="rounded-2xl border border-border/50 bg-card/50 backdrop-blur-xl p-6 space-y-4 shadow-sm hover:border-border/80 transition-all duration-300 relative z-10">
                  <div className="flex items-center gap-2 border-b border-border/50 pb-3">
                    <ShieldCheck className="h-4.5 w-4.5 text-primary" />
                    <h2 className="text-sm font-semibold text-foreground">{t("settings.section.session.title")}</h2>
                  </div>
                  {currentToken ? (
                    <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
                      <button
                        onClick={handleLogout}
                        className="focus-ring flex items-center gap-1.5 rounded-xl border border-destructive/20 bg-destructive/5 px-4 py-2.5 text-xs font-semibold text-destructive hover:bg-destructive/10 hover:border-destructive/30 transition-all active:scale-98"
                      >
                        <LogOut size={14} aria-hidden />
                        <span>{t("settings.btn.logout")}</span>
                      </button>
                    </div>
                  ) : (
                    <p className="text-xs text-muted-foreground italic">{t("settings.section.session.no_token")}</p>
                  )}
                </div>
              </section>
            )}

            {/* TAB: Le mie Istruzioni (USER.md) */}
            {activeTab === "user-md" && (
              <section className="space-y-4 animate-[fadeIn_0.2s_ease-out]">
                <div className="rounded-2xl border border-border/50 bg-card/50 backdrop-blur-xl p-6 space-y-4 shadow-sm hover:border-border/80 transition-all duration-300">
                  <div className="flex items-center justify-between border-b border-border/50 pb-3">
                    <div className="flex items-center gap-2">
                      <FileText className="h-4.5 w-4.5 text-primary" />
                      <h2 className="text-sm font-semibold text-foreground">{t("settings.usermd.title")}</h2>
                    </div>
                    <span className="text-[10px] text-muted-foreground font-mono bg-muted/60 px-2.5 py-1 rounded border border-border/40">
                      ID: {currentUserId}
                    </span>
                  </div>
                  <p className="text-xs text-muted-foreground leading-relaxed">
                    {t("settings.usermd.desc")}
                  </p>

                  {/* Profilo Select */}
                  <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pt-2 pb-1">
                    <div className="space-y-1.5 max-w-xs">
                      <label className="text-[10px] font-bold tracking-wider uppercase text-muted-foreground/80">{t("settings.usermd.profile_label")}</label>
                      <div className="relative">
                        <select
                          value={selectedProfile}
                          onChange={(e) => setSelectedProfile(e.target.value)}
                          disabled={loadingProfiles}
                          className="w-full appearance-none rounded-xl border border-border/50 bg-background/40 px-4 py-2.5 pr-10 text-xs font-semibold text-foreground outline-none focus:border-primary focus:ring-1 focus:ring-primary focus:bg-background/60 transition-all cursor-pointer"
                        >
                          {loadingProfiles && <option value="">{t("settings.usermd.profile_loading")}</option>}
                          {!loadingProfiles && profiles.length === 0 && <option value="">{t("settings.usermd.profile_none")}</option>}
                          {profiles.map((p) => (
                            <option key={p.slug} value={p.slug} className="bg-card text-foreground">
                              {p.name}
                            </option>
                          ))}
                        </select>
                        <div className="pointer-events-none absolute inset-y-0 right-3.5 flex items-center text-muted-foreground/80">
                          <ChevronDown size={14} />
                        </div>
                      </div>
                    </div>
                    {selectedProfile && (
                      <p className="text-[10.5px] text-muted-foreground/80 leading-normal italic sm:max-w-md">
                        {profiles.find(p => p.slug === selectedProfile)?.description || t("settings.usermd.profile_nodesc")}
                      </p>
                    )}
                  </div>

                  <div className="space-y-2 pt-2">
                    <div className="relative">
                      <textarea
                        value={userMdContent}
                        onChange={(e) => setUserMdContent(e.target.value)}
                        placeholder={loadingUserMd ? t("settings.usermd.loading_placeholder") : t("settings.usermd.placeholder")}
                        disabled={loadingUserMd}
                        className={cn(
                          "min-h-[280px] w-full resize-y rounded-2xl border bg-background/40 px-4 py-4 font-mono text-xs leading-relaxed text-foreground outline-none transition-all",
                          isOverLimit
                            ? "border-destructive focus:ring-destructive focus:border-destructive bg-destructive/5"
                            : "border-border/50 focus:border-primary focus:ring-1 focus:ring-primary focus:bg-background/60",
                          loadingUserMd && "opacity-60 pointer-events-none"
                        )}
                        spellCheck={false}
                      />
                      {loadingUserMd && (
                        <div className="absolute inset-0 flex items-center justify-center bg-background/10 backdrop-blur-[1px] rounded-2xl">
                          <div className="flex items-center gap-2 bg-card/90 border border-border/40 px-4 py-2 rounded-xl shadow-lg">
                            <div className="h-4 w-4 animate-spin rounded-full border-2 border-primary border-t-transparent" />
                            <span className="text-xs font-semibold text-foreground">{t("settings.usermd.loading_overlay")}</span>
                          </div>
                        </div>
                      )}
                      {isOverLimit && !loadingUserMd && (
                        <div className="absolute top-3 right-3 flex items-center gap-1 text-[10px] font-bold text-destructive bg-destructive/10 px-2.5 py-1 rounded border border-destructive/20 animate-pulse">
                          <AlertTriangle size={11} aria-hidden />
                          <span>{t("settings.usermd.overlimit")}</span>
                        </div>
                      )}
                    </div>

                    <div className="flex items-center justify-between text-[11px] text-muted-foreground mt-1 px-1">
                      <div className="flex items-center gap-1">
                        <HelpCircle size={12} className="text-muted-foreground/60" aria-hidden />
                        <span>{t("settings.usermd.markdown_hint")}</span>
                      </div>
                      <span className={cn("font-mono", isOverLimit ? "text-destructive font-bold" : "text-muted-foreground")}>
                        {t("settings.usermd.chars", { count: charCount })}
                      </span>
                    </div>
                  </div>

                  <div className="flex justify-end gap-2.5 pt-2">
                    <button
                      onClick={() => setUserMdContent(DEFAULT_USER_MD_BY_LANG[selectedLanguage] || DEFAULT_USER_MD_BY_LANG["en"])}
                      disabled={loadingUserMd || savingUserMd}
                      className="focus-ring border border-border bg-card/40 text-muted-foreground text-xs font-semibold py-2.5 px-4 rounded-xl hover:bg-muted hover:text-foreground active:scale-98 transition-all disabled:opacity-50"
                    >
                      {t("settings.usermd.btn.restore")}
                    </button>
                    <button
                      onClick={handleSaveUserMd}
                      disabled={isOverLimit || loadingUserMd || savingUserMd || !selectedProfile}
                      className="focus-ring flex items-center gap-1.5 rounded-xl bg-primary px-5 py-2.5 text-xs font-bold text-primary-foreground shadow-sm transition hover:bg-primary/90 disabled:opacity-50 active:scale-98"
                    >
                      {savingUserMd ? (
                        <div className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-primary-foreground border-t-transparent" />
                      ) : (
                        <Save size={14} aria-hidden />
                      )}
                      <span>{savingUserMd ? t("settings.usermd.btn.saving") : t("settings.usermd.btn.save")}</span>
                    </button>
                  </div>
                </div>
              </section>
            )}

          </div>
        </div>
      </main>

      {/* Floating Toast Notification */}
      {toastMessage && (
        <div
          className={cn(
            "fixed bottom-5 right-5 z-50 flex items-center gap-2.5 rounded-xl px-4 py-3.5 text-xs font-semibold shadow-lg border backdrop-blur-md animate-[slideUp_0.25s_ease-out]",
            toastType === "success"
              ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-600 dark:text-emerald-400"
              : "bg-destructive/10 border-destructive/30 text-destructive"
          )}
        >
          {toastType === "success" ? (
            <CheckCircle className="h-4 w-4" />
          ) : (
            <AlertTriangle className="h-4 w-4" />
          )}
          <span>{toastMessage}</span>
        </div>
      )}

      {/* CSS Animazioni inline specifiche */}
      <style jsx global>{`
        @keyframes fadeIn {
          from { opacity: 0; transform: translateY(4px); }
          to { opacity: 1; transform: translateY(0); }
        }
        @keyframes slideUp {
          from { opacity: 0; transform: translateY(12px); }
          to { opacity: 1; transform: translateY(0); }
        }
      `}</style>

    </div>
  );
}
