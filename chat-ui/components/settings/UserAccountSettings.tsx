"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { AlertTriangle, Check, LogOut } from "lucide-react";

import { AppearanceSection } from "@/components/settings/AppearanceSection";
import { ChangePasswordSection } from "@/components/settings/ChangePasswordSection";
import { ProfileAvatarEditor } from "@/components/settings/ProfileAvatarEditor";
import { SettingsCard, SettingsFieldRow } from "@/components/settings/SettingsCard";
import { UserMdSection } from "@/components/settings/UserMdSection";
import { useStoredToken, useStoredUserId } from "@/lib/auth/use-stored-auth";
import { setStoredAuth } from "@/lib/auth/storage";
import { apiBase } from "@/lib/config";
import { detectBrowserLocale, setLocale, type Locale } from "@/lib/i18n/i18n-store";
import {
  notifyProfileAppearanceUpdated,
  type UserAppearanceMetadata,
} from "@/lib/profile/user-appearance";
import { useT } from "@/lib/i18n/use-t";
import type { SettingsTab } from "@/components/settings/SettingsNav";

const DEFAULT_USER_MD_BY_LANG: Record<string, string> = {
  it: `# Le mie preferenze ed istruzioni\n- Preferisci spiegazioni chiare e concise.\n`,
  en: `# My preferences and instructions\n- Prefer clear and concise explanations.\n`,
  es: `# Mis preferencias e instrucciones\n- Prefiere explicaciones claras y concisas.\n`,
  fr: `# Mes préférences et instructions\n- Préfère des explications claires et concises.\n`,
  de: `# Meine Präferenzen und Anweisungen\n- Bevorzuge klare und prägnante Erklärungen.\n`,
};

const compactCard = "rounded-xl p-3 sm:p-3";

export function UserAccountSettings({ tab }: { tab: SettingsTab }) {
  const router = useRouter();
  const currentUserId = useStoredUserId();
  const currentToken = useStoredToken();
  const t = useT();

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

  const showToast = useCallback((msg: string) => {
    setToastMessage(msg);
    window.setTimeout(() => setToastMessage(null), 2500);
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
    if (data.metadata?.language && ["it", "en", "es", "fr", "de"].includes(data.metadata.language)) {
      setSelectedLanguage(data.metadata.language);
      setLocale(data.metadata.language as Locale);
    }
  }, [applyUserData, currentToken]);

  useEffect(() => {
    const storedLang = localStorage.getItem("aion_chat_language") || detectBrowserLocale();
    if (["it", "en", "es", "fr", "de"].includes(storedLang)) setSelectedLanguage(storedLang);
    void reloadUser();
  }, [reloadUser]);

  useEffect(() => {
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
            const initial = data.find((p: { slug: string }) => p.slug === storedProfile) || data[0];
            setSelectedProfile(initial.slug);
          }
        }
      } finally {
        setLoadingProfiles(false);
      }
    };
    void fetchProfilesList();
  }, [currentToken]);

  useEffect(() => {
    if (!selectedProfile || !currentUserId) return;
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
        } else setUserMdContent("");
      } catch {
        setUserMdContent("");
      } finally {
        setLoadingUserMd(false);
      }
    };
    void fetchUserMd();
  }, [selectedProfile, currentUserId, currentToken]);

  const handleUpdateProfileField = async (
    field: "identifier" | "display_name" | "email",
    value: string,
  ) => {
    if (!currentToken) return;
    const res = await fetch(`${apiBase()}/auth/me`, {
      method: "PATCH",
      headers: { Authorization: `Bearer ${currentToken}`, "Content-Type": "application/json" },
      body: JSON.stringify({ [field]: value.trim() || null }),
    });
    if (res.ok) {
      applyUserData(await res.json());
      notifyProfileAppearanceUpdated();
      showToast(t("toast.field_updated", { field }));
    }
  };

  const saveAppearanceMetadata = async (partial: UserAppearanceMetadata) => {
    if (!currentToken) return;
    setSavingAppearance(true);
    try {
      const res = await fetch(`${apiBase()}/auth/me`, {
        method: "PATCH",
        headers: { Authorization: `Bearer ${currentToken}`, "Content-Type": "application/json" },
        body: JSON.stringify({ metadata: partial }),
      });
      if (res.ok) {
        applyUserData(await res.json());
        notifyProfileAppearanceUpdated();
      }
    } finally {
      setSavingAppearance(false);
    }
  };

  const handleSaveUserMd = async () => {
    if (!selectedProfile || userMdContent.length > 1400) return;
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
      }
    } finally {
      setSavingUserMd(false);
    }
  };

  const inputClass =
    "focus-ring w-full rounded-lg border border-border/50 bg-background/50 px-2 py-1.5 text-xs";
  const profileLabel = backendDisplayName || backendIdentifier || currentUserId;

  return (
    <div className="space-y-3 px-1 pb-4">
      {tab === "profile" && currentToken ? (
        <SettingsCard title={t("settings.profile.title")} className={compactCard}>
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
          <SettingsFieldRow label={t("settings.field.displayname")}>
            <div className="flex gap-1">
              <input className={inputClass} value={backendDisplayName} onChange={(e) => setBackendDisplayName(e.target.value)} />
              <button type="button" onClick={() => void handleUpdateProfileField("display_name", backendDisplayName)} className="rounded-lg bg-primary p-2 text-primary-foreground">
                <Check className="h-3.5 w-3.5" />
              </button>
            </div>
          </SettingsFieldRow>
        </SettingsCard>
      ) : null}

      {tab === "appearance" ? (
        <SettingsCard title={t("settings.appearance.title")} className={compactCard}>
          <AppearanceSection onLanguageSaved={(msg) => showToast(msg)} />
        </SettingsCard>
      ) : null}

      {tab === "security" && currentToken ? (
        <>
          {mustChangePassword ? (
            <div className="flex gap-2 rounded-xl border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs">
              <AlertTriangle className="h-4 w-4 shrink-0" />
              {t("settings.security.must_change_title")}
            </div>
          ) : null}
          <SettingsCard title={t("settings.security.password_title")} className={compactCard}>
            <ChangePasswordSection onSuccess={(msg) => { setMustChangePassword(false); showToast(msg); }} />
          </SettingsCard>
          <button
            type="button"
            onClick={() => {
              setStoredAuth(null, "default");
              window.dispatchEvent(new Event("storage"));
              router.push("/login");
            }}
            className="inline-flex items-center gap-2 rounded-lg border border-destructive/20 px-3 py-2 text-xs font-semibold text-destructive"
          >
            <LogOut className="h-4 w-4" />
            {t("settings.btn.logout")}
          </button>
        </>
      ) : null}

      {tab === "instructions" ? (
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
          isOverLimit={userMdContent.length > 1400}
          charCount={userMdContent.length}
          onRestoreDefault={() =>
            setUserMdContent(DEFAULT_USER_MD_BY_LANG[selectedLanguage as string] || DEFAULT_USER_MD_BY_LANG.en)
          }
          onSave={() => void handleSaveUserMd()}
        />
      ) : null}

      {toastMessage ? (
        <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-2 py-1.5 text-[0.7rem] text-emerald-600">
          {toastMessage}
        </div>
      ) : null}
    </div>
  );
}
