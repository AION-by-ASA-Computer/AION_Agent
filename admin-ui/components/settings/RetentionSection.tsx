"use client";

import { Field, FieldGrid, Group, Mono, Note, SectionHead, TextInput, ToggleList, ToggleRow } from "./ui";
import { K, type SectionCtx } from "./types";

const m = `${K}.retention`;

export function RetentionSection({ t, settings, set }: SectionCtx) {
  const days = settings.AION_SESSION_CLEANUP_MAX_AGE_DAYS ?? "15";
  const hard = settings.AION_SESSION_CLEANUP_HARD_DELETE === "1";
  const off = days.trim() === "0";

  return (
    <div className="flex flex-col gap-5">
      <SectionHead title={t(`${m}.title`)} description={t(`${m}.description`)} />

      <Group>
        <FieldGrid>
          <Field label={t(`${m}.max_age`)} env="AION_SESSION_CLEANUP_MAX_AGE_DAYS" hint={t(`${m}.max_age_hint`)}>
            <TextInput type="number" inputMode="numeric" value={days} onChange={(v) => set("AION_SESSION_CLEANUP_MAX_AGE_DAYS", v)} />
          </Field>
          <Field label={t(`${m}.interval`)} env="AION_SESSION_CLEANUP_INTERVAL_SEC" hint={t(`${m}.interval_hint`)}>
            <TextInput type="number" inputMode="numeric" value={settings.AION_SESSION_CLEANUP_INTERVAL_SEC ?? "86400"} onChange={(v) => set("AION_SESSION_CLEANUP_INTERVAL_SEC", v)} />
          </Field>
        </FieldGrid>
        <div className="border-t border-border/50">
          <ToggleList>
            <ToggleRow label={t(`${m}.hard`)} description={t(`${m}.hard_hint`)} checked={hard} onChange={(v) => set("AION_SESSION_CLEANUP_HARD_DELETE", v ? "1" : "0")} />
          </ToggleList>
        </div>
      </Group>

      <Note tone={hard && !off ? "warn" : "info"}>
        {off ? t(`${m}.summary_off`) : t(hard ? `${m}.summary_hard` : `${m}.summary_soft`, { days })}{" "}
        <Mono>data/sessions/</Mono>
      </Note>
    </div>
  );
}
