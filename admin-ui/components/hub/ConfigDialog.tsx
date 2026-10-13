"use client";

import { AlertTriangle, CheckCircle2, EyeOff, Loader2, Lock, Shield, ShieldCheck, ToggleRight, Users } from "lucide-react";
import { cn } from "@/lib/cn";
import { Select } from "@/components/ui/Select";
import { Dialog } from "@/components/profiles/Dialog";
import { ghostBtn, inputCls, solidBtn } from "@/components/ui/classes";
import { KeyValueBuilder } from "@/components/KeyValueBuilder";
import { CredentialSchemaEditor } from "@/components/CredentialSchemaEditor";
import { RegistryEnvPanel, SchemaSuggestion } from "@/components/hub/CredentialSetup";
import { McpOAuthAdminSetupPanel } from "@/components/McpOAuthAdminSetupPanel";
import type { CredentialMode } from "@/lib/mcpIntegrationPolicy";
import { schemaSig, type Hub } from "@/components/hub/useHub";
import { useState } from "react";

/* eslint-disable @typescript-eslint/no-explicit-any */

const MODES: { mode: CredentialMode; icon: typeof Shield }[] = [
  { mode: "none", icon: Shield },
  { mode: "org_shared", icon: ShieldCheck },
  { mode: "per_user", icon: Users },
];

const AVAILABILITY: { id: "hidden" | "optional" | "required"; icon: typeof Shield }[] = [
  { id: "hidden", icon: EyeOff },
  { id: "optional", icon: ToggleRight },
  { id: "required", icon: Lock },
];

const labelCls = "text-sm font-medium";
const hintCls = "text-xs text-muted-foreground";

/** Remove `--header` pairs injected for per-user auth once the server stops needing them. */
function stripHeaderArgs(args: string[]): string[] {
  const out: string[] = [];
  for (let i = 0; i < args.length; i++) {
    if (args[i] === "--header") {
      i++;
      continue;
    }
    out.push(args[i]);
  }
  return out;
}

