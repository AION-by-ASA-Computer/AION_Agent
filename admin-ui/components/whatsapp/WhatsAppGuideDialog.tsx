"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { Check, Copy, ExternalLink, TriangleAlert } from "lucide-react";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";
import { Dialog } from "@/components/profiles/Dialog";
import { outlineBtn } from "@/components/ui/classes";
import { Shot, Step, rich } from "@/components/sso/MicrosoftSsoGuide";
import { WHATSAPP_SHOT_MARKS } from "./guide-shots";

const k = "admin_whatsapp.guide";
const BUSINESS_URL = "https://business.facebook.com/";
const DEVELOPERS_URL = "https://developers.facebook.com/apps/";

export function MetaLink({ business, className }: { business?: boolean; className?: string }) {
  const t = useT();
  return (
    <a href={business ? BUSINESS_URL : DEVELOPERS_URL} target="_blank" rel="noreferrer" className={cn(outlineBtn, "w-fit", className)}>
      {t(`${k}.${business ? "link_business" : "link_developers"}`)}
      <ExternalLink className="h-3.5 w-3.5" aria-hidden />
    </a>
  );
}

/** Read-only value with a copy button; `empty` replaces the value while there is none. */
export function CopyField({
  label,
  value,
  empty,
  copyLabel,
  copiedLabel,
  action,
}: {
  label: string;
  value: string;
  empty?: string;
  copyLabel: string;
  copiedLabel: string;
  action?: ReactNode;
}) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
  }, []);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => setCopied(false), 2000);
    } catch {
      /* clipboard unavailable */
    }
  };

  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <span className="text-sm font-medium">{label}</span>
      <div className="flex items-center gap-2">
        <code
          className={cn(
            "min-w-0 flex-1 break-all rounded-xl border border-border bg-background px-3.5 py-2.5 font-mono text-[13px]",
            !value && "text-muted-foreground",
          )}
        >
          {value || empty || "…"}
        </code>
        <button type="button" onClick={copy} disabled={!value} className={cn(outlineBtn, "w-9 shrink-0 justify-center px-0")} aria-label={copied ? copiedLabel : copyLabel}>
          {copied ? <Check className="h-4 w-4 text-success" aria-hidden /> : <Copy className="h-4 w-4" aria-hidden />}
        </button>
        {action}
      </div>
    </div>
  );
}

function Warn({ children }: { children: ReactNode }) {
  return (
    <p className="flex max-w-[68ch] items-start gap-2.5 rounded-xl bg-warning/10 px-4 py-3 text-[15px] leading-relaxed">
      <TriangleAlert className="mt-1 h-4 w-4 shrink-0 text-warning" aria-hidden />
      {children}
    </p>
  );
}

/**
 * Redacted Meta screenshot from `public/whatsapp-guide/<name>.png`.
 * The caption (also used as alt text) lives in the locale files under
 * `cap_<name with "_" instead of "-">`; the highlight boxes in `guide-shots.ts`.
 * `narrow` caps the width of dialog-style captures (tall, mostly white) so they
 * don't dominate the guide.
 */
function WaShot({ name, narrow }: { name: string; narrow?: boolean }) {
  const t = useT();
  const caption = t(`${k}.cap_${name.replaceAll("-", "_")}`);
  return <Shot dir="whatsapp-guide" src={`${name}.png`} alt={caption} caption={caption} marks={WHATSAPP_SHOT_MARKS[name] ?? []} className={narrow ? "max-w-xl" : undefined} />;
}

export function WhatsAppGuideDialog({ webhookUrl, verifyToken, onClose }: { webhookUrl: string; verifyToken: string; onClose: () => void }) {
  const t = useT();
  const body = "max-w-[68ch] text-[15px] leading-relaxed text-muted-foreground";
  const p = (n: number) => <p className={body}>{rich(t(`${k}.b${n}`))}</p>;
  return (
    <Dialog title={t(`${k}.dialog_title`)} closeLabel={t(`${k}.close`)} onClose={onClose} className="max-w-4xl">
      <div className="flex max-h-[min(75vh,56rem)] flex-col gap-6 overflow-y-auto pr-1">
        <p className={body}>{t(`${k}.intro`)}</p>
        <ol className="flex flex-col gap-9">
          <Step n={1} title={t(`${k}.t1`)}>
            {p(1)}
            <MetaLink business />
          </Step>
          <Step n={2} title={t(`${k}.t2`)}>
            {p(2)}
            <MetaLink />
            <WaShot name="app-details" />
            <WaShot name="app-use-case" />
            <WaShot name="app-business-portfolio" />
            <WaShot name="app-review-create" />
          </Step>
          <Step n={3} title={t(`${k}.t3`)}>
            {p(3)}
            <Warn>{t(`${k}.warn3`)}</Warn>
            <WaShot name="use-cases-customize" />
            <WaShot name="add-phone-number" />
            <WaShot name="whatsapp-profile" narrow />
            <WaShot name="phone-verify" narrow />
            <WaShot name="messaging-account" narrow />
          </Step>
          <Step n={4} title={t(`${k}.t4`)}>
            {p(4)}
            <WaShot name="registered-ids" />
          </Step>
          <Step n={5} title={t(`${k}.t5`)}>
            {p(5)}
            <WaShot name="system-users" />
            <WaShot name="system-user-create" narrow />
            <WaShot name="system-user-assign" />
            <WaShot name="assign-assets-dialog" narrow />
            <WaShot name="assets-assigned" />
            <WaShot name="token-app" narrow />
            <WaShot name="token-expiry" narrow />
            <WaShot name="token-permissions" narrow />
            <WaShot name="token-created" narrow />
            <Warn>{t(`${k}.warn5`)}</Warn>
            <WaShot name="temp-token" />
          </Step>
          <Step n={6} title={t(`${k}.t6`)}>
            {p(6)}
            <WaShot name="app-secret" />
          </Step>
          <Step n={7} title={t(`${k}.t7`)}>
            {p(7)}
          </Step>
          <Step n={8} title={t(`${k}.t8`)}>
            {p(8)}
            <CopyField label={t(`${k}.callback`)} value={webhookUrl} copyLabel={t(`${k}.copy`)} copiedLabel={t(`${k}.copied`)} />
            <CopyField
              label={t(`${k}.verify_token`)}
              value={verifyToken}
              empty={t(`${k}.no_token`)}
              copyLabel={t(`${k}.copy`)}
              copiedLabel={t(`${k}.copied`)}
            />
          </Step>
          <Step n={9} title={t(`${k}.t9`)}>
            {p(9)}
            <WaShot name="app-unpublished" />
          </Step>
        </ol>
        {/* Screenshots come from an Italian Meta UI with personal data masked: say so, as Meta's labels change often */}
        <p className="max-w-[68ch] text-sm text-muted-foreground">{t(`${k}.shots_note`)}</p>
      </div>
    </Dialog>
  );
}
