"use client";

import { Check, Copy, ExternalLink, Info, TriangleAlert } from "lucide-react";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";
import { Dialog } from "@/components/profiles/Dialog";
import { outlineBtn } from "@/components/ui/classes";
import { Shot, Step, rich, type Mark } from "./MicrosoftSsoGuide";

const k = "admin_users.sso_guide_google";
const GOOGLE_URL = "https://console.cloud.google.com/";

const NEW_PROJECT: Mark[] = [{ n: 1, x: 2, y: 25.4, w: 30, h: 3.8 }, { x: 2, y: 44.3, w: 3.3, h: 3.3 }];
const PLATFORM: Mark[] = [{ n: 2, x: 60.2, y: 56, w: 3.4, h: 3.3 }];
const APP_INFO: Mark[] = [{ n: 3, x: 19.6, y: 22.1, w: 27.1, h: 3.8 }, { x: 19.6, y: 30.7, w: 27.1, h: 4.2 }, { x: 19.6, y: 39.8, w: 3.8, h: 3.4 }];
const AUDIENCE: Mark[] = [{ n: 4, x: 19.4, y: 27.8, w: 6.3, h: 2.9 }, { x: 19.4, y: 41, w: 6.3, h: 2.9 }, { x: 19.2, y: 65.5, w: 3.8, h: 3.3 }];
const CONTACT: Mark[] = [{ n: 5, x: 19.7, y: 35.3, w: 27.3, h: 4.2 }, { x: 19.7, y: 45.6, w: 3.8, h: 3.3 }];
const FINISH: Mark[] = [{ x: 20.3, y: 41.5, w: 25.4, h: 2.7 }, { x: 20.3, y: 46.9, w: 5, h: 3.3 }, { x: 17.4, y: 53.8, w: 3.2, h: 3.4 }];
const CLIENTS: Mark[] = [{ n: 6, x: 21.9, y: 9, w: 6.7, h: 3.4 }];
const CLIENT_FORM: Mark[] = [{ n: 7, x: 16.9, y: 20.6, w: 29.3, h: 4.1 }, { x: 16.9, y: 27, w: 29.3, h: 3.7 }, { x: 16.9, y: 72.1, w: 26.5, h: 3.7 }, { x: 16.9, y: 96.2, w: 3.2, h: 3.3 }];
const CREATED: Mark[] = [{ n: 8, x: 43.4, y: 29.8, w: 48.4, h: 9.7 }, { x: 43.4, y: 62, w: 48.4, h: 6.2 }];

export function GoogleLink({ className }: { className?: string }) {
  const t = useT();
  return (
    <a href={GOOGLE_URL} target="_blank" rel="noreferrer" className={cn(outlineBtn, "w-fit", className)}>
      {t(`${k}.link`)}
      <ExternalLink className="h-3.5 w-3.5" aria-hidden />
    </a>
  );
}

export function GoogleGuideDialog({ redirectUri, copied, onCopy, onClose }: { redirectUri: string; copied: boolean; onCopy: () => void; onClose: () => void }) {
  const t = useT();
  const body = "max-w-[68ch] text-[15px] leading-relaxed text-muted-foreground";
  const shot = (src: string, cap: string, marks: Mark[], className?: string) => <Shot src={src} alt={t(`${k}.${cap}`)} caption={t(`${k}.${cap}`)} marks={marks} className={className} />;
  return (
    <Dialog title={t(`${k}.dialog_title`)} closeLabel={t(`${k}.close`)} onClose={onClose} className="max-w-4xl">
      <div className="flex max-h-[min(75vh,56rem)] flex-col gap-6 overflow-y-auto pr-1">
        <p className={body}>{t(`${k}.intro`)}</p>
        <ol className="flex flex-col gap-9">
          <Step n={1} title={t(`${k}.t1`)}>
            <p className={body}>{rich(t(`${k}.b1`))}</p>
            <GoogleLink />
            {shot("google-new-project.png", "c1", NEW_PROJECT)}
          </Step>
          <Step n={2} title={t(`${k}.t2`)}>
            <p className={body}>{rich(t(`${k}.b2`))}</p>
            {shot("google-auth-platform.png", "c2", PLATFORM)}
          </Step>
          <Step n={3} title={t(`${k}.t3`)}>
            <p className={body}>{rich(t(`${k}.b3`))}</p>
            {shot("google-app-info.png", "c3", APP_INFO)}
          </Step>
          <Step n={4} title={t(`${k}.t4`)}>
            <p className={body}>{rich(t(`${k}.b4`))}</p>
            {shot("google-audience.png", "c4", AUDIENCE)}
          </Step>
          <Step n={5} title={t(`${k}.t5`)}>
            <p className={body}>{rich(t(`${k}.b5`))}</p>
            {shot("google-contact.png", "c5", CONTACT)}
            {shot("google-finish.png", "c6", FINISH)}
          </Step>
          <Step n={6} title={t(`${k}.t6`)}>
            <p className={body}>{rich(t(`${k}.b6`))}</p>
            {shot("google-clients.png", "c7", CLIENTS)}
          </Step>
          <Step n={7} title={t(`${k}.t7`)}>
            <p className={body}>{rich(t(`${k}.b7`))}</p>
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
            {shot("google-create-client.png", "c8", CLIENT_FORM)}
          </Step>
          <Step n={8} title={t(`${k}.t8`)}>
            <p className={body}>{rich(t(`${k}.b8`))}</p>
            <p className="flex max-w-[68ch] items-start gap-2.5 rounded-xl bg-warning/10 px-4 py-3 text-[15px] leading-relaxed">
              <TriangleAlert className="mt-1 h-4 w-4 shrink-0 text-warning" aria-hidden />
              {t(`${k}.warn`)}
            </p>
            {shot("google-client-created.png", "c9", CREATED, "max-w-sm")}
          </Step>
          <Step n={9} title={t(`${k}.t9`)}>
            <p className={body}>{rich(t(`${k}.b9`))}</p>
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
