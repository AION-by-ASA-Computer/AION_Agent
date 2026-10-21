"use client";

import { useCallback, useEffect, useLayoutEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  FileText,
  KeyRound,
  Loader2,
  Palette,
  Settings,
  ShieldCheck,
  SlidersHorizontal,
  User,
} from "lucide-react";

import { ApiKeysSection } from "@/components/settings/ApiKeysSection";
import { AppearanceSection } from "@/components/settings/AppearanceSection";
import { ChangePasswordSection } from "@/components/settings/ChangePasswordSection";
import { ProfileAvatarEditor } from "@/components/settings/ProfileAvatarEditor";
import { SettingsNav, type SettingsTab } from "@/components/settings/SettingsNav";
import { TuningsSettingsSection } from "@/components/settings/TuningsSettingsSection";
import { UserMdSection } from "@/components/settings/UserMdSection";
import {
  Field,
  FieldGrid,
  Group,
  Note,
  SaveBar,
  SectionHead,
  Toast,
  inputCls,
  type ToastState,
} from "@/components/settings/ui";
import { ShellSectionHeader } from "@/components/layout/ShellSectionHeader";
import { useStoredToken, useStoredUserId } from "@/lib/auth/use-stored-auth";
import { apiBase } from "@/lib/config";
import { cn } from "@/lib/cn";
import { detectBrowserLocale, setLocale, type Locale } from "@/lib/i18n/i18n-store";
import {
  notifyProfileAppearanceUpdated,
  type UserAppearanceMetadata,
} from "@/lib/profile/user-appearance";
import { useShellActions } from "@/lib/shell/shell-context";
import { useT } from "@/lib/i18n/use-t";

const USER_MD_LIMIT = 1400;

