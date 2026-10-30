"use client";

import { useCallback, useState } from "react";
import { useT } from "@/lib/i18n/use-t";
import { PageToast, type ToastState } from "@/components/PageToast";
import { SectionHead } from "@/components/settings/ui";
import { WhatsAppConfigPanel, type Notify } from "@/components/whatsapp/WhatsAppConfigPanel";
import { WhatsAppIdentitiesTable } from "@/components/whatsapp/WhatsAppIdentitiesTable";

const k = "admin_whatsapp.page";

export default function WhatsAppPage() {
  const t = useT();
  const [toast, setToast] = useState<ToastState>(null);
  const notify: Notify = useCallback((message, variant = "info") => setToast({ message, variant }), []);

  return (
    <div className="mx-auto max-w-4xl pb-24">
      <header className="pb-8">
        <h1 className="text-balance text-2xl font-semibold tracking-[-0.02em] sm:text-3xl">{t(`${k}.title`)}</h1>
        <p className="mt-1 max-w-[62ch] text-sm text-muted-foreground">{t(`${k}.subtitle`)}</p>
      </header>

      <section aria-labelledby="wa-config" className="flex flex-col gap-4">
        <div id="wa-config">
          <SectionHead title={t(`${k}.config_title`)} description={t(`${k}.config_desc`)} />
        </div>
        <WhatsAppConfigPanel notify={notify} />
      </section>

      <section aria-labelledby="wa-users" className="mt-12 flex flex-col gap-4">
        <div id="wa-users">
          <SectionHead title={t(`${k}.users_title`)} description={t(`${k}.users_desc`)} />
        </div>
        <WhatsAppIdentitiesTable notify={notify} />
      </section>

      <PageToast toast={toast} onDismiss={() => setToast(null)} />
    </div>
  );
}
