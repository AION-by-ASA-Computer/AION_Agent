"use client";

import { useCallback, useEffect, useLayoutEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import {
  AlertTriangle,
  Check,
  CheckCircle,
  FileText,
  LogOut,
  Palette,
  Settings,
  ShieldCheck,
  User,
} from "lucide-react";

import { AppearanceSection } from "@/components/settings/AppearanceSection";
import { ChangePasswordSection } from "@/components/settings/ChangePasswordSection";
import { ProfileAvatarEditor } from "@/components/settings/ProfileAvatarEditor";
import { SettingsCard, SettingsFieldRow } from "@/components/settings/SettingsCard";
import { SettingsNav, type SettingsTab } from "@/components/settings/SettingsNav";
import { UserMdSection } from "@/components/settings/UserMdSection";
import { ShellSectionHeader } from "@/components/layout/ShellSectionHeader";
import { useStoredToken, useStoredUserId } from "@/lib/auth/use-stored-auth";
import { setStoredAuth } from "@/lib/auth/storage";
import { apiBase } from "@/lib/config";
import { cn } from "@/lib/cn";
import { detectBrowserLocale, setLocale, type Locale } from "@/lib/i18n/i18n-store";
import {
  notifyProfileAppearanceUpdated,
  type UserAppearanceMetadata,
} from "@/lib/profile/user-appearance";
import { useShellActions } from "@/lib/shell/shell-context";
import { useT } from "@/lib/i18n/use-t";

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

function tabFromSearchParam(tab: string | null): SettingsTab {
  if (tab === "user-md" || tab === "instructions") return "instructions";
  if (tab === "appearance") return "appearance";
  if (tab === "security") return "security";
  return "profile";
}

export default function SettingsPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { setHeader, setDock, setDockOpen, clearChrome } = useShellActions();
  const currentUserId = useStoredUserId();
  const currentToken = useStoredToken();
  const t = useT();

  const [mounted, setMounted] = useState(false);
  const [activeTab, setActiveTab] = useState<SettingsTab>("profile");

  const [userMdContent, setUserMdContent] = useState("");
  const [selectedLanguage, setSelectedLanguage] = useState<Locale | string>("en");

  const [backendIdentifier, setBackendIdentifier] = useState("");
  const [backendDisplayName, setBackendDisplayName] = useState("");
  const [backendEmail, setBackendEmail] = useState("");
  const [mustChangePassword, setMustChangePassword] = useState(false);
  const [profileColor, setProfileColor] = useState("violet");
  const [avatarUrl, setAvatarUrl] = useState("");
  const [savingAppearance, setSavingAppearance] = useState(false);

  const [profiles, setProfiles] = useState<Array<{ name: string; slug: string; description?: string }>>([]);
  const [selectedProfile, setSelectedProfile] = useState("");
  const [loadingProfiles, setLoadingProfiles] = useState(false);
  const [loadingUserMd, setLoadingUserMd] = useState(false);
  const [savingUserMd, setSavingUserMd] = useState(false);

  const [toastMessage, setToastMessage] = useState<string | null>(null);
  const [toastType, setToastType] = useState<"success" | "error">("success");

  const navItems = useMemo(
    () => [
      { id: "profile" as const, label: t("settings.tab.profile"), icon: User },
      { id: "appearance" as const, label: t("settings.tab.appearance"), icon: Palette },
      { id: "security" as const, label: t("settings.tab.security"), icon: ShieldCheck },
      { id: "instructions" as const, label: t("settings.tab.instructions"), icon: FileText },
    ],
    [t],
  );

  const showToast = useCallback((msg: string, type: "success" | "error" = "success") => {
    setToastMessage(msg);
    setToastType(type);
    window.setTimeout(() => setToastMessage(null), 3000);
  }, []);

  const applyUserData = useCallback((data: {
    identifier?: string;
    display_name?: string;
    email?: string;
    metadata?: UserAppearanceMetadata;
    must_change_password?: boolean;
  }) => {
    setBackendIdentifier(data.identifier || "");
    setBackendDisplayName(data.display_name || "");
    setBackendEmail(data.email || "");
    setMustChangePassword(Boolean(data.must_change_password));
    setProfileColor(data.metadata?.profile_color || "violet");
    setAvatarUrl(data.metadata?.avatar_url || "");
  }, []);

  const reloadUser = useCallback(async () => {
    if (!currentToken) return;
    const res = await fetch(`${apiBase()}/auth/me`, {
      headers: { Authorization: `Bearer ${currentToken}` },
    });
    if (!res.ok) return;
    const data = await res.json();
    applyUserData(data);
    if (data.metadata?.language) {
      const lang = data.metadata.language;
      if (["it", "en", "es", "fr", "de"].includes(lang)) {
        setSelectedLanguage(lang);
        setLocale(lang as Locale);
        localStorage.setItem("aion_chat_language", lang);
      }
    }
  }, [applyUserData, currentToken]);

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    if (mounted && !currentToken) {
      router.replace("/login");
    }
  }, [mounted, currentToken, router]);

  useEffect(() => {
    setActiveTab(tabFromSearchParam(searchParams.get("tab")));
  }, [searchParams]);

  useEffect(() => {
    if (!mounted) return;

    const storedLang = localStorage.getItem("aion_chat_language") || detectBrowserLocale();
    if (["it", "en", "es", "fr", "de"].includes(storedLang)) {
      setSelectedLanguage(storedLang);
    }

    const storedUserMd = localStorage.getItem("aion_chat_user_instructions");
    const defaultText = DEFAULT_USER_MD_BY_LANG[storedLang] || DEFAULT_USER_MD_BY_LANG.en;
    setUserMdContent(storedUserMd || defaultText);

    void reloadUser();
  }, [mounted, reloadUser]);

  useEffect(() => {
    if (!mounted) return;
    const fetchProfilesList = async () => {
      setLoadingProfiles(true);
      try {
        const res = await fetch(`${apiBase()}/profiles`, {
          headers: { Authorization: currentToken ? `Bearer ${currentToken}` : "" },
        });
        if (res.ok) {
          const data = await res.json();
          setProfiles(data);
          if (data.length > 0) {
            const storedProfile = localStorage.getItem("aion_chat_selected_profile_user_md");
            const initialProfile = data.find((p: { slug: string }) => p.slug === storedProfile) || data[0];
            setSelectedProfile(initialProfile.slug);
          }
        }
      } catch (err) {
        console.error("Errore recupero profili:", err);
      } finally {
        setLoadingProfiles(false);
      }
    };
    void fetchProfilesList();
  }, [mounted, currentToken]);

  useEffect(() => {
    if (!mounted || !selectedProfile || !currentUserId) return;
    const fetchUserMd = async () => {
      setLoadingUserMd(true);
      try {
        const res = await fetch(
          `${apiBase()}/admin/profile-memory/${encodeURIComponent(selectedProfile)}/users/${encodeURIComponent(currentUserId)}`,
          { headers: { Authorization: currentToken ? `Bearer ${currentToken}` : "" } },
        );
        if (res.ok) {
          const data = await res.json();
          setUserMdContent(data.content || "");
        } else {
          setUserMdContent("");
        }
      } catch {
        setUserMdContent("");
      } finally {
        setLoadingUserMd(false);
      }
    };
    void fetchUserMd();
    localStorage.setItem("aion_chat_selected_profile_user_md", selectedProfile);
  }, [selectedProfile, currentUserId, currentToken, mounted]);

  const handleUpdateProfileField = async (
    field: "identifier" | "display_name" | "email",
    value: string,
  ) => {
    const trimmed = value.trim();
    if (field === "identifier" && !trimmed) {
      showToast(t("toast.username_empty"), "error");
      return;
    }
    if (!currentToken) {
      showToast(t("toast.no_token"), "error");
      return;
    }
    try {
      const res = await fetch(`${apiBase()}/auth/me`, {
        method: "PATCH",
        headers: {
          Authorization: `Bearer ${currentToken}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ [field]: trimmed || null }),
      });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        showToast((errData as { detail?: string }).detail || t("toast.server_error"), "error");
        return;
      }
      const data = await res.json();
      applyUserData(data);
      notifyProfileAppearanceUpdated();
      const fieldLabel =
        field === "identifier"
          ? t("field.username")
          : field === "display_name"
            ? t("field.displayname")
            : t("field.email");
      showToast(t("toast.field_updated", { field: fieldLabel }));
    } catch {
      showToast(t("toast.conn_error"), "error");
    }
  };

  const saveAppearanceMetadata = async (partial: UserAppearanceMetadata) => {
    if (!currentToken) return;
    setSavingAppearance(true);
    try {
      const res = await fetch(`${apiBase()}/auth/me`, {
        method: "PATCH",
        headers: {
          Authorization: `Bearer ${currentToken}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ metadata: partial }),
      });
      if (!res.ok) {
        showToast(t("toast.server_error"), "error");
        return;
      }
      const data = await res.json();
      applyUserData(data);
      notifyProfileAppearanceUpdated();
      showToast(t("settings.profile.appearance_saved"));
    } catch {
      showToast(t("toast.conn_error"), "error");
    } finally {
      setSavingAppearance(false);
    }
  };

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
            Authorization: currentToken ? `Bearer ${currentToken}` : "",
          },
          body: JSON.stringify({ content: userMdContent }),
        },
      );
      if (res.ok) {
        localStorage.setItem("aion_chat_user_instructions", userMdContent);
        showToast(t("toast.usermd_saved"));
      } else {
        const errData = await res.json().catch(() => ({}));
        showToast((errData as { detail?: string }).detail || t("toast.server_error"), "error");
      }
    } catch {
      showToast(t("toast.conn_error"), "error");
    } finally {
      setSavingUserMd(false);
    }
  };

  const handleLogout = () => {
    setStoredAuth(null, "default");
    window.dispatchEvent(new Event("storage"));
    showToast(t("toast.logout"));
    router.push("/login");
  };

  const charCount = userMdContent.length;
  const isOverLimit = charCount > 1400;
  const profileLabel = backendDisplayName || backendIdentifier || currentUserId;
  const inputClass =
    "focus-ring w-full rounded-xl border border-border/50 bg-background/50 px-3.5 py-2.5 text-sm text-foreground outline-none transition focus:border-primary focus:ring-1 focus:ring-primary";

  useLayoutEffect(() => {
    setHeader(
      <ShellSectionHeader
        title={t("settings.title")}
        icon={<Settings className="h-5 w-5" aria-hidden />}
      />,
    );
    setDock(null);
    setDockOpen(false);
  }, [setHeader, setDock, setDockOpen, t]);

  useLayoutEffect(() => () => clearChrome(), [clearChrome]);

  if (!mounted) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background text-foreground">
        <div className="h-5 w-5 animate-spin rounded-full border-2 border-primary border-t-transparent" />
      </div>
    );
  }

  return (
    <div className="flex min-h-0 w-full flex-1 flex-col overflow-y-auto bg-background text-foreground">
      <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-8 md:py-10">
        <div className="mb-6">
          <h1 className="text-lg font-semibold tracking-tight">{t("settings.title")}</h1>
          <p className="mt-1 text-sm text-muted-foreground">{t("settings.subtitle")}</p>
        </div>

        <div className="grid gap-8 md:grid-cols-[220px_1fr]">
          <SettingsNav
            activeTab={activeTab}
            onChange={setActiveTab}
            items={navItems}
          />

          <div className="min-h-[400px] space-y-6">
            {activeTab === "profile" && currentToken ? (
              <>
                <SettingsCard
                  title={t("settings.profile.title")}
                  description={t("settings.profile.desc")}
                  icon={<User className="h-4.5 w-4.5" aria-hidden />}
                >
                  <ProfileAvatarEditor
                    label={profileLabel}
                    profileColor={profileColor}
                    avatarUrl={avatarUrl}
                    saving={savingAppearance}
                    onColorChange={(colorId) => {
                      setProfileColor(colorId);
                      void saveAppearanceMetadata({ profile_color: colorId, avatar_url: avatarUrl || undefined });
                    }}
                    onAvatarChange={(dataUrl) => {
                      setAvatarUrl(dataUrl);
                      void saveAppearanceMetadata({ profile_color: profileColor, avatar_url: dataUrl });
                    }}
                    onAvatarRemove={() => {
                      setAvatarUrl("");
                      void saveAppearanceMetadata({ profile_color: profileColor, avatar_url: "" });
                    }}
                  />

                  <div className="mt-6 space-y-1">
                    <SettingsFieldRow label={t("settings.field.displayname")}>
                      <div className="flex gap-2">
                        <input
                          type="text"
                          value={backendDisplayName}
                          onChange={(e) => setBackendDisplayName(e.target.value)}
                          placeholder={t("settings.placeholder.displayname")}
                          className={inputClass}
                        />
                        <button
                          type="button"
                          onClick={() => void handleUpdateProfileField("display_name", backendDisplayName)}
                          className="focus-ring shrink-0 rounded-xl bg-primary px-4 py-2.5 text-xs font-semibold text-primary-foreground hover:bg-primary/90"
                        >
                          <Check className="h-4 w-4" aria-hidden />
                        </button>
                      </div>
                    </SettingsFieldRow>

                    <SettingsFieldRow
                      label={t("settings.field.username")}
                      hint={t("settings.profile.username_hint")}
                    >
                      <div className="flex gap-2">
                        <input
                          type="text"
                          value={backendIdentifier}
                          onChange={(e) => setBackendIdentifier(e.target.value)}
                          placeholder={t("settings.placeholder.username")}
                          className={inputClass}
                        />
                        <button
                          type="button"
                          onClick={() => void handleUpdateProfileField("identifier", backendIdentifier)}
                          className="focus-ring shrink-0 rounded-xl bg-primary px-4 py-2.5 text-xs font-semibold text-primary-foreground hover:bg-primary/90"
                        >
                          <Check className="h-4 w-4" aria-hidden />
                        </button>
                      </div>
                    </SettingsFieldRow>

                    <SettingsFieldRow label={t("settings.field.email")}>
                      <div className="flex gap-2">
                        <input
                          type="email"
                          value={backendEmail}
                          onChange={(e) => setBackendEmail(e.target.value)}
                          placeholder={t("settings.placeholder.email")}
                          className={inputClass}
                        />
                        <button
                          type="button"
                          onClick={() => void handleUpdateProfileField("email", backendEmail)}
                          className="focus-ring shrink-0 rounded-xl bg-primary px-4 py-2.5 text-xs font-semibold text-primary-foreground hover:bg-primary/90"
                        >
                          <Check className="h-4 w-4" aria-hidden />
                        </button>
                      </div>
                    </SettingsFieldRow>
                  </div>
                </SettingsCard>

                <SettingsCard title={t("settings.profile.shortcuts_title")} description={t("settings.profile.shortcuts_desc")}>
                  <Link
                    href="/schedules"
                    className="inline-flex items-center gap-2 rounded-xl border border-border/50 bg-muted/30 px-4 py-3 text-sm font-medium transition hover:bg-muted/50"
                  >
                    {t("sidebar.schedules")}
                  </Link>
                </SettingsCard>
              </>
            ) : null}

            {activeTab === "appearance" ? (
              <SettingsCard
                title={t("settings.appearance.title")}
                description={t("settings.appearance.desc")}
                icon={<Palette className="h-4.5 w-4.5" aria-hidden />}
              >
                <AppearanceSection onLanguageSaved={(msg) => showToast(msg)} />
              </SettingsCard>
            ) : null}

            {activeTab === "security" && currentToken ? (
              <>
                {mustChangePassword ? (
                  <div className="flex items-start gap-3 rounded-2xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-900 dark:text-amber-100">
                    <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
                    <div>
                      <p className="font-semibold">{t("settings.security.must_change_title")}</p>
                      <p className="mt-1 text-xs opacity-90">{t("settings.security.must_change_desc")}</p>
                    </div>
                  </div>
                ) : null}

                <SettingsCard
                  title={t("settings.security.password_title")}
                  description={t("settings.security.password_desc")}
                  icon={<ShieldCheck className="h-4.5 w-4.5" aria-hidden />}
                >
                  <ChangePasswordSection
                    onSuccess={(msg) => {
                      setMustChangePassword(false);
                      showToast(msg);
                    }}
                  />
                </SettingsCard>

                <SettingsCard title={t("settings.section.session.title")}>
                  <button
                    type="button"
                    onClick={handleLogout}
                    className="focus-ring inline-flex items-center gap-2 rounded-xl border border-destructive/20 bg-destructive/5 px-4 py-2.5 text-xs font-semibold text-destructive transition hover:bg-destructive/10"
                  >
                    <LogOut className="h-4 w-4" aria-hidden />
                    {t("settings.btn.logout")}
                  </button>
                </SettingsCard>
              </>
            ) : null}

            {activeTab === "instructions" ? (
              <UserMdSection
                userId={currentUserId}
                profiles={profiles}
                selectedProfile={selectedProfile}
                onProfileChange={setSelectedProfile}
                loadingProfiles={loadingProfiles}
                userMdContent={userMdContent}
                onUserMdChange={setUserMdContent}
                loadingUserMd={loadingUserMd}
                savingUserMd={savingUserMd}
                isOverLimit={isOverLimit}
                charCount={charCount}
                onRestoreDefault={() =>
                  setUserMdContent(
                    DEFAULT_USER_MD_BY_LANG[selectedLanguage as string] || DEFAULT_USER_MD_BY_LANG.en,
                  )
                }
                onSave={() => void handleSaveUserMd()}
              />
            ) : null}
          </div>
        </div>
      </main>

      {toastMessage ? (
        <div
          className={cn(
            "fixed bottom-5 right-5 z-50 flex items-center gap-2.5 rounded-xl border px-4 py-3.5 text-xs font-semibold shadow-lg backdrop-blur-md",
            toastType === "success"
              ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
              : "border-destructive/30 bg-destructive/10 text-destructive",
          )}
        >
          {toastType === "success" ? (
            <CheckCircle className="h-4 w-4" aria-hidden />
          ) : (
            <AlertTriangle className="h-4 w-4" aria-hidden />
          )}
          <span>{toastMessage}</span>
        </div>
      ) : null}
    </div>
  );
}
