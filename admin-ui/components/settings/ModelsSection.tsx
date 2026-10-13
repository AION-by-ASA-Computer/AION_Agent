"use client";

import { useCallback, useEffect, useState } from "react";
import { Loader2, Pencil, Plus, Save, Star, Trash2 } from "lucide-react";
import { apiFetch } from "@/lib/api/headers";
import { apiBase } from "@/lib/api";
import { cn } from "@/lib/cn";
import { Dialog } from "@/components/profiles/Dialog";
import { DeleteDialog } from "@/components/ui/ConfirmDialogs";
import { Select } from "@/components/ui/Select";
import { ghostBtn, solidBtn, outlineBtn } from "@/components/ui/classes";
import {
  filterModelsForKind,
  formatModelDisplayName,
  hintForModel,
  modelIdsFromProbe,
  pickDefaultModel,
  providerNeedsBaseUrl,
  providerSupportsProbe,
  runModelProbe,
  slugFromModelId,
  validateMaxChatTokens,
} from "@/lib/llm-probe";
import { Field, ModelField, Note, ProbeBar, SecretInput, SectionHead, Switch, TextInput } from "./ui";
import { useProbe } from "./useProbe";
import { K, type SectionCtx } from "./types";

type Provider = {
  id: string | number;
  slug: string;
  display_name: string;
  provider: string;
  model_name: string;
  api_base_url?: string | null;
  api_key_present?: boolean;
  timeout?: number;
  max_chat_tokens?: number | null;
  thinking_token_budget?: number | null;
  enabled?: boolean;
  is_default?: boolean;
};

const EMPTY_FORM = {
  slug: "",
  display_name: "",
  provider: "openai",
  model_name: "",
  api_base_url: "",
  api_key: "",
  timeout: 300,
  max_chat_tokens: null as number | null,
  thinking_token_budget: null as number | null,
  enabled: true,
  is_default: false,
};

const PROVIDER_OPTIONS = [
  { value: "openai", label: "OpenAI" },
  { value: "anthropic", label: "Anthropic" },
  { value: "gemini", label: "Google Gemini" },
  { value: "ollama", label: "Ollama" },
  { value: "vllm", label: "vLLM" },
];

const m = `${K}.models`;

