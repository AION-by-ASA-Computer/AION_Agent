"use client";

/**
 * Admin Telegram page: the single place for the Telegram channel, laid out like the
 * WhatsApp page. Configuration (manager bot, policies, chat behaviour) comes first,
 * then the assistants users created, their quotas and the activity log.
 */

import { useCallback, useState } from "react";
import { useT } from "@/lib/i18n/use-t";
import { PageToast, type ToastState } from "@/components/PageToast";
import { SectionHead } from "@/components/settings/ui";
import { TelegramAuditLog } from "@/components/telegram/TelegramAuditLog";
import { TelegramBotsList } from "@/components/telegram/TelegramBotsList";
import { TelegramConfigPanel } from "@/components/telegram/TelegramConfigPanel";
import { TelegramQuotasList } from "@/components/telegram/TelegramQuotasList";
import { k, type Notify } from "@/components/telegram/shared";

const p = `${k}.page`;

export default function TelegramAdminPage() {
  const t = useT();
  const [toast, setToast] = useState<ToastState>(null);
  const notify: Notify = useCallback((message, variant = "info") => setToast({ message, variant }), []);
  // Bumped after a config save: the gateway restarts and the default quota may change,
  // so the lists below reload.
  const [rev, setRev] = useState(0);
  const onSaved = useCallback(() => setRev((r) => r + 1), []);

  return (
    <div className="mx-auto max-w-4xl pb-24">
      <header className="pb-8">
        <h1 className="text-balance text-2xl font-semibold tracking-[-0.02em] sm:text-3xl">{t(`${k}.title`)}</h1>
        <p className="mt-1 max-w-[62ch] text-sm text-muted-foreground">{t(`${k}.subtitle`)}</p>
      </header>

      <section aria-labelledby="tg-config" className="flex flex-col gap-4">
        <div id="tg-config">
          <SectionHead title={t(`${p}.config_title`)} description={t(`${p}.config_desc`)} />
        </div>
        <TelegramConfigPanel t={t} notify={notify} onSaved={onSaved} />
      </section>

      <section aria-labelledby="tg-bots" className="mt-12 flex flex-col gap-4">
        <div id="tg-bots">
          <SectionHead title={t(`${p}.bots_title`)} description={t(`${p}.bots_desc`)} />
        </div>
        <TelegramBotsList t={t} notify={notify} rev={rev} />
      </section>

      <section aria-labelledby="tg-quotas" className="mt-12 flex flex-col gap-4">
        <div id="tg-quotas">
          <SectionHead title={t(`${p}.quotas_title`)} description={t(`${p}.quotas_desc`)} />
        </div>
        <TelegramQuotasList t={t} notify={notify} rev={rev} />
      </section>

      <section aria-labelledby="tg-audit" className="mt-12 flex flex-col gap-4">
        <div id="tg-audit">
          <SectionHead title={t(`${p}.audit_title`)} description={t(`${p}.audit_desc`)} />
        </div>
        <TelegramAuditLog t={t} rev={rev} />
      </section>

      <PageToast toast={toast} onDismiss={() => setToast(null)} />
    </div>
  );
}
