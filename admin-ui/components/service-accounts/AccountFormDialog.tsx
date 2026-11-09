"use client";

/**
 * Create / edit dialog for a service account (admin-ui → Service accounts).
 *
 * On create the admin picks a slug: the backend stores the identifier as
 * `svc-<slug>`, so the prefix is shown fixed in front of the input and cannot
 * be typed. The slug is immutable afterwards, so it is hidden when editing.
 * The dialog only validates and collects values; the page sends the request.
 */

import { useState } from "react";
import { Bot, Brain, Loader2 } from "lucide-react";
import { cn } from "@/lib/cn";
import { Dialog } from "@/components/profiles/Dialog";
import { ghostBtn, inputCls, solidBtn } from "@/components/ui/classes";
import { Switch } from "@/components/settings/ui";
import { Field, KEY_TTL_DAYS, MAX_KEYS, SLUG_RE, SVC_PREFIX, k, nameOf, parseInRange, type ServiceAccount, type T } from "./shared";

/** Values collected by the form; `slug` is only sent on create. */
export interface AccountFormValues {
  slug: string;
  display_name: string;
  description: string;
  ltm_enabled: boolean;
  max_api_keys: number;
  api_key_max_ttl_days: number;
}

/** Suggested slug from the display name: "Nightly ETL bot" -> "nightly-etl-bot". */
function suggestSlug(displayName: string): string {
  return displayName
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .trim()
    .replace(/\s+/g, "-")
    .replace(/[^a-z0-9._-]/g, "")
    .replace(/-{2,}/g, "-")
    .replace(/^[._-]+|[._-]+$/g, "")
    .slice(0, 61);
}

/**
 * @param account  Account to edit, or null to create a new one.
 * @param slugError Server-side error for the slug (e.g. already taken), shown under the input.
 * @param onSubmit Sends the values; resolves when the request is done.
 */
