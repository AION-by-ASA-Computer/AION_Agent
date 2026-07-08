"use client";

import { useRef } from "react";
import { Camera, Trash2 } from "lucide-react";

import { cn } from "@/lib/cn";
import {
  PROFILE_ACCENT_COLORS,
  profileInitials,
  type UserAppearanceMetadata,
} from "@/lib/profile/user-appearance";
import { useT } from "@/lib/i18n/use-t";

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
}: {
  label: string;
  metadata?: UserAppearanceMetadata;
  profileColor: string;
  avatarUrl: string;
  saving?: boolean;
  onColorChange: (colorId: string) => void;
  onAvatarChange: (dataUrl: string) => void;
  onAvatarRemove: () => void;
}) {
  const t = useT();
  const fileRef = useRef<HTMLInputElement>(null);
  const initials = profileInitials(label);
  const activeColor =
    PROFILE_ACCENT_COLORS.find((c) => c.id === profileColor)?.value ||
    metadata?.profile_color ||
    PROFILE_ACCENT_COLORS[0].value;

  async function handleFile(file: File) {
    if (!file.type.startsWith("image/")) return;
    if (file.size > MAX_AVATAR_BYTES) {
      alert(t("settings.profile.avatar_too_large"));
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      if (typeof reader.result === "string") onAvatarChange(reader.result);
    };
    reader.readAsDataURL(file);
  }

  return (
    <div className="flex flex-col gap-5 sm:flex-row sm:items-start">
      <div className="flex items-center gap-4">
        <div
          className="relative flex h-20 w-20 shrink-0 items-center justify-center overflow-hidden rounded-full border-2 border-border/60 text-lg font-semibold text-white shadow-sm"
          style={{ backgroundColor: avatarUrl ? undefined : activeColor }}
        >
          {avatarUrl ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={avatarUrl} alt="" className="h-full w-full object-cover" />
          ) : (
            initials
          )}
        </div>
        <div className="flex flex-col gap-2">
          <button
            type="button"
            disabled={saving}
            onClick={() => fileRef.current?.click()}
            className="focus-ring inline-flex items-center gap-2 rounded-lg border border-border bg-background/60 px-3 py-2 text-xs font-semibold text-foreground transition hover:bg-muted/60 disabled:opacity-50"
          >
            <Camera className="h-3.5 w-3.5" aria-hidden />
            {t("settings.profile.upload_photo")}
          </button>
          {avatarUrl ? (
            <button
              type="button"
              disabled={saving}
              onClick={onAvatarRemove}
              className="focus-ring inline-flex items-center gap-2 rounded-lg px-2 py-1.5 text-xs font-medium text-destructive transition hover:bg-destructive/10 disabled:opacity-50"
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
              if (file) void handleFile(file);
              e.target.value = "";
            }}
          />
        </div>
      </div>

      <div className="min-w-0 flex-1">
        <div className="mb-2 text-xs font-semibold text-foreground">{t("settings.profile.color_label")}</div>
        <div className="flex flex-wrap gap-2">
          {PROFILE_ACCENT_COLORS.map((color) => {
            const selected = profileColor === color.id;
            return (
              <button
                key={color.id}
                type="button"
                disabled={saving}
                onClick={() => onColorChange(color.id)}
                className={cn(
                  "focus-ring h-8 w-8 rounded-full border-2 transition",
                  color.className,
                  selected ? "border-foreground ring-2 ring-primary/40" : "border-transparent opacity-90 hover:opacity-100",
                )}
                aria-label={color.id}
                aria-pressed={selected}
              />
            );
          })}
        </div>
      </div>
    </div>
  );
}
