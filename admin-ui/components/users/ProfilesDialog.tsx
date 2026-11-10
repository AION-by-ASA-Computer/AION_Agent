"use client";

/**
 * Profile access picker shared by the Users and Service accounts admin pages.
 *
 * Lets an admin choose which agent profiles an account may use; an empty
 * selection means "every profile". The dialog only collects the choice: the
 * caller persists it through `POST /admin/users/{id}/profiles`.
 */

import { useState } from "react";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/cn";
import { Dialog } from "@/components/profiles/Dialog";
import { ghostBtn, solidBtn } from "@/components/ui/classes";

/** Agent profile as returned by `GET /admin/profiles`. */
export interface ProfileRow {
  slug: string;
  name: string;
  description?: string;
}

type T = (key: string, vars?: Record<string, string | number>) => string;

/**
 * Modal with one checkbox per profile.
 *
 * @param name     Account name shown in the body sentence (`{{name}}`).
 * @param initial  Slugs currently allowed (empty = all profiles).
 * @param ns       i18n namespace holding the strings (title, body, hint, …);
 *                 defaults to the Users page wording.
 * @param onSave   Called with the selected slugs; the caller closes the dialog.
 */
export function ProfilesDialog({
  name,
  profiles,
  initial,
  busy,
  t,
  ns = "admin_users.profiles",
  onSave,
  onClose,
}: {
  name: string;
  profiles: ProfileRow[];
  initial: string[];
  busy: boolean;
  t: T;
  ns?: string;
  onSave: (slugs: string[]) => void;
  onClose: () => void;
}) {
  const [selected, setSelected] = useState<string[]>(initial);
  const toggle = (slug: string) => setSelected((s) => (s.includes(slug) ? s.filter((x) => x !== slug) : [...s, slug]));

  return (
    <Dialog title={t(`${ns}.title`)} closeLabel={t(`${ns}.cancel`)} onClose={onClose} className="max-w-xl">
      <div className="flex flex-col gap-4">
        <p className="text-sm text-muted-foreground">{t(`${ns}.body`, { name })}</p>

        <div className="flex items-center justify-between gap-3 text-xs text-muted-foreground">
          <span>{selected.length === 0 ? t(`${ns}.all`) : t(`${ns}.selected`, { count: selected.length })}</span>
          {selected.length > 0 && (
            <button type="button" onClick={() => setSelected([])} className="focus-ring rounded-md font-medium underline underline-offset-4 hover:text-foreground">
              {t(`${ns}.clear`)}
            </button>
          )}
        </div>

        <ul className="-mx-1 flex max-h-[22rem] flex-col gap-0.5 overflow-y-auto px-1">
          {profiles.map((p) => {
            const on = selected.includes(p.slug);
            return (
              <li key={p.slug}>
                <label className={cn("flex cursor-pointer items-start gap-3 rounded-xl px-3 py-2.5 transition-colors", on ? "bg-secondary" : "hover:bg-secondary/60")}>
                  <input type="checkbox" checked={on} onChange={() => toggle(p.slug)} className="focus-ring mt-1 h-4 w-4 shrink-0 accent-foreground" />
                  <span className="min-w-0">
                    <span className="block truncate text-sm font-medium">{p.name}</span>
                    {p.description && <span className="mt-0.5 block text-xs text-muted-foreground">{p.description}</span>}
                  </span>
                </label>
              </li>
            );
          })}
        </ul>
        {profiles.length === 0 && <p className="py-6 text-center text-sm text-muted-foreground">{t(`${ns}.none`)}</p>}
        <p className="text-xs text-muted-foreground">{t(`${ns}.hint`)}</p>

        <div className="flex justify-end gap-2">
          <button type="button" className={ghostBtn} onClick={onClose}>
            {t(`${ns}.cancel`)}
          </button>
          <button type="button" className={solidBtn} disabled={busy} onClick={() => onSave(selected)}>
            {busy && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />}
            {busy ? t(`${ns}.saving`) : t(`${ns}.save`)}
          </button>
        </div>
      </div>
    </Dialog>
  );
}
