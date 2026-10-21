"use client";

import { Loader2, RotateCcw } from "lucide-react";

import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";
import { Select } from "./Select";
import { Group, Mono, SectionHead, outlineBtn } from "./ui";

/** USER.md editor for one agent profile. Saving goes through the page's save bar. */
export function UserMdSection({
  userId,
  profiles,
  selectedProfile,
  onProfileChange,
  loadingProfiles,
  userMdContent,
  onUserMdChange,
  loadingUserMd,
  limit,
  profileLocked,
  onRestoreDefault,
}: {
  userId: string;
  profiles: Array<{ name: string; slug: string; description?: string }>;
  selectedProfile: string;
  onProfileChange: (slug: string) => void;
  loadingProfiles: boolean;
  userMdContent: string;
  onUserMdChange: (value: string) => void;
  loadingUserMd: boolean;
  limit: number;
  /** Unsaved edits belong to the selected profile, so switching waits for save or discard. */
  profileLocked?: boolean;
  onRestoreDefault: () => void;
}) {
  const t = useT();
  const charCount = userMdContent.length;
  const isOverLimit = charCount > limit;
  const profileHint = profileLocked
    ? t("settings.usermd.profile_locked")
    : profiles.find((p) => p.slug === selectedProfile)?.description || null;

  return (
    <>
      <SectionHead title={t("settings.usermd.title")} description={t("settings.usermd.desc")} />

      <Group
        footer={
          <button type="button" onClick={onRestoreDefault} disabled={loadingUserMd} className={outlineBtn}>
            <RotateCcw className="h-3.5 w-3.5" aria-hidden />
            {t("settings.usermd.btn.restore")}
          </button>
        }
      >
        <div className="flex flex-col gap-4 px-5 py-5 md:flex-row md:items-start md:gap-6">
          <div className="flex min-w-0 flex-col gap-1.5 md:w-80">
            <span className="text-sm font-medium">
              {t("settings.usermd.profile_label")}
            </span>
            {loadingProfiles ? (
              <p className="flex items-center gap-2 py-2.5 text-sm text-muted-foreground">
                <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
                {t("settings.usermd.profile_loading")}
              </p>
            ) : profiles.length === 0 ? (
              <p className="py-2.5 text-sm text-muted-foreground">{t("settings.usermd.profile_none")}</p>
            ) : (
              <Select
                aria-label={t("settings.usermd.profile_label")}
                value={selectedProfile}
                onChange={onProfileChange}
                disabled={profileLocked}
                options={profiles.map((p) => ({ value: p.slug, label: p.name || p.slug, description: p.description }))}
              />
            )}
            {profileHint ? <p className="text-xs text-muted-foreground">{profileHint}</p> : null}
          </div>
          <div className="flex min-w-0 flex-col gap-1.5 md:ml-auto md:items-end md:text-right">
            <span className="text-xs text-muted-foreground">{t("settings.usermd.user_id")}</span>
            <Mono className="truncate">{userId}</Mono>
          </div>
        </div>

        <div className="border-t border-border/60 px-5 py-5">
          <label className="flex flex-col gap-1.5">
            <span className="text-sm font-medium">USER.md</span>
            <div className="relative">
              <textarea
                value={userMdContent}
                onChange={(e) => onUserMdChange(e.target.value)}
                placeholder={t("settings.usermd.placeholder")}
                disabled={loadingUserMd}
                aria-invalid={isOverLimit || undefined}
                aria-describedby="usermd-count"
                spellCheck={false}
                className={cn(
                  "focus-ring block min-h-72 w-full resize-y rounded-xl border bg-background px-4 py-3.5 font-mono text-[0.893rem] leading-relaxed text-foreground transition-colors placeholder:text-muted-foreground/70 disabled:opacity-60",
                  isOverLimit
                    ? "border-destructive/60 focus:border-destructive"
                    : "border-border hover:border-foreground/25 focus:border-foreground/40",
                )}
              />
              {loadingUserMd ? (
                <div className="absolute inset-0 flex items-center justify-center gap-2 rounded-xl text-sm text-muted-foreground" role="status">
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                  {t("settings.usermd.loading_overlay")}
                </div>
              ) : null}
            </div>
          </label>
          <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
            <span className="mr-auto">{t("settings.usermd.markdown_hint")}</span>
            <span id="usermd-count" className={cn("font-mono tabular-nums", isOverLimit && "font-medium text-destructive")}>
              {isOverLimit ? `${t("settings.usermd.overlimit")} · ` : ""}
              {t("settings.usermd.chars", { count: charCount })}
            </span>
          </div>
        </div>
      </Group>
    </>
  );
}
