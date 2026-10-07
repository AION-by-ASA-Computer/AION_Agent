"use client";

import { useMemo, useState } from "react";
import {
  Check,
  ChevronDown,
  Eye,
  EyeOff,
  Globe,
  KeyRound,
  Loader2,
  Lock,
  Plug,
  Plus,
  Server,
  Shield,
  SlidersHorizontal,
  Trash2,
  X,
} from "lucide-react";

import type { CredentialField, Integration } from "@/components/integrations/types";
import { apiBase, oauthCallbackRedirectUri } from "@/lib/config";
import { jsonHeaders } from "@/lib/api/aion";
import { oauthManagedFieldKeys, oauthProviderDisplayName } from "@/lib/integrations/oauthLabels";
import {
  formatFieldLabel,
  isAdvancedField,
  isBooleanField,
  isSecretField,
} from "@/lib/integrations/field-labels";
import { Switch } from "@/components/ui/Switch";
import { useT } from "@/lib/i18n/use-t";
import { cn } from "@/lib/cn";

const MASKED_SECRET_VALUE = "••••••••••••";

interface CustomFieldItem {
  id: string;
  key: string;
  label: string;
  type: "password" | "text" | "boolean";
  required: boolean;
}

export function CredentialConfigDialog({
  integration,
  userId,
  token,
  onClose,
}: {
  integration: Integration;
  userId: string;
  token: string | null;
  onClose: () => void;
}) {
  const t = useT();

  const oauthManaged = useMemo(() => oauthManagedFieldKeys(), []);
  const providerLabel = oauthProviderDisplayName(integration);

  const hasOAuthToken = useMemo(
    () => integration.credentials_hints.some((h) => h.key === "OAUTH_TOKEN" && !h.is_expired),
    [integration.credentials_hints],
  );

  const savedKeys = useMemo(
    () => new Set(integration.credentials_hints.map((h) => h.key)),
    [integration.credentials_hints],
  );

  const [customFields, setCustomFields] = useState<CustomFieldItem[]>([]);
  const [deletedKeys, setDeletedKeys] = useState<Set<string>>(new Set());
  const [deletingKeys, setDeletingKeys] = useState<Record<string, boolean>>({});
  const [loadingSecretKeys, setLoadingSecretKeys] = useState<Record<string, boolean>>({});

  const formFields = useMemo(() => {
    const seen = new Set<string>();
    const out: CredentialField[] = [];

    // Campi definiti dallo schema / connettore
    for (const f of integration.credential_schema) {
      if (!f.key || seen.has(f.key) || deletedKeys.has(f.key)) continue;
      if (integration.has_oauth && oauthManaged.has(f.key)) continue;
      seen.add(f.key);
      out.push(f);
    }

    // Campi personalizzati aggiunti dall'utente nel modale
    for (const c of customFields) {
      const key = normalizeKey(c.key);
      if (!key || seen.has(key) || deletedKeys.has(key)) continue;
      if (integration.has_oauth && oauthManaged.has(key)) continue;
      seen.add(key);
      out.push({
        key,
        label: c.label.trim() || key,
        type: c.type,
        category: "advanced",
        required: c.required,
      });
    }
    return out;
  }, [integration.credential_schema, integration.has_oauth, customFields, oauthManaged, deletedKeys]);

  // Precompilazione delle vecchie credenziali nei relativi input
  const initialValues = useMemo(() => {
    const init: Record<string, string> = {};
    for (const f of formFields) {
      const hint = integration.credentials_hints.find((h) => h.key === f.key);
      const isSec = isSecretField(f);
      const isBool = isBooleanField(f);

      if (hint) {
        if (isBool) {
          const val = (hint.display_hint || "").toLowerCase();
          init[f.key] = val.includes("attivo") || val.includes("true") ? "true" : "false";
        } else if (isSec) {
          // Campi secret salvati: testo censurato
          init[f.key] = MASKED_SECRET_VALUE;
        } else {
          // Campi testo non-secret: mostriamo il valore precedente
          let val = hint.display_hint || "";
          if (val.endsWith("…")) {
            val = val.slice(0, -1);
          }
          init[f.key] = val || (f.default_value !== undefined ? String(f.default_value) : "");
        }
      } else if (f.default_value !== undefined) {
        init[f.key] = String(f.default_value);
      }
    }
    return init;
  }, [formFields, integration.credentials_hints]);

  const [values, setValues] = useState<Record<string, string>>(initialValues);
  const [showPasswords, setShowPasswords] = useState<Record<string, boolean>>({});
  const [isAdvancedOpen, setIsAdvancedOpen] = useState(false);
  const [attemptedSave, setAttemptedSave] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const { basicFields, advancedFields } = useMemo(() => {
    const basic: CredentialField[] = [];
    const adv: CredentialField[] = [];

    for (const f of formFields) {
      if (isAdvancedField(f)) {
        adv.push(f);
      } else {
        basic.push(f);
      }
    }
    return { basicFields: basic, advancedFields: adv };
  }, [formFields]);

  function getOAuthButtonText() {
    return t("integrationsPage.oauth_login_service", { service: providerLabel });
  }

  async function handleOAuthLogin() {
    const redirectUri = oauthCallbackRedirectUri();
    try {
      const res = await fetch(
        `${apiBase()}/v1/integrations/oauth/start?server_slug=${encodeURIComponent(integration.server_slug)}&redirect_uri=${encodeURIComponent(redirectUri)}`,
        { headers: jsonHeaders(userId, token) },
      );
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        setError((err as { detail?: string }).detail || t("integrationsPage.oauth_start_error"));
        return;
      }
      const data = (await res.json()) as { authorization_url: string; state: string };
      localStorage.setItem("oauth_state", data.state);
      localStorage.setItem("oauth_server_slug", integration.server_slug);
      window.location.href = data.authorization_url;
    } catch {
      setError(t("integrationsPage.oauth_network_error"));
    }
  }

  function addCustomField() {
    const count = customFields.length + 1;
    setCustomFields((prev) => [
      ...prev,
      {
        id: `cf-${Date.now()}-${count}`,
        key: `CUSTOM_VAR_${count}`,
        label: "",
        type: "password",
        required: false,
      },
    ]);
    setIsAdvancedOpen(true);
  }

  function removeCustomField(id: string, key?: string) {
    if (key) {
      const norm = normalizeKey(key);
      setValues((prev) => {
        const next = { ...prev };
        delete next[norm];
        delete next[key];
        return next;
      });
    }
    setCustomFields((prev) => prev.filter((c) => c.id !== id));
  }

  function updateCustomFieldType(id: string, type: "password" | "text" | "boolean") {
    setCustomFields((prev) =>
      prev.map((c) => {
        if (c.id !== id) return c;
        return { ...c, type };
      }),
    );
    const target = customFields.find((c) => c.id === id);
    if (target && type === "boolean") {
      const k = normalizeKey(target.key);
      if (!values[k]) {
        setValues((v) => ({ ...v, [k]: "false" }));
      }
    }
  }

  function updateCustomFieldRequired(id: string, required: boolean) {
    setCustomFields((prev) =>
      prev.map((c) => (c.id === id ? { ...c, required } : c)),
    );
  }

  function normalizeKey(raw: string) {
    return raw.trim().toUpperCase().replace(/\s+/g, "_");
  }

  async function toggleShowPassword(key: string) {
    if (showPasswords[key]) {
      setShowPasswords((prev) => ({ ...prev, [key]: false }));
      return;
    }

    // Se il valore è la maschera di censura ed è salvato sul server, recuperiamo il testo in chiaro decifrato
    if (values[key] === MASKED_SECRET_VALUE && savedKeys.has(key)) {
      setLoadingSecretKeys((prev) => ({ ...prev, [key]: true }));
      try {
        const res = await fetch(
          `${apiBase()}/v1/integrations/credentials/${encodeURIComponent(integration.server_slug)}/${encodeURIComponent(key)}`,
          { headers: jsonHeaders(userId, token) },
        );
        if (res.ok) {
          const data = (await res.json()) as { key: string; value: string };
          if (typeof data.value === "string") {
            setValues((v) => ({ ...v, [key]: data.value }));
            setShowPasswords((prev) => ({ ...prev, [key]: true }));
            return;
          }
        }
      } catch (err) {
        console.error("Errore recupero credenziale in chiaro:", err);
      } finally {
        setLoadingSecretKeys((prev) => ({ ...prev, [key]: false }));
      }
    }

    setShowPasswords((prev) => ({ ...prev, [key]: true }));
  }

  async function handleDeleteField(field: CredentialField, customId?: string) {
    if (customId) {
      removeCustomField(customId, field.key);
      return;
    }

    const key = field.key;
    if (savedKeys.has(key)) {
      setDeletingKeys((prev) => ({ ...prev, [key]: true }));
      try {
        const res = await fetch(
          `${apiBase()}/v1/integrations/credentials/${encodeURIComponent(integration.server_slug)}/${encodeURIComponent(key)}`,
          {
            method: "DELETE",
            headers: jsonHeaders(userId, token),
          },
        );
        if (!res.ok) {
          console.error("Errore cancellazione credenziale dal server");
        }
      } catch (e) {
        console.error("Errore cancellazione credenziale:", e);
      } finally {
        setDeletingKeys((prev) => ({ ...prev, [key]: false }));
      }
    }

    setDeletedKeys((prev) => new Set([...prev, key]));
    setValues((prev) => {
      const next = { ...prev };
      delete next[key];
      return next;
    });
  }

  function getBooleanValue(key: string, defaultValue?: string | boolean): boolean {
    if (values[key] !== undefined) {
      return values[key] === "true";
    }
    const hint = integration.credentials_hints.find((h) => h.key === key);
    if (hint && hint.display_hint) {
      const p = hint.display_hint.toLowerCase();
      if (p.includes("attivo") || p.includes("true")) return true;
      if (p.includes("disattivo") || p.includes("false")) return false;
    }
    if (defaultValue !== undefined) {
      return defaultValue === true || defaultValue === "true";
    }
    return false;
  }

  function isFieldMissing(f: CredentialField): boolean {
    if (!f.required) return false;
    if (isBooleanField(f)) return false;
    if (savedKeys.has(f.key) && !deletedKeys.has(f.key)) return false;
    const val = values[f.key]?.trim();
    return !val;
  }

  async function save() {
    setAttemptedSave(true);
    const missing = formFields.filter(isFieldMissing);
    if (missing.length) {
      setError(
        `${t("integrationsPage.field_error")}: ${missing.map((f) => formatFieldLabel(f.key, f.label)).join(", ")}`,
      );
      return;
    }

    const toSave: Record<string, string> = {};
    const hints: Record<string, string> = {};

    for (const [key, val] of Object.entries(values)) {
      if (deletedKeys.has(key)) continue;
      if (val === undefined || val === null || val === "") continue;

      // Se il campo secret è rimasto la maschera censurata, NON inviarlo per non sovrascrivere
      // la vera credenziale cifrata sul server
      if (val === MASKED_SECRET_VALUE) continue;

      toSave[key] = val;
      const field = formFields.find((f) => f.key === key);
      const isBool = field && isBooleanField(field);
      const isSec = field && isSecretField(field);

      if (isBool) {
        hints[key] = val === "true" ? "Attivo" : "Disattivo";
      } else if (isSec) {
        hints[key] = "****";
      } else {
        hints[key] = val.slice(0, 128);
      }
    }

    if (Object.keys(toSave).length === 0) {
      onClose();
      return;
    }

    setSaving(true);
    setError(null);
    try {
      const res = await fetch(`${apiBase()}/v1/integrations/credentials`, {
        method: "POST",
        headers: jsonHeaders(userId, token),
        body: JSON.stringify({
          server_slug: integration.server_slug,
          credentials: toSave,
          display_hints: hints,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error((err as { detail?: string }).detail || t("integrationsPage.save_error"));
      }
      onClose();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : t("integrationsPage.save_error"));
    } finally {
      setSaving(false);
    }
  }

  const oauthOnly = integration.has_oauth && formFields.length === 0;
  const showSaveButton = !oauthOnly && formFields.length > 0;

  function renderField(field: CredentialField, allowDelete = false) {
    const custom = customFields.find((c) => normalizeKey(c.key) === field.key);
    const isCustom = Boolean(custom);
    const labelText = isCustom
      ? custom!.label.trim() || custom!.key
      : formatFieldLabel(field.key, field.label);
    const isBool = isBooleanField(field);
    const isSecret = isSecretField(field);
    const showPlain = showPasswords[field.key];
    const missing = attemptedSave && isFieldMissing(field);
    const isMaskedSecret = isSecret && values[field.key] === MASKED_SECRET_VALUE;
    const isLoadingSecret = loadingSecretKeys[field.key];
    const isDeleting = deletingKeys[field.key];

    // ==========================================
    // CAMPO PERSONALIZZATO CREATO DALL'UTENTE
    // ==========================================
    if (isCustom && custom) {
      return (
        <div
          key={custom.id}
          className="rounded-2xl border-2 border-primary/25 bg-card p-4 sm:p-5 shadow-xs space-y-3.5 transition hover:border-primary/40"
        >
          {/* Header del campo con Titolo, Badge e Cestino */}
          <div className="flex items-center justify-between gap-2 border-b border-border/60 pb-2.5">
            <div className="flex items-center gap-2 min-w-0">
              <span className="text-xs font-bold text-foreground truncate">
                {custom.label.trim() || custom.key || "Nuova Variabile"}
              </span>
              <span className="text-[10px] font-semibold bg-primary/10 text-primary px-2 py-0.5 rounded-full">
                Personalizzata
              </span>
            </div>
            <button
              type="button"
              onClick={() => removeCustomField(custom.id, custom.key)}
              className="p-1.5 rounded-lg text-muted-foreground/80 hover:text-destructive hover:bg-destructive/10 transition cursor-pointer"
              title="Rimuovi questa variabile dal modale"
              aria-label="Rimuovi variabile"
            >
              <Trash2 className="h-4 w-4" />
            </button>
          </div>

          {/* Riquadro di configurazione: Nome ENV, Etichetta, Tipo variabile, e Obbligatorietà */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="text-[11px] font-semibold text-muted-foreground mb-1 block">
                Nome Variabile ENV
              </label>
              <input
                className="w-full rounded-xl border border-input bg-background px-3 py-2 font-mono text-xs font-semibold text-foreground focus:border-primary focus:ring-2 focus:ring-primary/20 outline-none transition"
                value={custom.key}
                onChange={(e) => {
                  const nextKey = normalizeKey(e.target.value);
                  setCustomFields((prev) =>
                    prev.map((c) => (c.id === custom.id ? { ...c, key: nextKey } : c)),
                  );
                  setValues((v) => {
                    const old = v[field.key];
                    if (old === undefined) return v;
                    const { [field.key]: _removed, ...rest } = v;
                    return nextKey ? { ...rest, [nextKey]: old } : rest;
                  });
                }}
                placeholder="ES: API_KEY"
              />
            </div>

            <div>
              <label className="text-[11px] font-semibold text-muted-foreground mb-1 block">
                Etichetta Descrittiva
              </label>
              <input
                className="w-full rounded-xl border border-input bg-background px-3 py-2 text-xs text-foreground focus:border-primary focus:ring-2 focus:ring-primary/20 outline-none transition"
                value={custom.label}
                onChange={(e) => {
                  setCustomFields((prev) =>
                    prev.map((c) => (c.id === custom.id ? { ...c, label: e.target.value } : c)),
                  );
                }}
                placeholder="ES: Chiave Segreta"
              />
            </div>

            <div>
              <label className="text-[11px] font-semibold text-muted-foreground mb-1 block">
                Tipo Variabile
              </label>
              <div className="flex items-center rounded-xl border border-input bg-muted/40 p-0.5 text-xs">
                <button
                  type="button"
                  onClick={() => updateCustomFieldType(custom.id, "password")}
                  className={cn(
                    "flex-1 flex items-center justify-center gap-1.5 py-1.5 px-2 rounded-lg font-medium transition cursor-pointer",
                    custom.type === "password"
                      ? "bg-background text-foreground shadow-xs font-bold"
                      : "text-muted-foreground hover:text-foreground",
                  )}
                >
                  <Lock className="h-3 w-3" />
                  <span>Sicura</span>
                </button>
                <button
                  type="button"
                  onClick={() => updateCustomFieldType(custom.id, "text")}
                  className={cn(
                    "flex-1 flex items-center justify-center gap-1.5 py-1.5 px-2 rounded-lg font-medium transition cursor-pointer",
                    custom.type === "text"
                      ? "bg-background text-foreground shadow-xs font-bold"
                      : "text-muted-foreground hover:text-foreground",
                  )}
                >
                  <SlidersHorizontal className="h-3 w-3" />
                  <span>Testo</span>
                </button>
                <button
                  type="button"
                  onClick={() => updateCustomFieldType(custom.id, "boolean")}
                  className={cn(
                    "flex-1 flex items-center justify-center gap-1.5 py-1.5 px-2 rounded-lg font-medium transition cursor-pointer",
                    custom.type === "boolean"
                      ? "bg-background text-foreground shadow-xs font-bold"
                      : "text-muted-foreground hover:text-foreground",
                  )}
                >
                  <Check className="h-3 w-3" />
                  <span>Boolean</span>
                </button>
              </div>
            </div>

            <div>
              <label className="text-[11px] font-semibold text-muted-foreground mb-1 block">
                Obbligatorietà
              </label>
              <div className="flex items-center rounded-xl border border-input bg-muted/40 p-0.5 text-xs">
                <button
                  type="button"
                  onClick={() => updateCustomFieldRequired(custom.id, false)}
                  className={cn(
                    "flex-1 py-1.5 px-2 rounded-lg font-medium transition cursor-pointer text-center",
                    !custom.required
                      ? "bg-background text-foreground shadow-xs font-bold"
                      : "text-muted-foreground hover:text-foreground",
                  )}
                >
                  Opzionale
                </button>
                <button
                  type="button"
                  onClick={() => updateCustomFieldRequired(custom.id, true)}
                  className={cn(
                    "flex-1 py-1.5 px-2 rounded-lg font-medium transition cursor-pointer text-center",
                    custom.required
                      ? "bg-destructive/15 text-destructive shadow-xs font-bold"
                      : "text-muted-foreground hover:text-foreground",
                  )}
                >
                  Obbligatoria *
                </button>
              </div>
            </div>
          </div>

          {/* Campo di Inserimento Valore */}
          <div className="pt-1 border-t border-border/40">
            <label className="text-[11px] font-semibold text-muted-foreground mb-1 block">
              Valore
            </label>
            {custom.type === "boolean" ? (
              <div className="p-2.5 rounded-xl border border-input bg-background">
                <Switch
                  id={`field-${field.key}`}
                  checked={values[field.key] === "true"}
                  onChange={(checked) =>
                    setValues((v) => ({ ...v, [field.key]: checked ? "true" : "false" }))
                  }
                  label={
                    <span className="text-xs font-semibold text-foreground">
                      {values[field.key] === "true" ? "Attivo (true)" : "Disattivo (false)"}
                    </span>
                  }
                />
              </div>
            ) : custom.type === "password" ? (
              <div className="relative">
                <input
                  id={`field-${field.key}`}
                  type={showPasswords[field.key] ? "text" : "password"}
                  value={values[field.key] ?? ""}
                  onChange={(e) => setValues((v) => ({ ...v, [field.key]: e.target.value }))}
                  placeholder="Inserisci password o token segreto…"
                  className={cn(
                    "w-full rounded-xl border bg-background px-3.5 py-2.5 pr-12 font-mono text-xs sm:text-sm text-foreground placeholder:text-muted-foreground focus:border-primary focus:ring-2 focus:ring-primary/20 outline-none transition",
                    missing ? "border-destructive ring-2 ring-destructive/20" : "border-input",
                  )}
                />
                <button
                  type="button"
                  onClick={() => void toggleShowPassword(field.key)}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 p-1.5 rounded-lg text-muted-foreground hover:bg-muted hover:text-foreground transition cursor-pointer"
                  tabIndex={-1}
                  aria-label={showPasswords[field.key] ? "Nascondi" : "Mostra"}
                >
                  {showPasswords[field.key] ? (
                    <EyeOff className="h-4 w-4" />
                  ) : (
                    <Eye className="h-4 w-4" />
                  )}
                </button>
              </div>
            ) : (
              <input
                id={`field-${field.key}`}
                type="text"
                value={values[field.key] ?? ""}
                onChange={(e) => setValues((v) => ({ ...v, [field.key]: e.target.value }))}
                placeholder="Inserisci valore…"
                className={cn(
                  "w-full rounded-xl border bg-background px-3.5 py-2.5 text-xs sm:text-sm text-foreground placeholder:text-muted-foreground focus:border-primary focus:ring-2 focus:ring-primary/20 outline-none transition",
                  missing ? "border-destructive ring-2 ring-destructive/20" : "border-input",
                )}
              />
            )}
          </div>
        </div>
      );
    }

    // ==========================================
    // CAMPO BOOLEANO STANDARD
    // ==========================================
    if (isBool) {
      const checked = getBooleanValue(field.key, field.default_value);
      return (
        <div
          key={field.key}
          className="rounded-2xl border border-border/70 bg-card p-4 transition hover:border-border shadow-xs flex items-center justify-between gap-3"
        >
          <div className="flex-1">
            <Switch
              id={`field-${field.key}`}
              checked={checked}
              onChange={(nextChecked) =>
                setValues((v) => ({ ...v, [field.key]: nextChecked ? "true" : "false" }))
              }
              label={
                <span className="text-sm font-semibold text-foreground flex items-center gap-1.5">
                  <span>{labelText}</span>
                  {field.required ? (
                    <span className="text-destructive font-bold text-xs" title="Obbligatorio">
                      *
                    </span>
                  ) : (
                    <span className="text-[11px] font-normal text-muted-foreground">
                      (opzionale)
                    </span>
                  )}
                </span>
              }
              description={field.description || undefined}
            />
          </div>
          {allowDelete && (
            <button
              type="button"
              onClick={() => void handleDeleteField(field)}
              disabled={isDeleting}
              className="p-1.5 rounded-lg text-muted-foreground/70 hover:text-destructive hover:bg-destructive/10 transition cursor-pointer shrink-0"
              title="Rimuovi questa variabile"
              aria-label="Rimuovi variabile"
            >
              {isDeleting ? (
                <Loader2 className="h-4 w-4 animate-spin text-destructive" />
              ) : (
                <Trash2 className="h-4 w-4" />
              )}
            </button>
          )}
        </div>
      );
    }

    // ==========================================
    // CAMPO STANDARD (PASSWORD O TESTO)
    // ==========================================
    return (
      <div
        key={field.key}
        className="rounded-2xl border border-border/70 bg-card p-4 sm:p-4.5 transition hover:border-border shadow-xs space-y-2.5"
      >
        {/* Intestazione del Campo: Label, Obbligatorio, Nome Chiave ENV, Cestino */}
        <div className="flex flex-wrap items-center justify-between gap-2">
          <label
            htmlFor={`field-${field.key}`}
            className="text-sm font-semibold text-foreground flex items-center gap-1.5"
          >
            <span>{labelText}</span>
            {field.required ? (
              <span className="text-destructive font-bold text-xs" title="Obbligatorio">
                *
              </span>
            ) : (
              <span className="text-[11px] font-normal text-muted-foreground">
                (opzionale)
              </span>
            )}
          </label>

          <div className="flex items-center gap-2">
            {field.key && (
              <span className="text-[11px] font-mono text-muted-foreground bg-muted/60 px-2 py-0.5 rounded border border-border/40">
                {field.key}
              </span>
            )}
            {allowDelete && (
              <button
                type="button"
                onClick={() => void handleDeleteField(field)}
                disabled={isDeleting}
                className="p-1 rounded-lg text-muted-foreground/70 hover:text-destructive hover:bg-destructive/10 transition cursor-pointer"
                title="Rimuovi questa variabile"
                aria-label="Rimuovi variabile"
              >
                {isDeleting ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin text-destructive" />
                ) : (
                  <Trash2 className="h-3.5 w-3.5" />
                )}
              </button>
            )}
          </div>
        </div>

        {/* Descrizione opzionale */}
        {field.description ? (
          <p className="text-xs text-muted-foreground leading-relaxed">
            {field.description}
          </p>
        ) : null}

        {/* Input Controls */}
        <div className="relative pt-0.5">
          {isSecret ? (
            <div className="relative">
              <input
                id={`field-${field.key}`}
                type={showPlain ? "text" : "password"}
                value={values[field.key] ?? ""}
                onFocus={(e) => {
                  if (isMaskedSecret) {
                    e.target.select();
                  }
                }}
                onChange={(e) => {
                  setValues((v) => ({ ...v, [field.key]: e.target.value }));
                }}
                placeholder={`Inserisci ${labelText.toLowerCase()}…`}
                className={cn(
                  "w-full rounded-xl border bg-background px-3.5 py-2.5 pr-12 text-xs sm:text-sm text-foreground font-mono placeholder:text-muted-foreground focus:border-primary focus:ring-2 focus:ring-primary/20 outline-none transition",
                  missing ? "border-destructive ring-2 ring-destructive/20" : "border-input",
                  isMaskedSecret && !showPlain && "text-muted-foreground tracking-widest",
                )}
              />
              <button
                type="button"
                onClick={() => void toggleShowPassword(field.key)}
                disabled={isLoadingSecret}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 p-1.5 rounded-lg text-muted-foreground hover:bg-muted hover:text-foreground transition cursor-pointer disabled:opacity-50"
                tabIndex={-1}
                aria-label={showPlain ? "Nascondi" : "Mostra"}
                title={showPlain ? "Nascondi valore" : "Mostra valore in chiaro"}
              >
                {isLoadingSecret ? (
                  <Loader2 className="h-4 w-4 animate-spin text-primary" />
                ) : showPlain ? (
                  <EyeOff className="h-4 w-4" />
                ) : (
                  <Eye className="h-4 w-4" />
                )}
              </button>
            </div>
          ) : (
            <input
              id={`field-${field.key}`}
              type="text"
              value={values[field.key] ?? ""}
              onChange={(e) => setValues((v) => ({ ...v, [field.key]: e.target.value }))}
              placeholder={`Inserisci ${labelText.toLowerCase()}…`}
              className={cn(
                "w-full rounded-xl border bg-background px-3.5 py-2.5 text-xs sm:text-sm text-foreground placeholder:text-muted-foreground focus:border-primary focus:ring-2 focus:ring-primary/20 outline-none transition",
                missing ? "border-destructive ring-2 ring-destructive/20" : "border-input",
              )}
            />
          )}

          {isMaskedSecret && !showPlain ? (
            <p className="mt-1 text-[11px] text-muted-foreground">
              {t("integrationsPage.modify_field_hint") ||
                "Lascia invariato per conservare il valore salvato, oppure digita per sostituirlo."}
            </p>
          ) : null}
        </div>
      </div>
    );
  }

  // Raggruppa i campi in categorie logiche per chiarezza e massima leggibilità
  function renderFieldGroup(
    fields: CredentialField[],
    groupTitle?: string,
    groupIcon?: React.ReactNode,
    allowDelete = false,
  ) {
    if (fields.length === 0) return null;
    return (
      <div className="space-y-3">
        {groupTitle ? (
          <div className="flex items-center gap-2 pt-1 pb-0.5">
            {groupIcon}
            <h4 className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
              {groupTitle}
            </h4>
            <span className="text-[10px] font-semibold text-muted-foreground/70 rounded-full bg-muted px-1.5 py-0.2">
              {fields.length}
            </span>
          </div>
        ) : null}
        <div className="space-y-3">
          {fields.map((f) => renderField(f, allowDelete))}
        </div>
      </div>
    );
  }

  // Suddivisione logica dei campi base in categorie comprensibili
  const { basicAuthFields, basicConnFields, basicOtherFields } = useMemo(() => {
    const auth: CredentialField[] = [];
    const conn: CredentialField[] = [];
    const other: CredentialField[] = [];

    for (const f of basicFields) {
      const k = f.key.toUpperCase();
      if (/(PASSWORD|SECRET|TOKEN|KEY|PAT|AUTH|CREDENTIAL|USER|EMAIL|ACCOUNT|LOGIN|CLIENT_ID)/i.test(k)) {
        auth.push(f);
      } else if (/(HOST|PORT|URL|URI|ENDPOINT|SERVER|SSL|TLS|DOMAIN|HTTP)/i.test(k)) {
        conn.push(f);
      } else {
        other.push(f);
      }
    }

    return { basicAuthFields: auth, basicConnFields: conn, basicOtherFields: other };
  }, [basicFields]);

  // Suddivisione logica dei campi avanzati in categorie comprensibili
  const { advAuthFields, advConnFields, advOtherFields } = useMemo(() => {
    const auth: CredentialField[] = [];
    const conn: CredentialField[] = [];
    const other: CredentialField[] = [];

    for (const f of advancedFields) {
      const isCustom = customFields.some((c) => normalizeKey(c.key) === f.key);
      if (isCustom) {
        other.push(f);
        continue;
      }
      const k = f.key.toUpperCase();
      if (/(PASSWORD|SECRET|TOKEN|KEY|PAT|AUTH|CREDENTIAL|USER|EMAIL|ACCOUNT|LOGIN|CLIENT_ID)/i.test(k)) {
        auth.push(f);
      } else if (/(HOST|PORT|URL|URI|ENDPOINT|SERVER|SSL|TLS|DOMAIN|HTTP)/i.test(k)) {
        conn.push(f);
      } else {
        other.push(f);
      }
    }

    return { advAuthFields: auth, advConnFields: conn, advOtherFields: other };
  }, [advancedFields, customFields]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 sm:p-6 backdrop-blur-sm animate-in fade-in duration-200">
      <div className="max-h-[90vh] w-full max-w-2xl flex flex-col rounded-3xl border border-border bg-card text-card-foreground shadow-2xl overflow-hidden animate-in zoom-in-95 duration-200">
        {/* Header Modale */}
        <div className="flex items-center justify-between border-b border-border p-5 sm:p-6 bg-muted/20 shrink-0">
          <div className="flex items-center gap-3.5 min-w-0 pr-4">
            {integration.icon_url ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={integration.icon_url}
                alt=""
                className="h-11 w-11 shrink-0 rounded-2xl border border-border object-cover shadow-sm"
              />
            ) : (
              <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl border border-primary/25 bg-primary/10 text-primary shadow-sm">
                <Plug className="h-5 w-5" aria-hidden />
              </div>
            )}
            <div className="min-w-0 flex-1">
              <h2 className="text-lg sm:text-xl font-bold tracking-tight text-foreground truncate">
                {integration.display_name}
              </h2>
              {integration.description ? (
                <p className="mt-0.5 text-xs text-muted-foreground line-clamp-2">
                  {integration.description}
                </p>
              ) : null}
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-xl p-2 text-muted-foreground hover:bg-muted hover:text-foreground transition cursor-pointer shrink-0"
            aria-label={t("integrationsPage.cancel")}
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Corpo scrollabile del Form */}
        <div className="flex-1 overflow-y-auto p-5 sm:p-6 space-y-4 bg-background">
          {/* Sezione OAuth se applicabile */}
          {integration.has_oauth ? (
            <div className="rounded-2xl border border-primary/30 bg-primary/5 p-4 text-center space-y-2.5">
              <h3 className="text-sm font-bold text-foreground">
                {t("integrationsPage.oauth_title_service", { service: providerLabel })}
              </h3>
              {hasOAuthToken ? (
                <>
                  <p className="text-xs font-semibold text-emerald-600 dark:text-emerald-400">
                    {t("integrationsPage.oauth_connected_service", { service: providerLabel })}
                  </p>
                  <button
                    type="button"
                    onClick={handleOAuthLogin}
                    className="inline-flex items-center justify-center gap-2 rounded-xl border border-border bg-background px-4 py-2 text-xs font-semibold text-foreground transition hover:bg-muted cursor-pointer"
                  >
                    <Plug className="h-3.5 w-3.5" aria-hidden />
                    {t("integrationsPage.oauth_reconnect")}
                  </button>
                </>
              ) : (
                <>
                  <p className="text-xs text-muted-foreground max-w-md mx-auto">
                    {t("integrationsPage.oauth_intro_service", { service: providerLabel })}
                  </p>
                  <button
                    type="button"
                    onClick={handleOAuthLogin}
                    className="inline-flex items-center justify-center gap-2 rounded-xl bg-primary px-4 py-2 text-xs font-bold text-primary-foreground shadow transition hover:bg-primary/90 cursor-pointer"
                  >
                    <Plug className="h-3.5 w-3.5" aria-hidden />
                    {getOAuthButtonText()}
                  </button>
                </>
              )}
            </div>
          ) : null}

          {/* Variabili Primarie Raggruppate per Categoria */}
          {basicFields.length > 0 ? (
            <div className="space-y-5">
              {renderFieldGroup(
                basicAuthFields,
                "Credenziali di Accesso",
                <KeyRound className="h-4 w-4 text-primary" />,
              )}
              {renderFieldGroup(
                basicConnFields,
                "Connessione & Server",
                <Server className="h-4 w-4 text-sky-500" />,
              )}
              {renderFieldGroup(
                basicOtherFields,
                "Parametri & Opzioni",
                <SlidersHorizontal className="h-4 w-4 text-muted-foreground" />,
              )}
            </div>
          ) : null}

          {/* Parametri Avanzati (Accordion con raggruppamenti interni) */}
          {advancedFields.length > 0 ? (
            <div className="overflow-hidden rounded-2xl border border-border bg-card shadow-xs">
              <button
                type="button"
                onClick={() => setIsAdvancedOpen((prev) => !prev)}
                className="flex w-full items-center justify-between p-4 text-left text-xs sm:text-sm font-bold transition hover:bg-muted/30 focus:outline-none cursor-pointer"
              >
                <div className="flex items-center gap-2 text-foreground">
                  <SlidersHorizontal className="h-4 w-4 text-primary" />
                  <span>
                    {t("integrationsPage.advanced_settings") || "Parametri Avanzati"}
                  </span>
                  <span className="rounded-full bg-muted px-2 py-0.2 text-[10px] font-bold text-muted-foreground">
                    {advancedFields.length}
                  </span>
                </div>
                <ChevronDown
                  className={cn(
                    "h-4 w-4 text-muted-foreground transition-transform duration-200",
                    isAdvancedOpen && "rotate-180",
                  )}
                />
              </button>

              {isAdvancedOpen ? (
                <div className="border-t border-border p-4.5 space-y-5 bg-background/50">
                  {renderFieldGroup(
                    advAuthFields,
                    "Autenticazione & Account",
                    <Lock className="h-3.5 w-3.5 text-primary" />,
                  )}
                  {renderFieldGroup(
                    advConnFields,
                    "Server & Parametri di Rete",
                    <Globe className="h-3.5 w-3.5 text-sky-500" />,
                  )}
                  {renderFieldGroup(
                    advOtherFields,
                    "Opzioni & Preferenze",
                    <Shield className="h-3.5 w-3.5 text-muted-foreground" />,
                    true, // Cestino abilitato sotto Opzioni & Preferenze
                  )}
                </div>
              ) : null}
            </div>
          ) : null}

          {/* Aggiunta campo extra personalizzato */}
          {!integration.has_oauth ? (
            <button
              type="button"
              onClick={addCustomField}
              className="flex w-full items-center justify-center gap-2 rounded-2xl border-2 border-dashed border-border/80 p-3.5 text-xs font-bold text-muted-foreground hover:text-foreground hover:border-primary/50 hover:bg-muted/20 transition cursor-pointer"
            >
              <Plus className="h-4 w-4" aria-hidden />
              {t("integrationsPage.add_credential")}
            </button>
          ) : null}

          {/* Messaggio di Errore */}
          {error ? (
            <div className="rounded-2xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-xs font-semibold text-red-500">
              {error}
            </div>
          ) : null}
        </div>

        {/* Footer con Azioni */}
        <div className="border-t border-border p-4 sm:p-5 bg-muted/20 flex items-center justify-end gap-3 shrink-0">
          <button
            type="button"
            onClick={onClose}
            className="rounded-xl border border-border px-4 py-2 text-xs font-semibold text-foreground hover:bg-muted transition cursor-pointer"
          >
            {oauthOnly && hasOAuthToken ? t("integrationsPage.close") : t("integrationsPage.cancel")}
          </button>
          {showSaveButton ? (
            <button
              type="button"
              onClick={() => void save()}
              disabled={saving}
              className="rounded-xl bg-primary px-5 py-2 text-xs font-semibold text-primary-foreground shadow-sm hover:bg-primary/90 transition cursor-pointer disabled:opacity-50"
            >
              {saving ? t("integrationsPage.saving") : t("integrationsPage.save")}
            </button>
          ) : null}
        </div>
      </div>
    </div>
  );
}