export function ConfigDialog({ hub }: { hub: Hub }) {
  const { t, editing, editingPolicy } = hub;
  const k = "admin_hub.config";
  const [section, setSection] = useState<"runtime" | "policy">("runtime");
  if (!editing) return null;

  const v = editing.values;
  const setValues = (patch: Record<string, unknown>) => hub.setEditing({ ...editing, values: { ...v, ...patch } });
  const remote = v.type === "sse" || v.type === "remote-bridge";
  const argsText: string = v.rawArgsText ?? (v.args || []).join("\n");
  const matched = hub.formContext.matched as { id?: string } | null;

  const availability: "hidden" | "optional" | "required" = !editingPolicy?.enabled ? "hidden" : hub.userMayDisable ? "optional" : "required";

  const registryYaml: string =
    (editingPolicy && hub.integrationBySlug[editing.name]?.suggested_env_yaml) ||
    (editingPolicy && editingPolicy.credentialSchema.length > 0
      ? `env:\n${editingPolicy.credentialSchema
          .filter((f) => f.env_placeholder)
          .map((f) => `  ${f.registry_env_key || f.key}: "${f.env_placeholder}"`)
          .join("\n")}`
      : "");
  const currentEnv: Record<string, unknown> = v.env || {};
  const overwriteKeys = Array.from(registryYaml.matchAll(/^ {2}([^\s:]+):/gm))
    .map((m) => m[1])
    .filter((key) => String(currentEnv[key] ?? "").trim() !== "");

  const tabs: { id: "runtime" | "policy"; label: string; badge?: string }[] = [
    { id: "runtime", label: t(`${k}.tab_runtime`) },
    {
      id: "policy",
      label: t(`${k}.tab_policy`),
      badge:
        editingPolicy?.mode === "per_user" ? t("admin_hub.scope.per_user") : editingPolicy?.mode === "org_shared" ? t("admin_hub.scope.org_shared") : undefined,
    },
  ];

  return (
    <Dialog title={editing.name} closeLabel={t(`${k}.cancel`)} onClose={hub.closeConfig} className="max-w-3xl">
      <div className="flex flex-col gap-5">
        <p className="-mt-1 text-sm text-muted-foreground">{t(`${k}.subtitle`)}</p>

        <div role="tablist" aria-label={t(`${k}.tabs_aria`)} className="flex gap-1 border-b border-border">
          {tabs.map((tb) => {
            const active = section === tb.id;
            return (
              <button
                key={tb.id}
                type="button"
                role="tab"
                aria-selected={active}
                onClick={() => setSection(tb.id)}
                className={cn(
                  "focus-ring -mb-px flex items-center gap-2 border-b-2 px-3 pb-2.5 pt-1 text-sm font-medium transition-colors",
                  active ? "border-foreground text-foreground" : "border-transparent text-muted-foreground hover:text-foreground",
                )}
              >
                {tb.label}
                {tb.badge && <span className="rounded-md bg-secondary px-1.5 py-0.5 text-[11px] font-medium text-muted-foreground">{tb.badge}</span>}
              </button>
            );
          })}
        </div>

        <div className="max-h-[56vh] overflow-y-auto pr-1">
          {section === "runtime" && (
            <div className="flex flex-col gap-4" role="tabpanel">
              <div className="grid gap-4 sm:grid-cols-2">
                <label className="flex flex-col gap-1.5">
                  <span className={labelCls}>{t(`${k}.connector`)}</span>
                  <Select
                    value={v.aion_connector_id ?? ""}
                    onChange={(val) => setValues({ aion_connector_id: val || undefined })}
                    options={[
                      { value: "", label: t(`${k}.connector_auto`) },
                      ...hub.connectorRows.map((c: any) => ({ value: String(c.id), label: String(c.title || c.id) })),
                    ]}
                  />
                  {matched && (
                    <span className="flex items-center gap-1 font-mono text-xs text-success">
                      <CheckCircle2 className="h-3 w-3" aria-hidden />
                      {t(`${k}.matched`, { id: String(matched.id) })}
                    </span>
                  )}
                </label>

                <label className="flex flex-col gap-1.5">
                  <span className={labelCls}>{t(`${k}.connection`)}</span>
                  <Select
                    value={v.type ?? "stdio"}
                    onChange={(val) =>
                      setValues({
                        type: val,
                        ...(["sse", "remote-bridge"].includes(val) ? { command: undefined, args: undefined, rawArgsText: "" } : {}),
                      })
                    }
                    options={(["stdio", "sse", "remote-bridge", "in_process"] as const).map((id) => ({
                      value: id,
                      label: t(`admin_hub.runtime.${id}`),
                    }))}
                  />
                </label>
              </div>

              {remote ? (
                <label className="flex flex-col gap-1.5">
                  <span className={labelCls}>{v.type === "remote-bridge" ? t(`${k}.bridge_url`) : t(`${k}.endpoint_url`)}</span>
                  <input
                    type="text"
                    value={(v.type === "remote-bridge" ? v.remote_url : v.url) ?? ""}
                    onChange={(e) => setValues(v.type === "remote-bridge" ? { remote_url: e.target.value } : { url: e.target.value })}
                    placeholder={v.type === "remote-bridge" ? "https://bridge.example.com" : "https://example.com/sse"}
                    className={cn(inputCls, "font-mono")}
                  />
                </label>
              ) : v.type !== "in_process" ? (
                <>
                  <label className="flex flex-col gap-1.5">
                    <span className={labelCls}>{t(`${k}.command`)}</span>
                    <input
                      type="text"
                      value={v.command ?? ""}
                      onChange={(e) => setValues({ command: e.target.value })}
                      placeholder="npx, python, node…"
                      className={cn(inputCls, "font-mono")}
                    />
                  </label>
                  <label className="flex flex-col gap-1.5">
                    <span className={labelCls}>
                      {t(`${k}.args`)} <span className="font-normal text-muted-foreground">· {t(`${k}.args_hint`)}</span>
                    </span>
                    <textarea
                      rows={Math.max(3, argsText.split("\n").length + 1)}
                      value={argsText}
                      onChange={(e) =>
                        setValues({
                          rawArgsText: e.target.value,
                          args: e.target.value
                            .split("\n")
                            .map((l) => l.trim())
                            .filter(Boolean),
                        })
                      }
                      placeholder={"mcp-server\n--port\n8080"}
                      className={cn(inputCls, "resize-y font-mono")}
                    />
                  </label>
                </>
              ) : null}

              <label className="flex flex-col gap-1.5">
                <span className={labelCls}>{t(`${k}.description`)}</span>
                <textarea
                  rows={3}
                  value={v.description || ""}
                  onChange={(e) => setValues({ description: e.target.value })}
                  placeholder={t(`${k}.description_placeholder`)}
                  className={cn(inputCls, "resize-y")}
                />
              </label>

              {editingPolicy && (
                <fieldset className="flex flex-col gap-2">
                  <legend className={cn(labelCls, "mb-2")}>{t(`${k}.availability`)}</legend>
                  <div className="grid gap-2 sm:grid-cols-3">
                    {AVAILABILITY.map(({ id, icon: Icon }) => {
                      const selected = availability === id;
                      return (
                        <button
                          key={id}
                          type="button"
                          aria-pressed={selected}
                          onClick={() => {
                            hub.setEditingPolicy({ ...editingPolicy, enabled: id !== "hidden" });
                            if (id !== "hidden") hub.setUserMayDisable(id === "optional");
                          }}
                          className={cn(
                            "focus-ring flex flex-col gap-1 rounded-2xl border p-3.5 text-left transition-colors",
                            selected ? "border-foreground bg-secondary" : "border-border hover:border-foreground/30",
                          )}
                        >
                          <span className="flex items-center gap-2 text-sm font-semibold">
                            <Icon className="h-4 w-4 text-muted-foreground" aria-hidden />
                            {t(`${k}.availability_${id}`)}
                          </span>
                          <span className={hintCls}>{t(`${k}.availability_${id}_hint`)}</span>
                        </button>
                      );
                    })}
                  </div>
                </fieldset>
              )}
            </div>
          )}

          {section === "policy" && editingPolicy && (
            <div className="flex flex-col gap-5" role="tabpanel">
              <fieldset className="flex flex-col gap-2">
                <legend className={cn(labelCls, "mb-2")}>{t(`${k}.mode`)}</legend>
                <div className="grid gap-2 sm:grid-cols-3">
                  {MODES.map(({ mode, icon: Icon }) => {
                    const selected = editingPolicy.mode === mode;
                    return (
                      <button
                        key={mode}
                        type="button"
                        aria-pressed={selected}
                        onClick={() => {
                          hub.setEditingPolicy({ ...editingPolicy, mode });
                          void hub.loadPolicyPreview(editing.name, mode);
                          if (mode === "none" && Array.isArray(v.args)) {
                            const cleaned = stripHeaderArgs(v.args);
                            if (cleaned.length !== v.args.length) setValues({ args: cleaned });
                          }
                        }}
                        className={cn(
                          "focus-ring flex flex-col gap-1 rounded-2xl border p-3.5 text-left transition-colors",
                          selected ? "border-foreground bg-secondary" : "border-border hover:border-foreground/30",
                        )}
                      >
                        <span className="flex items-center gap-2 text-sm font-semibold">
                          <Icon className="h-4 w-4 text-muted-foreground" aria-hidden />
                          {t(`admin_hub.scope.${mode}`)}
                        </span>
                        <span className={hintCls}>{t(`${k}.mode_${mode}`)}</span>
                      </button>
                    );
                  })}
                </div>
              </fieldset>

              {editingPolicy.warnings.map((w) => (
                <p key={w} className="flex gap-2 rounded-2xl bg-warning/12 px-3.5 py-2.5 text-sm" role="status">
                  <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" aria-hidden />
                  <span>{w}</span>
                </p>
              ))}

              {editingPolicy.mode === "none" && (
                <p className="rounded-2xl bg-secondary/60 px-4 py-3.5 text-sm text-muted-foreground">{t(`${k}.none_body`)}</p>
              )}

              {editingPolicy.mode === "org_shared" && (
                <KeyValueBuilder env={v.env || {}} onChange={(env) => setValues({ env, rawAllEnvText: JSON.stringify(env, null, 2) })} disabled={hub.busy} />
              )}

              {editingPolicy.mode === "per_user" && (
                <div className="flex flex-col gap-4">
                  <SchemaSuggestion
                    suggested={editingPolicy.previewSchema}
                    current={editingPolicy.credentialSchema}
                    onAdd={(missing) =>
                      hub.setEditingPolicy({ ...editingPolicy, credentialSchema: [...editingPolicy.credentialSchema, ...missing] })
                    }
                  />
                  <CredentialSchemaEditor
                    value={editingPolicy.credentialSchema}
                    onChange={(credentialSchema) => hub.setEditingPolicy({ ...editingPolicy, credentialSchema })}
                  />
                  <RegistryEnvPanel
                    yaml={registryYaml}
                    dirty={schemaSig(editingPolicy.credentialSchema) !== editingPolicy.savedSig}
                    busy={hub.busy}
                    overwriteKeys={overwriteKeys}
                    onApply={() => void hub.applySuggestedEnv()}
                  />
                  {(v.type === "remote-bridge" || hub.oauthConfig.authorization_server || hub.formContext.matched) && (
                    <McpOAuthAdminSetupPanel
                      connector={hub.formContext.matched}
                      oauthConfig={hub.oauthConfig}
                      onChange={(patch) => hub.setOauthConfig((prev) => ({ ...prev, ...patch }))}
                    />
                  )}
                </div>
              )}
            </div>
          )}
        </div>

        <div className="flex justify-end gap-2 border-t border-border pt-4">
          <button type="button" className={ghostBtn} onClick={hub.closeConfig}>
            {t(`${k}.cancel`)}
          </button>
          <button type="button" className={solidBtn} disabled={hub.busy} onClick={() => void hub.saveConfig()}>
            {hub.busy && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />}
            {hub.busy ? t(`${k}.saving`) : t(`${k}.save`)}
          </button>
        </div>
      </div>
    </Dialog>
  );
}