export function ModelsSection({ t, notify }: Pick<SectionCtx, "t" | "notify">) {
  const [providers, setProviders] = useState<Provider[] | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<Provider | null>(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [toDelete, setToDelete] = useState<Provider | null>(null);
  const [deleting, setDeleting] = useState(false);
  const probe = useProbe();

  const load = useCallback(async () => {
    try {
      const res = await apiFetch(`${apiBase()}/admin/llm-providers`);
      const data = await res.json();
      setProviders(Array.isArray(data) ? data : []);
      setLoadFailed(false);
    } catch {
      setLoadFailed(true);
      setProviders((p) => p ?? []);
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch on mount
    void load();
  }, [load]);

  const resetProbe = () => {
    probe.reset();
    setForm((f) => ({ ...f, model_name: "" }));
  };

  const openCreate = () => {
    setForm(EMPTY_FORM);
    setEditing(null);
    probe.reset();
    setFormError(null);
    setFormOpen(true);
  };

  const openEdit = (p: Provider) => {
    setForm({
      slug: p.slug || "",
      display_name: p.display_name || "",
      provider: p.provider || "openai",
      model_name: p.model_name || "",
      api_base_url: p.api_base_url || "",
      api_key: "",
      timeout: p.timeout || 300,
      max_chat_tokens: p.max_chat_tokens || null,
      thinking_token_budget: p.thinking_token_budget || null,
      enabled: p.enabled !== false,
      is_default: p.is_default || false,
    });
    setEditing(p);
    probe.seed(p.model_name);
    setFormError(null);
    setFormOpen(true);
  };

  const closeForm = () => {
    setFormOpen(false);
    setEditing(null);
    setForm(EMPTY_FORM);
    probe.reset();
    setFormError(null);
  };

  const applyModel = (modelId: string, result = probe.result) => {
    const hint = hintForModel(result, modelId);
    setForm((f) => ({
      ...f,
      model_name: modelId,
      display_name: f.display_name || formatModelDisplayName(modelId),
      slug: f.slug || slugFromModelId(modelId, f.provider === "vllm" ? "local" : "default"),
      max_chat_tokens: hint?.suggested_max_chat_tokens ?? f.max_chat_tokens,
    }));
  };

  const changeType = (provider: string) => {
    setForm((f) => ({
      ...f,
      provider,
      model_name: "",
      max_chat_tokens: provider === "ollama" ? 4096 : f.max_chat_tokens,
      thinking_token_budget: provider === "gemini" || provider === "ollama" ? 0 : f.thinking_token_budget,
    }));
    probe.reset();
  };

  const runProbe = async (): Promise<boolean> => {
    if (providerNeedsBaseUrl(form.provider) && !form.api_base_url.trim()) {
      setFormError(t(`${m}.err_base_url`));
      return false;
    }
    const needsKey = form.provider !== "ollama";
    if (needsKey && !form.api_key.trim() && !(editing && editing.api_key_present)) {
      setFormError(t(`${m}.err_key_test`));
      return false;
    }
    probe.setProbing(true);
    setFormError(null);
    probe.setLatency(null);
    try {
      const result = await runModelProbe(apiFetch, apiBase(), {
        provider: form.provider,
        api_base_url: form.api_base_url.trim() || null,
        api_key: form.api_key.trim() || null,
        slug: editing ? editing.slug : null,
      });
      const all = modelIdsFromProbe(result);
      const chat = filterModelsForKind(all, "chat");
      probe.setResult(result);
      probe.setIds(chat);
      probe.setTested(true);
      probe.setLatency(result.latency_ms);
      setForm((f) => ({ ...f, api_base_url: result.base_url || f.api_base_url }));
      if (chat.length > 0) {
        probe.setManual(false);
        applyModel(pickDefaultModel(all, "chat"), result);
      } else {
        probe.setManual(true);
        setForm((f) => ({ ...f, model_name: "" }));
      }
      if (result.warning) setFormError(result.warning);
      return true;
    } catch (err) {
      resetProbe();
      setFormError(err instanceof Error ? err.message : t(`${m}.err_test_failed`));
      return false;
    } finally {
      probe.setProbing(false);
    }
  };

  const save = async () => {
    setFormError(null);
    if (!form.slug || !form.display_name) return setFormError(t(`${m}.err_slug_name`));
    if (!form.api_key && form.provider !== "ollama" && !editing) return setFormError(t(`${m}.err_key`));

    if (!form.api_key && form.provider !== "ollama" && editing) {
      if (!form.model_name.trim()) return setFormError(t(`${m}.err_model`));
    } else {
      if (!probe.tested) {
        const ok = await runProbe();
        if (!ok) return;
      }
      if (!form.model_name.trim()) {
        return setFormError(t(probe.manual ? `${m}.err_model_manual` : `${m}.err_model_select`));
      }
    }
    if (form.max_chat_tokens != null) {
      const err = validateMaxChatTokens(form.max_chat_tokens, Number(form.thinking_token_budget) || 0, hintForModel(probe.result, form.model_name));
      if (err) return setFormError(err);
    }

    setSaving(true);
    try {
      const body: Record<string, unknown> = {
        slug: form.slug,
        display_name: form.display_name,
        provider: form.provider,
        model_name: form.model_name,
        api_base_url: form.api_base_url || null,
        timeout: form.timeout,
        max_chat_tokens: form.max_chat_tokens ?? null,
        thinking_token_budget: form.thinking_token_budget ?? null,
        enabled: form.enabled,
        is_default: form.is_default || false,
      };
      if (form.api_key) body.api_key = form.api_key;
      const res = await apiFetch(editing ? `${apiBase()}/admin/llm-providers/${editing.slug}` : `${apiBase()}/admin/llm-providers`, {
        method: editing ? "PUT" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (res.ok) {
        closeForm();
        void load();
        notify(t(form.is_default ? `${m}.saved_default` : `${m}.saved`), "success");
      } else {
        const data = await res.json().catch(() => ({}));
        setFormError(data.detail || t(`${m}.err_save`));
      }
    } catch {
      setFormError(t(`${m}.err_network`));
    } finally {
      setSaving(false);
    }
  };

  const makeDefault = async (slug: string) => {
    try {
      const res = await apiFetch(`${apiBase()}/admin/llm-providers/${slug}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ is_default: true }),
      });
      if (res.ok) {
        void load();
        notify(t(`${m}.default_set`), "success");
      } else {
        const data = await res.json().catch(() => ({}));
        notify(data.detail || t(`${m}.err_default`), "error");
      }
    } catch {
      notify(t(`${m}.err_network`), "error");
    }
  };

  const remove = async () => {
    if (!toDelete) return;
    setDeleting(true);
    try {
      const res = await apiFetch(`${apiBase()}/admin/llm-providers/${toDelete.slug}`, { method: "DELETE" });
      if (res.ok) {
        notify(t(`${m}.deleted`), "success");
        void load();
      } else {
        const data = await res.json().catch(() => ({}));
        notify(data.detail || t(`${m}.err_delete`), "error");
      }
    } catch {
      notify(t(`${m}.err_network`), "error");
    } finally {
      setDeleting(false);
      setToDelete(null);
    }
  };

  const hint = hintForModel(probe.result, form.model_name);
  const list = providers ?? [];

  return (
    <div className="flex flex-col gap-5">
      <SectionHead
        title={t(`${m}.title`)}
        description={t(`${m}.description`)}
        action={
          <button type="button" onClick={openCreate} className={solidBtn}>
            <Plus className="h-3.5 w-3.5" aria-hidden />
            {t(`${m}.add`)}
          </button>
        }
      />

      {providers === null ? (
        <div className="flex items-center gap-2 px-1 text-sm text-muted-foreground" role="status">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
          {t(`${m}.loading`)}
        </div>
      ) : loadFailed && list.length === 0 ? (
        <div className="flex flex-col items-start gap-3 rounded-3xl border border-dashed border-border px-6 py-12">
          <p className="text-sm text-destructive" role="alert">{t(`${m}.load_error`)}</p>
          <button type="button" className={outlineBtn} onClick={() => void load()}>{t(`${m}.retry`)}</button>
        </div>
      ) : list.length === 0 ? (
        <div className="flex flex-col items-start gap-3 rounded-3xl border border-dashed border-border px-6 py-12">
          <h3 className="text-base font-semibold tracking-[-0.015em]">{t(`${m}.empty_title`)}</h3>
          <p className="max-w-[48ch] text-sm text-muted-foreground">{t(`${m}.empty_body`)}</p>
          <button type="button" onClick={openCreate} className={solidBtn}>
            <Plus className="h-3.5 w-3.5" aria-hidden />
            {t(`${m}.add_first`)}
          </button>
        </div>
      ) : (
        <ul className="divide-y divide-border/40 overflow-hidden rounded-3xl border border-border/60 bg-card/40">
          {list.map((p) => (
            <li key={p.id} className="grid items-center gap-x-6 gap-y-2 px-5 py-4 md:grid-cols-[minmax(0,1.3fr)_minmax(0,1.6fr)_auto_auto]">
              <div className="min-w-0">
                <p className="flex flex-wrap items-center gap-2 text-sm font-semibold">
                  <span className="truncate">{p.display_name}</span>
                  {p.is_default && (
                    <span className="inline-flex items-center gap-1 rounded-md bg-secondary px-1.5 py-0.5 text-[11px] font-medium text-foreground">
                      <Star className="h-3 w-3 fill-current" aria-hidden />
                      {t(`${m}.default_badge`)}
                    </span>
                  )}
                </p>
                <p className="mt-0.5 truncate font-mono text-xs text-muted-foreground">{p.slug}</p>
              </div>
              <div className="min-w-0">
                <p className="truncate text-sm">
                  <span className="text-muted-foreground">{PROVIDER_OPTIONS.find((o) => o.value === p.provider)?.label ?? p.provider}</span>
                  <span className="mx-1.5 text-muted-foreground/50" aria-hidden>·</span>
                  <span className="font-mono text-[13px]">{p.model_name}</span>
                </p>
                <p className="mt-0.5 truncate font-mono text-xs text-muted-foreground" title={p.api_base_url || undefined}>
                  {p.api_base_url || t(`${m}.no_url`)}
                </p>
              </div>
              <span className={cn("inline-flex items-center gap-1.5 text-sm font-medium", p.enabled ? "text-success" : "text-muted-foreground")}>
                <span className={cn("h-2 w-2 rounded-full", p.enabled ? "bg-success" : "bg-muted-foreground/60")} aria-hidden />
                {t(p.enabled ? `${m}.active` : `${m}.disabled`)}
              </span>
              <div className="flex items-center justify-end gap-0.5">
                <IconBtn label={t(`${m}.set_default`)} disabled={!!p.is_default} onClick={() => void makeDefault(p.slug)}>
                  <Star className="h-4 w-4" aria-hidden />
                </IconBtn>
                <IconBtn label={t(`${m}.edit`)} onClick={() => openEdit(p)}>
                  <Pencil className="h-4 w-4" aria-hidden />
                </IconBtn>
                <IconBtn label={t(`${m}.delete`)} danger onClick={() => setToDelete(p)}>
                  <Trash2 className="h-4 w-4" aria-hidden />
                </IconBtn>
              </div>
            </li>
          ))}
        </ul>
      )}

      {formOpen && (
        <Dialog title={t(editing ? `${m}.form_edit` : `${m}.form_new`)} closeLabel={t(`${m}.cancel`)} onClose={closeForm} className="max-w-2xl overflow-y-auto max-h-[92vh]">
          <form
            className="flex flex-col gap-5"
            onSubmit={(e) => {
              e.preventDefault();
              void save();
            }}
          >
            <div className="grid gap-x-5 gap-y-4 md:grid-cols-2">
              <Field label={t(`${m}.provider`)} wide>
                <Select value={form.provider} onChange={changeType} options={PROVIDER_OPTIONS} aria-label={t(`${m}.provider`)} />
              </Field>

              {form.provider !== "ollama" && (
                <Field label={t(`${m}.api_key`)} wide hint={t(editing ? `${m}.api_key_keep` : `${m}.api_key_hint`)}>
                  <SecretInput
                    value={form.api_key}
                    onChange={(v) => {
                      setForm((f) => ({ ...f, api_key: v }));
                      if (v) probe.reset();
                    }}
                    placeholder={editing ? "sk-…" : t(`${m}.api_key_ph`)}
                    showLabel={t(`${K}.show_secret`)}
                    hideLabel={t(`${K}.hide_secret`)}
                  />
                </Field>
              )}

              <Field label={t(providerNeedsBaseUrl(form.provider) ? `${m}.base_url` : `${m}.base_url_optional`)} wide>
                <TextInput
                  value={form.api_base_url}
                  mono
                  onChange={(v) => {
                    setForm((f) => ({ ...f, api_base_url: v }));
                    probe.reset();
                  }}
                  placeholder={form.provider === "ollama" ? "http://localhost:11434/v1" : form.provider === "vllm" ? "http://localhost:8000/v1" : "https://"}
                />
              </Field>

              {providerSupportsProbe(form.provider) && (
                <ProbeBar
                  probing={probe.probing}
                  onProbe={() => void runProbe()}
                  label={t(`${m}.test`)}
                  ok={probe.tested && probe.latency != null}
                  okText={t(probe.ids.length > 0 ? `${m}.test_ok` : `${m}.test_ok_manual`, { ms: probe.latency ?? 0, count: probe.ids.length })}
                />
              )}

              <ModelField
                label={t(`${m}.model`)}
                manualLabel={t(`${m}.model_manual`)}
                tested={probe.tested}
                manual={probe.manual}
                ids={probe.ids}
                value={form.model_name}
                onChange={(v) => (probe.manual ? setForm((f) => ({ ...f, model_name: v, display_name: f.display_name || (v ? formatModelDisplayName(v) : ""), slug: f.slug || (v ? slugFromModelId(v, f.provider === "vllm" ? "local" : "default") : "") })) : applyModel(v))}
                hintBefore={t(editing ? `${m}.model_before_edit` : `${m}.model_before`)}
                manualPlaceholder={t(`${m}.model_manual_ph`)}
                hint={!probe.manual && hint ? t(`${m}.context_window`, { n: hint.context_window.toLocaleString() }) : undefined}
              />

              <Field label={t(`${m}.display_name`)}>
                <TextInput value={form.display_name} onChange={(v) => setForm((f) => ({ ...f, display_name: v }))} placeholder="Qwen 3 32B" />
              </Field>
              <Field label={t(`${m}.slug`)} hint={t(`${m}.slug_hint`)}>
                <TextInput value={form.slug} mono disabled={!!editing} onChange={(v) => setForm((f) => ({ ...f, slug: v }))} placeholder="qwen3-32b" />
              </Field>

              <Field label={t(`${m}.timeout`)}>
                <TextInput type="number" inputMode="numeric" value={String(form.timeout || "")} onChange={(v) => setForm((f) => ({ ...f, timeout: parseInt(v) || 0 }))} />
              </Field>
              <Field label={t(`${m}.max_tokens`)} env="AION_CHAT_MAX_TOKENS">
                <TextInput type="number" inputMode="numeric" value={form.max_chat_tokens ? String(form.max_chat_tokens) : ""} onChange={(v) => setForm((f) => ({ ...f, max_chat_tokens: v ? parseInt(v) : null }))} placeholder="4096" />
              </Field>
              <Field label={t(`${m}.thinking`)} env="AION_THINKING_TOKEN_BUDGET">
                <TextInput type="number" inputMode="numeric" value={form.thinking_token_budget ? String(form.thinking_token_budget) : ""} onChange={(v) => setForm((f) => ({ ...f, thinking_token_budget: v ? parseInt(v) : null }))} placeholder="1024" />
              </Field>
            </div>

            <ul className="divide-y divide-border/40 rounded-2xl border border-border/60">
              <li className="flex items-center gap-4 px-4 py-3">
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium">{t(`${m}.enabled`)}</p>
                  <p className="text-xs text-muted-foreground">{t(`${m}.enabled_hint`)}</p>
                </div>
                <Switch checked={form.enabled} onChange={(v) => setForm((f) => ({ ...f, enabled: v }))} label={t(`${m}.enabled`)} />
              </li>
              <li className="flex items-center gap-4 px-4 py-3">
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium">{t(`${m}.make_default`)}</p>
                  <p className="text-xs text-muted-foreground">{t(`${m}.make_default_hint`)}</p>
                </div>
                <Switch checked={form.is_default} onChange={(v) => setForm((f) => ({ ...f, is_default: v }))} label={t(`${m}.make_default`)} />
              </li>
            </ul>

            {formError && <Note tone="warn">{formError}</Note>}

            <div className="flex justify-end gap-2">
              <button type="button" className={ghostBtn} onClick={closeForm}>{t(`${m}.cancel`)}</button>
              <button type="submit" disabled={saving} className={solidBtn}>
                {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <Save className="h-3.5 w-3.5" aria-hidden />}
                {saving ? t(`${m}.saving`) : t(`${m}.save`)}
              </button>
            </div>
          </form>
        </Dialog>
      )}

      {toDelete && <DeleteDialog name={toDelete.slug} busy={deleting} ns={`${m}.delete_dialog`} t={t} onConfirm={() => void remove()} onClose={() => setToDelete(null)} />}
    </div>
  );
}

function IconBtn({ label, onClick, disabled, danger, children }: { label: string; onClick: () => void; disabled?: boolean; danger?: boolean; children: React.ReactNode }) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "focus-ring inline-flex h-9 w-9 items-center justify-center rounded-xl text-muted-foreground transition-colors hover:bg-secondary disabled:pointer-events-none disabled:opacity-35",
        danger ? "hover:text-destructive" : "hover:text-foreground",
      )}
    >
      {children}
    </button>
  );
}
