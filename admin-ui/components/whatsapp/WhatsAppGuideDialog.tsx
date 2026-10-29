"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { Check, Copy, ExternalLink, TriangleAlert } from "lucide-react";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";
import { Dialog } from "@/components/profiles/Dialog";
import { outlineBtn } from "@/components/ui/classes";
import { Step, rich } from "@/components/sso/MicrosoftSsoGuide";

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

export function WhatsAppGuideDialog({ webhookUrl, verifyToken, onClose }: { webhookUrl: string; verifyToken: string; onClose: () => void }) {
  const t = useT();
  const body = "max-w-[68ch] text-[15px] leading-relaxed text-muted-foreground";
  const p = (n: number) => <p className={body}>{rich(t(`${k}.b${n}`))}</p>;
  return (
    <Dialog title={t(`${k}.dialog_title`)} closeLabel={t(`${k}.close`)} onClose={onClose} className="max-w-3xl">
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
          </Step>
          <Step n={3} title={t(`${k}.t3`)}>
            {p(3)}
            <Warn>{t(`${k}.warn3`)}</Warn>
          </Step>
          <Step n={4} title={t(`${k}.t4`)}>
            {p(4)}
          </Step>
          <Step n={5} title={t(`${k}.t5`)}>
            {p(5)}
            <Warn>{t(`${k}.warn5`)}</Warn>
          </Step>
          <Step n={6} title={t(`${k}.t6`)}>
            {p(6)}
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
          </Step>
        </ol>
      </div>
    </Dialog>
  );
}