export function AccountFormDialog({
  account,
  busy,
  slugError,
  t,
  onSubmit,
  onClose,
}: {
  account: ServiceAccount | null;
  busy: boolean;
  slugError?: string;
  t: T;
  onSubmit: (v: AccountFormValues) => void | Promise<void>;
  onClose: () => void;
}) {
  const editing = !!account;
  const [displayName, setDisplayName] = useState(account?.display_name ?? "");
  const [description, setDescription] = useState(account?.description ?? "");
  const [slug, setSlug] = useState("");
  // Until the admin types a slug, keep suggesting one from the display name.
  const [slugTouched, setSlugTouched] = useState(false);
  const [ltm, setLtm] = useState(!!account?.ltm_enabled);
  const [maxKeys, setMaxKeys] = useState(String(account?.max_api_keys ?? MAX_KEYS.default));
  const [maxDays, setMaxDays] = useState(String(account?.api_key_max_ttl_days ?? KEY_TTL_DAYS.default));

  const effectiveSlug = slugTouched ? slug : suggestSlug(displayName);
  const slugOk = editing || SLUG_RE.test(effectiveSlug);
  const maxKeysValue = parseInRange(maxKeys, MAX_KEYS);
  const maxDaysValue = parseInRange(maxDays, KEY_TTL_DAYS);
  const canSubmit = !busy && slugOk && maxKeysValue !== null && maxDaysValue !== null;
  // Show the slug rule in red only once the admin typed something that breaks it.
  const showSlugError = !editing && slugTouched && !!slug && !SLUG_RE.test(slug);

  return (
    <Dialog title={t(`${k}.form.${editing ? "title_edit" : "title_new"}`)} closeLabel={t(`${k}.form.cancel`)} onClose={onClose} className="max-w-xl">
      <form
        className="flex flex-col"
        onSubmit={(e) => {
          e.preventDefault();
          if (!canSubmit) return;
          void onSubmit({
            slug: effectiveSlug,
            display_name: displayName.trim(),
            description: description.trim(),
            ltm_enabled: ltm,
            max_api_keys: maxKeysValue!,
            api_key_max_ttl_days: maxDaysValue!,
          });
        }}
      >
        {editing && (
          <div className="mb-5 flex items-center gap-3">
            <span aria-hidden className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-secondary text-muted-foreground">
              <Bot className="h-4 w-4" />
            </span>
            <div className="min-w-0">
              <p className="truncate text-sm font-medium">{nameOf(account)}</p>
              <p className="truncate font-mono text-xs text-muted-foreground">{account.identifier}</p>
            </div>
          </div>
        )}

        <div className="flex flex-col gap-4">
          <Field label={t(`${k}.form.display_name`)} htmlFor="svc-form-name" optional t={t}>
            <input
              id="svc-form-name"
              autoFocus
              type="text"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder={t(`${k}.form.display_name_placeholder`)}
              autoComplete="off"
              maxLength={120}
              className={inputCls}
            />
          </Field>

          {!editing && (
            <Field
              label={t(`${k}.form.slug`)}
              htmlFor="svc-form-slug"
              hint={t(`${k}.form.slug_hint`)}
              error={showSlugError ? t(`${k}.form.slug_invalid`) : slugError}
              t={t}
            >
              {/* The prefix is part of the identifier but not of the slug the backend expects. */}
              <div
                className={cn(
                  "flex items-stretch overflow-hidden rounded-xl border border-border bg-background transition-colors focus-within:border-foreground/40 hover:border-foreground/25",
                  (showSlugError || slugError) && "border-destructive/60",
                )}
              >
                <span aria-hidden className="flex items-center border-r border-border bg-secondary/60 px-3 font-mono text-sm text-muted-foreground">
                  {SVC_PREFIX}
                </span>
                <input
                  id="svc-form-slug"
                  type="text"
                  value={effectiveSlug}
                  onChange={(e) => {
                    setSlugTouched(true);
                    setSlug(e.target.value.toLowerCase());
                  }}
                  required
                  autoComplete="off"
                  autoCapitalize="none"
                  spellCheck={false}
                  maxLength={61}
                  placeholder="nightly-report"
                  aria-invalid={showSlugError || !!slugError}
                  aria-describedby="svc-form-slug-hint"
                  aria-label={`${t(`${k}.form.slug`)} (${SVC_PREFIX}…)`}
                  className="min-w-0 flex-1 bg-transparent px-3 py-2.5 font-mono text-sm outline-none placeholder:text-muted-foreground/70"
                />
              </div>
            </Field>
          )}

          <Field label={t(`${k}.form.description`)} htmlFor="svc-form-description" optional hint={t(`${k}.form.description_hint`)} t={t}>
            <textarea
              id="svc-form-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={2}
              maxLength={500}
              placeholder={t(`${k}.form.description_placeholder`)}
              className={cn(inputCls, "resize-y")}
            />
          </Field>
        </div>

        {/* Long-term memory: off by default, an integration rarely needs to remember across calls. */}
        <div className="mt-6 flex items-center gap-4 border-t border-border/60 pt-5">
          <Brain className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium">{t(`${k}.form.ltm`)}</p>
            <p className="mt-0.5 text-xs text-muted-foreground">{t(`${k}.form.ltm_hint`)}</p>
          </div>
          <Switch checked={ltm} onChange={setLtm} label={t(`${k}.form.ltm`)} />
        </div>

        <fieldset className="mt-6 flex flex-col gap-4 border-t border-border/60 pt-5">
          <legend className="sr-only">{t(`${k}.form.keys_title`)}</legend>
          <div>
            <p className="text-sm font-medium">{t(`${k}.form.keys_title`)}</p>
            <p className="mt-0.5 text-xs text-muted-foreground">{t(`${k}.form.keys_description`)}</p>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <NumberInput id="svc-form-max-keys" label={t(`${k}.form.max_keys`)} value={maxKeys} onChange={setMaxKeys} range={MAX_KEYS} t={t} />
            <NumberInput id="svc-form-max-days" label={t(`${k}.form.max_days`)} value={maxDays} onChange={setMaxDays} range={KEY_TTL_DAYS} t={t} />
          </div>
          {editing && <p className="text-xs text-muted-foreground">{t(`${k}.form.limits_existing`)}</p>}
        </fieldset>

        <div className="mt-7 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <button type="button" className={cn(ghostBtn, "justify-center")} onClick={onClose}>
            {t(`${k}.form.cancel`)}
          </button>
          <button type="submit" className={cn(solidBtn, "justify-center")} disabled={!canSubmit}>
            {busy && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />}
            {busy ? t(`${k}.form.saving`) : t(`${k}.form.${editing ? "save" : "create"}`)}
          </button>
        </div>
      </form>
    </Dialog>
  );
}

/** Integer input bounded by `range`, with the allowed range (or the error) under it. */
function NumberInput({
  id,
  label,
  value,
  onChange,
  range,
  t,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (v: string) => void;
  range: { min: number; max: number };
  t: T;
}) {
  const invalid = parseInRange(value, range) === null;
  return (
    <Field
      label={label}
      htmlFor={id}
      hint={t(`${k}.form.range_hint`, { min: range.min, max: range.max })}
      error={invalid ? t(`${k}.form.range_error`, { min: range.min, max: range.max }) : undefined}
      t={t}
    >
      <input
        id={id}
        type="number"
        inputMode="numeric"
        min={range.min}
        max={range.max}
        step={1}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        aria-invalid={invalid}
        aria-describedby={`${id}-hint`}
        className={cn(inputCls, "tabular-nums", invalid && "border-destructive/60 hover:border-destructive/70 focus:border-destructive")}
      />
    </Field>
  );
}
