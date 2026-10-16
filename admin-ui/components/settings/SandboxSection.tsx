"use client";

import { useCallback, useEffect, useState } from "react";
import { Loader2, Save } from "lucide-react";
import { load as yamlLoad } from "js-yaml";
import { apiFetch } from "@/lib/api/headers";
import { apiBase } from "@/lib/api";
import { PolicyEditor } from "@/components/policy-editor";
import { outlineBtn, solidBtn } from "@/components/ui/classes";
import { ChoiceList, Group, Mono, Note, SectionHead, Switch } from "./ui";
import { K, type SectionCtx } from "./types";

type PolicyType = "dev" | "production" | "custom";
const m = `${K}.sandbox`;

export function SandboxSection({ t, notify, onRestart }: Pick<SectionCtx, "t" | "notify" | "onRestart">) {
  const [enabled, setEnabled] = useState(true);
  const [devYaml, setDevYaml] = useState("");
  const [prodYaml, setProdYaml] = useState("");
  const [customYaml, setCustomYaml] = useState("");
  const [type, setType] = useState<PolicyType>("dev");
  const [saved, setSaved] = useState<{ enabled: boolean; yaml: string } | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await apiFetch(`${apiBase()}/admin/settings/fs-policy`);
      if (!res.ok) return;
      const data = await res.json();
      setEnabled(data.enabled);
      setDevYaml(data.dev_template || "");
      setProdYaml(data.example_template || "");
      const active = data.yaml_content || "";
      if (active === data.dev_template) {
        setType("dev");
        setCustomYaml(data.dev_template);
      } else if (active === data.example_template) {
        setType("production");
        setCustomYaml(data.example_template);
      } else {
        setType("custom");
        setCustomYaml(active);
      }
      setSaved({ enabled: data.enabled, yaml: active });
    } catch {
      /* the editor stays on its defaults */
    } finally {
      setLoaded(true);
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch on mount
    void load();
  }, [load]);

  const current = type === "dev" ? devYaml : type === "production" ? prodYaml : customYaml;
  const dirty = !!saved && (enabled !== saved.enabled || (enabled && current !== saved.yaml));

  const save = async () => {
    if (enabled) {
      try {
        const parsed = yamlLoad(current) as { exec?: { allowlist?: unknown[] } } | null;
        const list = parsed?.exec?.allowlist;
        if (Array.isArray(list)) {
          for (let i = 0; i < list.length; i++) {
            const rule = list[i] as { executable?: string } | null;
            if (!rule || typeof rule !== "object" || !rule.executable || !rule.executable.trim()) {
              return notify(t(`${m}.err_rule`, { n: i + 1 }), "error");
            }
          }
        }
      } catch {
        return notify(t(`${m}.err_yaml`), "error");
      }
    }
    setSaving(true);
    try {
      const res = await apiFetch(`${apiBase()}/admin/settings/fs-policy`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ yaml_content: current, enabled }),
      });
      if (res.ok) {
        const data = await res.json();
        if (data.restarting) onRestart();
        else {
          notify(t(`${m}.saved`), "success");
          void load();
        }
      } else {
        const err = await res.json().catch(() => ({}));
        notify(err.detail || t(`${m}.err_save`), "error");
      }
    } catch {
      notify(t(`${m}.err_network`), "error");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex flex-col gap-5">
      <SectionHead
        title={t(`${m}.title`)}
        description={t(`${m}.description`)}
        action={
          <div className="flex items-center gap-3">
            <span className="text-sm text-muted-foreground" aria-hidden>{t(enabled ? `${m}.on` : `${m}.off`)}</span>
            <Switch checked={enabled} onChange={setEnabled} label={t(`${m}.toggle`)} />
          </div>
        }
      />

      {!loaded ? (
        <div className="flex items-center gap-2 px-1 text-sm text-muted-foreground" role="status">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
          {t(`${m}.loading`)}
        </div>
      ) : enabled ? (
        <>
          <Group>
            <ChoiceList<PolicyType>
              value={type}
              onChange={setType}
              label={t(`${m}.template`)}
              options={[
                { value: "dev", title: t(`${m}.dev`), description: t(`${m}.dev_hint`) },
                { value: "production", title: t(`${m}.prod`), description: t(`${m}.prod_hint`) },
                { value: "custom", title: t(`${m}.custom`), description: t(`${m}.custom_hint`) },
              ]}
            />
          </Group>

          <Group
            title={type === "custom" ? t(`${m}.edit`) : t(`${m}.preview`)}
            description={t(`${m}.file`)}
            action={
              type !== "custom" ? (
                <button
                  type="button"
                  className={outlineBtn}
                  onClick={() => {
                    setCustomYaml(type === "dev" ? devYaml : prodYaml);
                    setType("custom");
                  }}
                >
                  {t(`${m}.derive`)}
                </button>
              ) : undefined
            }
          >
            <div className="flex flex-col gap-3 px-5 py-5">
              {type !== "custom" && <Note>{t(`${m}.readonly_note`)}</Note>}
              <PolicyEditor value={current} onChange={(y) => type === "custom" && setCustomYaml(y)} readOnly={type !== "custom"} />
            </div>
          </Group>
        </>
      ) : (
        <Note tone="warn">
          {t(`${m}.disabled_note`)} <Mono>config/fs_policy.yaml</Mono>
        </Note>
      )}

      {loaded && (
        <div className="flex flex-wrap items-center justify-end gap-3">
          {dirty && <span className="text-sm text-muted-foreground" role="status">{t(`${m}.unsaved`)}</span>}
          <button type="button" onClick={() => void save()} disabled={saving || !dirty} className={solidBtn}>
            {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <Save className="h-3.5 w-3.5" aria-hidden />}
            {saving ? t(`${m}.saving`) : t(`${m}.save`)}
          </button>
        </div>
      )}
    </div>
  );
}
