"use client";

import { Check, Copy, ExternalLink, Info, TriangleAlert } from "lucide-react";
import { Fragment, type ReactNode } from "react";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";
import { Dialog } from "@/components/profiles/Dialog";
import { outlineBtn } from "@/components/ui/classes";

const k = "admin_users.sso_guide";
const ENTRA_URL = "https://entra.microsoft.com/";
const BASE = process.env.NEXT_PUBLIC_BASE_PATH || "";

/** Renders `**bold**` segments of a translated string. */
export function rich(text: string): ReactNode {
  return text.split("**").map((part, i) => (i % 2 ? <strong key={i} className="font-semibold text-foreground">{part}</strong> : <Fragment key={i}>{part}</Fragment>));
}

/** Highlight box over a screenshot, in % of the image. `n` is the guide step it belongs to. */
export type Mark = { n?: number; x: number; y: number; w: number; h: number };

const REGISTER_MARKS: Mark[] = [
  { n: 2, x: 22.8, y: 34.2, w: 33.6, h: 3.6 },
  { n: 3, x: 22.8, y: 54.7, w: 50.5, h: 3.8 },
  { x: 22.8, y: 96.4, w: 7.4, h: 3.4 },
];
const SECRET_MARKS: Mark[] = [
  { n: 5, x: 14.6, y: 37.6, w: 13.9, h: 3.8 },
  { x: 35.3, y: 37.6, w: 6, h: 2.8 },
  { x: 29.8, y: 46, w: 8.6, h: 4.2 },
  { x: 70.6, y: 95.4, w: 5.3, h: 3.4 },
];

/**
 * Screenshot with highlight boxes and a caption. `dir` is the folder under `public/`
 * (defaults to the SSO guide; the WhatsApp guide passes `whatsapp-guide`).
 */
export function Shot({
  src,
  alt,
  caption,
  marks,
  className,
  dir = "sso-guide",
}: {
  src: string;
  alt: string;
  caption: string;
  marks: Mark[];
  className?: string;
  dir?: string;
}) {
  return (
    <figure className={cn("flex flex-col gap-2", className)}>
      <div className="relative overflow-hidden rounded-xl border border-border bg-background">
        {/* eslint-disable-next-line @next/next/no-img-element -- static guide asset, shown at natural size ratio */}
        <img src={`${BASE}/${dir}/${src}`} alt={alt} loading="lazy" className="block h-auto w-full" />
        {marks.map((m, i) => (
          <span
            key={i}
            aria-hidden
            className="absolute rounded-md border-2 border-warning bg-warning/10"
            style={{ left: `${m.x}%`, top: `${m.y}%`, width: `${m.w}%`, height: `${m.h}%` }}
          >
            {m.n && (
              <span className="absolute -left-2.5 -top-3 flex h-6 w-6 items-center justify-center rounded-full bg-warning text-xs font-semibold tabular-nums text-white shadow-sm">{m.n}</span>
            )}
          </span>
        ))}
      </div>
      <figcaption className="text-sm text-muted-foreground">{caption}</figcaption>
    </figure>
  );
}

export function Step({ n, title, children }: { n: number; title: string; children: ReactNode }) {
  return (
    <li className="flex gap-4">
      <span aria-hidden className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-secondary text-sm font-semibold tabular-nums">
        {n}
      </span>
      <div className="flex min-w-0 flex-1 flex-col gap-3">
        <h3 className="text-base font-semibold tracking-[-0.01em]">{title}</h3>
        {children}
      </div>
    </li>
  );
}

export function EntraLink({ className }: { className?: string }) {
  const t = useT();
  return (
    <a href={ENTRA_URL} target="_blank" rel="noreferrer" className={cn(outlineBtn, "w-fit", className)}>
      {t(`${k}.link`)}
      <ExternalLink className="h-3.5 w-3.5" aria-hidden />
    </a>
  );
}

export function MicrosoftGuideDialog({ redirectUri, copied, onCopy, onClose }: { redirectUri: string; copied: boolean; onCopy: () => void; onClose: () => void }) {
  const t = useT();
  const body = "text-[15px] leading-relaxed text-muted-foreground";
  return (
    <Dialog title={t(`${k}.dialog_title`)} closeLabel={t(`${k}.close`)} onClose={onClose} className="max-w-4xl">
      <div className="flex max-h-[min(75vh,56rem)] flex-col gap-6 overflow-y-auto pr-1">
        <p className={cn(body, "max-w-[68ch]")}>{t(`${k}.intro`)}</p>
        <ol className="flex flex-col gap-9">
          <Step n={1} title={t(`${k}.t1`)}>
            <p className={cn(body, "max-w-[68ch]")}>{rich(t(`${k}.b1`))}</p>
            <EntraLink />
          </Step>
          <Step n={2} title={t(`${k}.t2`)}>
            <p className={cn(body, "max-w-[68ch]")}>{rich(t(`${k}.b2`))}</p>
          </Step>
          <Step n={3} title={t(`${k}.t3`)}>
            <p className={cn(body, "max-w-[68ch]")}>{rich(t(`${k}.b3`))}</p>
            <div className="flex flex-col gap-1.5">
              <span className="text-sm font-medium">{t(`${k}.uri`)}</span>
              <div className="flex items-center gap-2">
                <code className="min-w-0 flex-1 break-all rounded-xl border border-border bg-background px-3.5 py-2.5 font-mono text-sm">{redirectUri || "…"}</code>
                <button type="button" onClick={onCopy} className={cn(outlineBtn, "shrink-0")}>
                  {copied ? <Check className="h-4 w-4 text-success" aria-hidden /> : <Copy className="h-4 w-4" aria-hidden />}
                  {t(`${k}.${copied ? "copied" : "copy"}`)}
                </button>
              </div>
            </div>
            <Shot src="entra-register-app.png" alt={t(`${k}.alt1`)} caption={t(`${k}.cap1`)} marks={REGISTER_MARKS} />
          </Step>
          <Step n={4} title={t(`${k}.t4`)}>
            <p className={cn(body, "max-w-[68ch]")}>{rich(t(`${k}.b4`))}</p>
          </Step>
          <Step n={5} title={t(`${k}.t5`)}>
            <p className={cn(body, "max-w-[68ch]")}>{rich(t(`${k}.b5`))}</p>
            <Shot src="entra-client-secret.png" alt={t(`${k}.alt2`)} caption={t(`${k}.cap2`)} marks={SECRET_MARKS} />
          </Step>
          <Step n={6} title={t(`${k}.t6`)}>
            <p className={cn(body, "max-w-[68ch]")}>{rich(t(`${k}.b6`))}</p>
            <p className="flex max-w-[68ch] items-start gap-2.5 rounded-xl bg-warning/10 px-4 py-3 text-[15px] leading-relaxed">
              <TriangleAlert className="mt-1 h-4 w-4 shrink-0 text-warning" aria-hidden />
              {t(`${k}.warn`)}
            </p>
          </Step>
          <Step n={7} title={t(`${k}.t7`)}>
            <p className={cn(body, "max-w-[68ch]")}>{rich(t(`${k}.b7`))}</p>
          </Step>
        </ol>
        <p className="flex items-start gap-2 border-t border-border/60 pt-4 text-sm text-muted-foreground">
          <Info className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
          {t(`${k}.shots_note`)}
        </p>
      </div>
    </Dialog>
  );
}
