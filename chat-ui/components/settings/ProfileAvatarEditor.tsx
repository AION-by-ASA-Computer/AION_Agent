"use client";

import { useRef } from "react";
import { Camera, Check, Trash2 } from "lucide-react";

import { cn } from "@/lib/cn";
import {
  PROFILE_ACCENT_COLORS,
  profileInitials,
  type UserAppearanceMetadata,
} from "@/lib/profile/user-appearance";
import { useT } from "@/lib/i18n/use-t";
import { ghostBtn, outlineBtn } from "./ui";

const MAX_AVATAR_BYTES = 256 * 1024;

export function ProfileAvatarEditor({
  label,
  metadata,
  profileColor,
  avatarUrl,
  saving,
  onColorChange,
  onAvatarChange,
  onAvatarRemove,
  onError,
}: {
  label: string;
  metadata?: UserAppearanceMetadata;
  profileColor: string;
  avatarUrl: string;
  saving?: boolean;
  onColorChange: (colorId: string) => void;
  onAvatarChange: (dataUrl: string) => void;
  onAvatarRemove: () => void;
  onError?: (message: string) => void;
}) {
  const t = useT();
  const fileRef = useRef<HTMLInputElement>(null);
  const initials = profileInitials(label);
  const activeColor =
    PROFILE_ACCENT_COLORS.find((c) => c.id === profileColor)?.value ||
    metadata?.profile_color ||
    PROFILE_ACCENT_COLORS[0].value;

  function handleFile(file: File) {
    if (!file.type.startsWith("image/")) return;
    if (file.size > MAX_AVATAR_BYTES) {
      const message = t("settings.profile.avatar_too_large");
      if (onError) onError(message);
      else alert(message);
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      if (typeof reader.result === "string") onAvatarChange(reader.result);
    };
    reader.readAsDataURL(file);
  }

  return (
    <div className="flex flex-col gap-6 px-5 py-5 md:flex-row md:items-center md:gap-10">
      <div className="flex items-center gap-4">
        <div
          className="flex h-16 w-16 shrink-0 items-center justify-center overflow-hidden rounded-full text-lg font-semibold text-white"
          style={{ backgroundColor: avatarUrl ? undefined : activeColor }}
        >
          {avatarUrl ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={avatarUrl} alt="" className="h-full w-full object-cover" />
          ) : (
            <span aria-hidden>{initials}</span>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" disabled={saving} onClick={() => fileRef.current?.click()} className={outlineBtn}>
            <Camera className="h-3.5 w-3.5" aria-hidden />
            {t("settings.profile.upload_photo")}
          </button>
          {avatarUrl ? (
            <button
              type="button"
              disabled={saving}
              onClick={onAvatarRemove}
              className={cn(ghostBtn, "hover:bg-destructive/10 hover:text-destructive")}
            >
              <Trash2 className="h-3.5 w-3.5" aria-hidden />
              {t("settings.profile.remove_photo")}
            </button>
          ) : null}
          <input
            ref={fileRef}
            type="file"
            accept="image/png,image/jpeg,image/webp,image/gif"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) handleFile(file);
              e.target.value = "";
            }}
          />
        </div>
      </div>

      <fieldset className="min-w-0 md:border-l md:border-border/60 md:pl-10">
        <legend className="mb-2.5 text-sm font-medium">{t("settings.profile.color_label")}</legend>
        <div className="flex flex-wrap gap-2.5">
          {PROFILE_ACCENT_COLORS.map((color) => {
            const selected = profileColor === color.id;
            return (
              <button
                key={color.id}
                type="button"
                disabled={saving}
                onClick={() => onColorChange(color.id)}
                className={cn(
                  "focus-ring flex h-7 w-7 items-center justify-center rounded-full text-white transition-[box-shadow,transform] hover:scale-105 disabled:opacity-60",
                  color.className,
                  selected && "ring-2 ring-foreground ring-offset-2 ring-offset-card",
                )}
                aria-label={color.id}
                aria-pressed={selected}
              >
                {selected ? <Check className="h-3.5 w-3.5" aria-hidden /> : null}
              </button>
            );
          })}
        </div>
      </fieldset>
    </div>
  );
}