type AccountFields = { display_name: string; identifier: string; email: string };
const EMPTY_ACCOUNT: AccountFields = { display_name: "", identifier: "", email: "" };

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
  if (tab === "api-keys" || tab === "api_keys" || tab === "apikeys") return "api-keys";
  if (tab === "tunings" || tab === "tuning" || tab === "runtime" || tab === "presets") return "tunings";
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
  const [selectedLanguage, setSelectedLanguage] = useState<Locale | string>("en");

  // Account fields are drafts until the save bar commits them; `accountBase` is the server copy.
  const [accountBase, setAccountBase] = useState<AccountFields>(EMPTY_ACCOUNT);
  const [account, setAccount] = useState<AccountFields>(EMPTY_ACCOUNT);
  const [mustChangePassword, setMustChangePassword] = useState(false);
  const [profileColor, setProfileColor] = useState("violet");
  const [avatarUrl, setAvatarUrl] = useState("");
  const [savingAppearance, setSavingAppearance] = useState(false);

  const [profiles, setProfiles] = useState<Array<{ name: string; slug: string; description?: string }>>([]);
  const [selectedProfile, setSelectedProfile] = useState("");
  const [loadingProfiles, setLoadingProfiles] = useState(false);
  const [userMdContent, setUserMdContent] = useState("");
  // null until the server copy for the selected profile has loaded.
  const [userMdBase, setUserMdBase] = useState<string | null>(null);
  const [loadingUserMd, setLoadingUserMd] = useState(false);

  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState<ToastState>(null);

  const navItems = useMemo(
    () => [
      { id: "profile" as const, label: t("settings.tab.profile"), icon: User },
      { id: "appearance" as const, label: t("settings.tab.appearance"), icon: Palette },
      { id: "security" as const, label: t("settings.tab.security"), icon: ShieldCheck },
      ...(currentToken
        ? [{ id: "api-keys" as const, label: t("settings.tab.api_keys"), icon: KeyRound }]
        : []),
      { id: "instructions" as const, label: t("settings.tab.instructions"), icon: FileText },
      { id: "tunings" as const, label: t("settings.tab.tunings"), icon: SlidersHorizontal },
    ],
    [t, currentToken],
  );

  const showToast = useCallback((message: string, variant: "success" | "error" = "success") => {
    setToast({ message, variant });
  }, []);
  const dismissToast = useCallback(() => setToast(null), []);

  const applyUserData = useCallback(
    (
      data: {
        identifier?: string;
        display_name?: string;
        email?: string;
        metadata?: UserAppearanceMetadata;
        must_change_password?: boolean;
      },
      resetDraft: boolean,
    ) => {
      const fields = {
        display_name: data.display_name || "",
        identifier: data.identifier || "",
        email: data.email || "",
      };
      setAccountBase(fields);
      if (resetDraft) setAccount(fields);
      setMustChangePassword(Boolean(data.must_change_password));
      setProfileColor(data.metadata?.profile_color || "violet");
      setAvatarUrl(data.metadata?.avatar_url || "");
    },
    [],
  );

  const reloadUser = useCallback(async () => {
    if (!currentToken) return;
    const res = await fetch(`${apiBase()}/auth/me`, {
      headers: { Authorization: `Bearer ${currentToken}` },
    });
    if (!res.ok) return;
    const data = await res.json();
    applyUserData(data, true);
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
      setUserMdBase(null);
      let content = "";
      try {
        const res = await fetch(
          `${apiBase()}/admin/profile-memory/${encodeURIComponent(selectedProfile)}/users/${encodeURIComponent(currentUserId)}`,
          { headers: { Authorization: currentToken ? `Bearer ${currentToken}` : "" } },
        );
        if (res.ok) {
          const data = await res.json();
          content = data.content || "";
        }
      } catch {
        // An unreachable profile reads as empty instructions.
      } finally {
        setUserMdContent(content);
        setUserMdBase(content);
        setLoadingUserMd(false);
      }
    };
    void fetchUserMd();
    localStorage.setItem("aion_chat_selected_profile_user_md", selectedProfile);
  }, [selectedProfile, currentUserId, currentToken, mounted]);

  const accountDirty =
    account.display_name !== accountBase.display_name ||
    account.identifier !== accountBase.identifier ||
    account.email !== accountBase.email;
  const userMdDirty = userMdBase !== null && userMdContent !== userMdBase;
  const dirty = accountDirty || userMdDirty;

  const usernameMissing = accountDirty && !account.identifier.trim();
  const isOverLimit = userMdContent.length > USER_MD_LIMIT;
  const canSave = dirty && !saving && !usernameMissing && !(userMdDirty && isOverLimit);

  const saveAccount = useCallback(async (): Promise<boolean> => {
    if (!currentToken) {
      showToast(t("toast.no_token"), "error");
      return false;
    }
    const changed: Partial<Record<keyof AccountFields, string | null>> = {};
    for (const key of Object.keys(account) as (keyof AccountFields)[]) {
      if (account[key] !== accountBase[key]) changed[key] = account[key].trim() || null;
    }
    try {
      const res = await fetch(`${apiBase()}/auth/me`, {
        method: "PATCH",
        headers: { Authorization: `Bearer ${currentToken}`, "Content-Type": "application/json" },
        body: JSON.stringify(changed),
      });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        showToast((errData as { detail?: string }).detail || t("toast.server_error"), "error");
        return false;
      }
      applyUserData(await res.json(), true);
      notifyProfileAppearanceUpdated();
      return true;
    } catch {
      showToast(t("toast.conn_error"), "error");
      return false;
    }
  }, [account, accountBase, applyUserData, currentToken, showToast, t]);

  const saveUserMd = useCallback(async (): Promise<boolean> => {
    if (!selectedProfile) {
      showToast(t("toast.usermd_no_profile"), "error");
      return false;
    }
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
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        showToast((errData as { detail?: string }).detail || t("toast.server_error"), "error");
        return false;
      }
      localStorage.setItem("aion_chat_user_instructions", userMdContent);
      setUserMdBase(userMdContent);
      return true;
    } catch {
      showToast(t("toast.conn_error"), "error");
      return false;
    }
  }, [currentToken, currentUserId, selectedProfile, showToast, t, userMdContent]);

  const save = useCallback(async () => {
    if (!canSave) return;
    setSaving(true);
    let ok = true;
    if (accountDirty) ok = await saveAccount();
    if (ok && userMdDirty) ok = await saveUserMd();
    setSaving(false);
    if (ok) showToast(t("settings.ui.saved"));
  }, [accountDirty, canSave, saveAccount, saveUserMd, showToast, t, userMdDirty]);

  const discard = useCallback(() => {
    setAccount(accountBase);
    if (userMdBase !== null) setUserMdContent(userMdBase);
  }, [accountBase, userMdBase]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "s" && dirty) {
        e.preventDefault();
        void save();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [dirty, save]);

  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const saveAppearanceMetadata = async (partial: UserAppearanceMetadata) => {
    if (!currentToken) return;
    setSavingAppearance(true);
    try {
      const res = await fetch(`${apiBase()}/auth/me`, {
        method: "PATCH",
        headers: { Authorization: `Bearer ${currentToken}`, "Content-Type": "application/json" },
        body: JSON.stringify({ metadata: partial }),
      });
      if (!res.ok) {
        showToast(t("toast.server_error"), "error");
        return;
      }
      // Photo and colour save on their own; keep any account edits that are still drafts.
      applyUserData(await res.json(), false);
      notifyProfileAppearanceUpdated();
      showToast(t("settings.profile.appearance_saved"));
    } catch {
      showToast(t("toast.conn_error"), "error");
    } finally {
      setSavingAppearance(false);
    }
  };

  const setField = (key: keyof AccountFields) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setAccount((a) => ({ ...a, [key]: e.target.value }));

  const profileLabel = accountBase.display_name || accountBase.identifier || currentUserId;

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
      <div className="settings-scope flex min-h-0 flex-1 items-center justify-center gap-2 bg-background text-sm text-muted-foreground" role="status">
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
        {t("settings.ui.loading")}
      </div>
    );
  }

  return (
    <div className="settings-scope flex min-h-0 w-full flex-1 flex-col overflow-y-auto bg-background text-sm text-foreground">
      <div className="mx-auto w-full max-w-[calc(72rem*var(--settings-k))] flex-1 px-4 pb-16 pt-6 sm:px-6 sm:pt-8 lg:px-8">
        <header className="pb-6">
          <h1 className="text-balance text-2xl font-semibold tracking-[-0.02em] sm:text-3xl">{t("settings.title")}</h1>
          <p className="mt-1 max-w-[62ch] text-sm text-muted-foreground">{t("settings.subtitle")}</p>
        </header>

        <div className="grid gap-6 lg:grid-cols-[13rem_minmax(0,1fr)] lg:gap-10">
          <SettingsNav
            label={t("settings.ui.nav")}
            activeTab={activeTab}
            onChange={(tab) => {
              setActiveTab(tab);
              router.replace(`/settings?tab=${tab}`, { scroll: false });
            }}
            items={navItems}
          />

          <div className="flex min-w-0 flex-col gap-5">
            {activeTab === "profile" && currentToken ? (
              <>
                <SectionHead title={t("settings.profile.title")} description={t("settings.profile.desc")} />
                <Group title={t("settings.profile.photo_title")} description={t("settings.profile.photo_hint")}>
                  <ProfileAvatarEditor
                    label={profileLabel}
                    profileColor={profileColor}
                    avatarUrl={avatarUrl}
                    saving={savingAppearance}
                    onError={(msg) => showToast(msg, "error")}
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
                </Group>
                <Group title={t("settings.profile.details_title")} description={t("settings.profile.details_desc")}>
                  <FieldGrid>
                    <Field label={t("settings.field.displayname")}>
                      <input
                        type="text"
                        value={account.display_name}
                        onChange={setField("display_name")}
                        placeholder={t("settings.placeholder.displayname")}
                        autoComplete="name"
                        className={inputCls}
                      />
                    </Field>
                    <Field
                      label={t("settings.field.username")}
                      hint={
                        usernameMissing ? (
                          <span className="text-destructive">{t("toast.username_empty")}</span>
                        ) : (
                          t("settings.profile.username_hint")
                        )
                      }
                    >
                      <input
                        type="text"
                        value={account.identifier}
                        onChange={setField("identifier")}
                        placeholder={t("settings.placeholder.username")}
                        autoComplete="username"
                        spellCheck={false}
                        aria-invalid={usernameMissing || undefined}
                        className={cn(inputCls, usernameMissing && "border-destructive/60")}
                      />
                    </Field>
                    <Field label={t("settings.field.email")}>
                      <input
                        type="email"
                        value={account.email}
                        onChange={setField("email")}
                        placeholder={t("settings.placeholder.email")}
                        autoComplete="email"
                        spellCheck={false}
                        className={inputCls}
                      />
                    </Field>
                  </FieldGrid>
                </Group>
              </>
            ) : null}

            {activeTab === "appearance" ? <AppearanceSection onLanguageSaved={(msg) => showToast(msg)} /> : null}

            {activeTab === "security" && currentToken ? (
              <>
                <SectionHead title={t("settings.tab.security")} description={t("settings.security.desc")} />
                {mustChangePassword ? (
                  <Note tone="warn">
                    <p className="font-medium text-foreground">{t("settings.security.must_change_title")}</p>
                    <p className="mt-0.5">{t("settings.security.must_change_desc")}</p>
                  </Note>
                ) : null}
                <ChangePasswordSection
                  onSuccess={(msg) => {
                    setMustChangePassword(false);
                    showToast(msg);
                  }}
                />
              </>
            ) : null}

            {activeTab === "api-keys" && currentToken ? <ApiKeysSection onToast={showToast} /> : null}

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
                limit={USER_MD_LIMIT}
                profileLocked={userMdDirty}
                onRestoreDefault={() =>
                  setUserMdContent(
                    DEFAULT_USER_MD_BY_LANG[selectedLanguage as string] || DEFAULT_USER_MD_BY_LANG.en,
                  )
                }
              />
            ) : null}

            {activeTab === "tunings" ? (
              <TuningsSettingsSection
                initialTab={
                  searchParams.get("tab") === "presets" || searchParams.get("sub") === "presets"
                    ? "presets"
                    : "runtime"
                }
              />
            ) : null}
          </div>
        </div>
      </div>

      {dirty ? (
        <SaveBar
          label={t("settings.ui.unsaved")}
          discardLabel={t("settings.ui.discard")}
          saveLabel={t("settings.ui.save")}
          savingLabel={t("settings.ui.saving")}
          saving={saving}
          canSave={canSave}
          onDiscard={discard}
          onSave={() => void save()}
        />
      ) : null}

      <Toast toast={toast} onDismiss={dismissToast} dismissLabel={t("settings.ui.dismiss")} />
    </div>
  );
}
