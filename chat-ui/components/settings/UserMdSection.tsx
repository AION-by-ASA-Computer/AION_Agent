"use client";

import { AlertTriangle, HelpCircle, Save } from "lucide-react";

import { ProfileOptionGrid } from "@/components/chat/ProfileOptionGrid";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";
import { SettingsCard } from "./SettingsCard";

export function UserMdSection({
  userId,
  profiles,
  selectedProfile,
  onProfileChange,
  loadingProfiles,
  userMdContent,
  onUserMdChange,
  loadingUserMd,
  savingUserMd,
  isOverLimit,
  charCount,
  onRestoreDefault,
  onSave,
}: {
  userId: string;
  profiles: Array<{ name: string; slug: string; description?: string }>;
  selectedProfile: string;
  onProfileChange: (slug: string) => void;
  loadingProfiles: boolean;
  userMdContent: string;
  onUserMdChange: (value: string) => void;
  loadingUserMd: boolean;
  savingUserMd: boolean;
  isOverLimit: boolean;
  charCount: number;
  onRestoreDefault: () => void;
  onSave: () => void;
}) {
  const t = useT();

  return (
    <SettingsCard
      title={t("settings.usermd.title")}
      description={t("settings.usermd.desc")}
      icon={<HelpCircle className="h-4.5 w-4.5" aria-hidden />}
    >
      <div className="mb-4 flex justify-end">
        <span className="rounded-md border border-border/40 bg-muted/50 px-2.5 py-1 font-mono text-[10px] text-muted-foreground">
          ID: {userId}
        </span>
      </div>

      <div className="space-y-2 pb-4">
        <label className="text-[10px] font-bold tracking-wider uppercase text-muted-foreground/80">
          {t("settings.usermd.profile_label")}
        </label>
        {loadingProfiles ? (
          <p className="text-xs italic text-muted-foreground">{t("settings.usermd.profile_loading")}</p>
        ) : (
          <ProfileOptionGrid
            profiles={profiles}
            value={selectedProfile}
            onChange={onProfileChange}
            emptyLabel={t("settings.usermd.profile_none")}
          />
        )}
      </div>

      <div className="relative">
        <textarea
          value={userMdContent}
          onChange={(e) => onUserMdChange(e.target.value)}
          placeholder={
            loadingUserMd ? t("settings.usermd.loading_placeholder") : t("settings.usermd.placeholder")
          }
          disabled={loadingUserMd}
          className={cn(
            "min-h-[280px] w-full resize-y rounded-2xl border bg-background/40 px-4 py-4 font-mono text-xs leading-relaxed text-foreground outline-none transition",
            isOverLimit
              ? "border-destructive bg-destructive/5 focus:border-destructive focus:ring-destructive"
              : "border-border/50 focus:border-primary focus:ring-1 focus:ring-primary",
            loadingUserMd && "pointer-events-none opacity-60",
          )}
          spellCheck={false}
        />
        {loadingUserMd ? (
          <div className="absolute inset-0 flex items-center justify-center rounded-2xl bg-background/10 backdrop-blur-[1px]">
            <div className="flex items-center gap-2 rounded-xl border border-border/40 bg-card/90 px-4 py-2 shadow-lg">
              <div className="h-4 w-4 animate-spin rounded-full border-2 border-primary border-t-transparent" />
              <span className="text-xs font-semibold">{t("settings.usermd.loading_overlay")}</span>
            </div>
          </div>
        ) : null}
        {isOverLimit && !loadingUserMd ? (
          <div className="absolute top-3 right-3 flex items-center gap-1 rounded border border-destructive/20 bg-destructive/10 px-2.5 py-1 text-[10px] font-bold text-destructive">
            <AlertTriangle size={11} aria-hidden />
            <span>{t("settings.usermd.overlimit")}</span>
          </div>
        ) : null}
      </div>

      <div className="mt-2 flex items-center justify-between px-1 text-[11px] text-muted-foreground">
        <span>{t("settings.usermd.markdown_hint")}</span>
        <span className={cn("font-mono", isOverLimit && "font-bold text-destructive")}>
          {t("settings.usermd.chars", { count: charCount })}
        </span>
      </div>

      <div className="mt-4 flex justify-end gap-2.5">
        <button
          type="button"
          onClick={onRestoreDefault}
          disabled={loadingUserMd || savingUserMd}
          className="focus-ring rounded-xl border border-border bg-card/40 px-4 py-2.5 text-xs font-semibold text-muted-foreground transition hover:bg-muted hover:text-foreground disabled:opacity-50"
        >
          {t("settings.usermd.btn.restore")}
        </button>
        <button
          type="button"
          onClick={onSave}
          disabled={isOverLimit || loadingUserMd || savingUserMd || !selectedProfile}
          className="focus-ring inline-flex items-center gap-1.5 rounded-xl bg-primary px-5 py-2.5 text-xs font-bold text-primary-foreground transition hover:bg-primary/90 disabled:opacity-50"
        >
          {savingUserMd ? (
            <div className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-primary-foreground border-t-transparent" />
          ) : (
            <Save size={14} aria-hidden />
          )}
          <span>{savingUserMd ? t("settings.usermd.btn.saving") : t("settings.usermd.btn.save")}</span>
        </button>
      </div>
    </SettingsCard>
  );
}
