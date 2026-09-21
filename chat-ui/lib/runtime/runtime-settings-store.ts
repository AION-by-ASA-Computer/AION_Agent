import { apiBase } from "@/lib/config";
import { jsonHeaders } from "@/lib/api/aion";

export type RuntimeFieldType = "int" | "float" | "bool" | "enum";

export type RuntimeFieldSchema = {
  key: string;
  group: "loop" | "generation" | "thinking" | "advanced" | string;
  type: RuntimeFieldType;
  env_key: string;
  nullable?: boolean;
  min?: number;
  max?: number;
  step?: number;
  enum?: string[];
  default?: unknown;
};

export type RuntimeValues = Record<string, unknown>;

export type RuntimePreset = {
  id: string;
  name: string;
  values: RuntimeValues;
  created_at?: string;
  updated_at?: string;
};

export type RuntimeSettingsResponse = {
  schema: RuntimeFieldSchema[];
  defaults: RuntimeValues;
  user: {
    values: RuntimeValues;
    stored_values?: RuntimeValues;
    presets: RuntimePreset[];
    active_preset_id: string | null;
  };
  limits?: {
    hard_max_agent_steps?: number;
    profile_max_agent_steps?: number | null;
  };
};

const STORAGE_KEY = "aion_runtime_settings";

/** On/off and min/med/max effort — controlled only from the chat composer "+" menu. */
export const COMPOSER_THINKING_KEYS = ["thinking_enabled", "reasoning_effort"] as const;

export type ComposerReasoningEffort = "min" | "medium" | "max";

export function isComposerThinkingKey(key: string): boolean {
  return (COMPOSER_THINKING_KEYS as readonly string[]).includes(key);
}

export function stripComposerThinkingKeys(values: RuntimeValues): RuntimeValues {
  const out = { ...values };
  for (const key of COMPOSER_THINKING_KEYS) delete out[key];
  return out;
}

function preserveComposerThinkingKeys(values: RuntimeValues): RuntimeValues {
  const out = { ...values };
  for (const key of COMPOSER_THINKING_KEYS) {
    if (key in state.values) out[key] = state.values[key];
  }
  return out;
}

type StoreState = {
  loaded: boolean;
  saving: boolean;
  schema: RuntimeFieldSchema[];
  defaults: RuntimeValues;
  values: RuntimeValues;
  storedValues: RuntimeValues;
  presets: RuntimePreset[];
  activePresetId: string | null;
  profileMaxAgentSteps: number | null;
};

const listeners = new Set<() => void>();
let persistTimer: ReturnType<typeof setTimeout> | null = null;
let persistAuth: { userId: string; token?: string | null } | null = null;

let state: StoreState = {
  loaded: false,
  saving: false,
  schema: [],
  defaults: {},
  values: {},
  storedValues: {},
  presets: [],
  activePresetId: null,
  profileMaxAgentSteps: null,
};

function notify() {
  listeners.forEach((fn) => fn());
}

function setState(patch: Partial<StoreState>) {
  state = { ...state, ...patch };
  notify();
}

export function subscribeRuntimeSettings(fn: () => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function getRuntimeSettingsSnapshot(): StoreState {
  return state;
}

function allowlistedValues(values: RuntimeValues): RuntimeValues {
  if (!state.schema.length) return { ...values };
  const out: RuntimeValues = {};
  for (const field of state.schema) {
    if (field.key in values) out[field.key] = values[field.key];
  }
  return out;
}

export function getRuntimeValues(): RuntimeValues {
  return allowlistedValues(state.values);
}

/** Runtime payload for a chat turn: sidebar tuning + composer thinking (single source of truth). */
export function getRuntimeValuesForTurn(
  thinkingEnabled: boolean,
  reasoningEffort: ComposerReasoningEffort,
): RuntimeValues {
  return {
    ...getRuntimeValues(),
    thinking_enabled: thinkingEnabled,
    reasoning_effort: reasoningEffort,
  };
}

export function sidebarRuntimeSchema(): RuntimeFieldSchema[] {
  return state.schema.filter((field) => !isComposerThinkingKey(field.key));
}

function cacheLocal(values: RuntimeValues) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(values));
  } catch {
    /* ignore */
  }
}

function readLocal(): RuntimeValues {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

function applyServer(data: RuntimeSettingsResponse) {
  const defaults = data.defaults || {};
  const userValues = data.user?.values || {};
  const local = readLocal();
  const values = { ...defaults, ...local, ...userValues };
  setState({
    loaded: true,
    schema: data.schema || [],
    defaults,
    values,
    storedValues: data.user?.stored_values || {},
    presets: data.user?.presets || [],
    activePresetId: data.user?.active_preset_id ?? null,
    profileMaxAgentSteps: data.limits?.profile_max_agent_steps ?? null,
  });
  cacheLocal(values);
}

export async function loadRuntimeSettings(userId: string, token?: string | null): Promise<void> {
  persistAuth = { userId, token };
  try {
    const profile =
      typeof localStorage !== "undefined"
        ? localStorage.getItem("aion_chat_selected_profile_user_md") || ""
        : "";
    const qs = profile ? `?profile=${encodeURIComponent(profile)}` : "";
    const r = await fetch(`${apiBase()}/v1/runtime-settings${qs}`, {
      headers: jsonHeaders(userId, token),
    });
    if (!r.ok) {
      const local = readLocal();
      setState({ loaded: true, values: { ...state.defaults, ...local } });
      return;
    }
    const data = (await r.json()) as RuntimeSettingsResponse;
    applyServer(data);
  } catch {
    const local = readLocal();
    setState({ loaded: true, values: { ...state.defaults, ...local } });
  }
}

async function persistNow() {
  if (!persistAuth) return;
  setState({ saving: true });
  try {
    const r = await fetch(`${apiBase()}/v1/runtime-settings`, {
      method: "PUT",
      headers: jsonHeaders(persistAuth.userId, persistAuth.token),
      body: JSON.stringify({
        values: allowlistedValues(state.values),
        active_preset_id: state.activePresetId,
      }),
    });
    if (r.ok) {
      const data = (await r.json()) as { user?: RuntimeSettingsResponse["user"] };
      if (data.user) {
        setState({
          saving: false,
          values: data.user.values || state.values,
          storedValues: data.user.stored_values || {},
          presets: data.user.presets || state.presets,
          activePresetId: data.user.active_preset_id ?? state.activePresetId,
        });
        cacheLocal(data.user.values || state.values);
        return;
      }
    }
  } catch {
    /* keep local */
  }
  setState({ saving: false });
  cacheLocal(state.values);
}

function schedulePersist() {
  cacheLocal(state.values);
  if (persistTimer) clearTimeout(persistTimer);
  persistTimer = setTimeout(() => {
    persistTimer = null;
    void persistNow();
  }, 400);
}

export function patchRuntimeValues(patch: RuntimeValues) {
  const values = { ...state.values, ...patch };
  setState({ values });
  schedulePersist();
}

export function resetRuntimeToDefaults() {
  const preserved: RuntimeValues = {};
  for (const key of COMPOSER_THINKING_KEYS) {
    if (key in state.values) preserved[key] = state.values[key];
  }
  setState({ values: { ...state.defaults, ...preserved }, activePresetId: null });
  schedulePersist();
}

export function resetRuntimeField(key: string) {
  patchRuntimeValues({ [key]: state.defaults[key] });
}

function applyUser(user: RuntimeSettingsResponse["user"]) {
  const values = preserveComposerThinkingKeys(user.values || state.values);
  setState({
    values,
    storedValues: user.stored_values || {},
    presets: user.presets || [],
    activePresetId: user.active_preset_id ?? null,
  });
  cacheLocal(values);
}

export async function createRuntimePreset(name: string): Promise<boolean> {
  if (!persistAuth) return false;
  const r = await fetch(`${apiBase()}/v1/runtime-settings/presets`, {
    method: "POST",
    headers: jsonHeaders(persistAuth.userId, persistAuth.token),
    body: JSON.stringify({
      name,
      values: stripComposerThinkingKeys(allowlistedValues(state.values)),
    }),
  });
  if (!r.ok) return false;
  const data = (await r.json()) as { user?: RuntimeSettingsResponse["user"] };
  if (data.user) applyUser(data.user);
  return true;
}

export async function saveActiveRuntimePreset(): Promise<boolean> {
  if (!persistAuth || !state.activePresetId) return false;
  const r = await fetch(
    `${apiBase()}/v1/runtime-settings/presets/${encodeURIComponent(state.activePresetId)}`,
    {
      method: "PATCH",
      headers: jsonHeaders(persistAuth.userId, persistAuth.token),
      body: JSON.stringify({
        values: stripComposerThinkingKeys(allowlistedValues(state.values)),
      }),
    },
  );
  if (!r.ok) return false;
  const data = (await r.json()) as { user?: RuntimeSettingsResponse["user"] };
  if (data.user) applyUser(data.user);
  return true;
}

export async function renameRuntimePreset(id: string, name: string): Promise<boolean> {
  if (!persistAuth) return false;
  const r = await fetch(`${apiBase()}/v1/runtime-settings/presets/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: jsonHeaders(persistAuth.userId, persistAuth.token),
    body: JSON.stringify({ name }),
  });
  if (!r.ok) return false;
  const data = (await r.json()) as { user?: RuntimeSettingsResponse["user"] };
  if (data.user) applyUser(data.user);
  return true;
}

export async function deleteRuntimePreset(id: string): Promise<boolean> {
  if (!persistAuth) return false;
  const r = await fetch(`${apiBase()}/v1/runtime-settings/presets/${encodeURIComponent(id)}`, {
    method: "DELETE",
    headers: jsonHeaders(persistAuth.userId, persistAuth.token),
  });
  if (!r.ok) return false;
  const data = (await r.json()) as { user?: RuntimeSettingsResponse["user"] };
  if (data.user) applyUser(data.user);
  return true;
}

export async function activateRuntimePreset(id: string): Promise<boolean> {
  if (!persistAuth) return false;
  const r = await fetch(
    `${apiBase()}/v1/runtime-settings/presets/${encodeURIComponent(id)}/activate`,
    {
      method: "POST",
      headers: jsonHeaders(persistAuth.userId, persistAuth.token),
    },
  );
  if (!r.ok) return false;
  const data = (await r.json()) as { user?: RuntimeSettingsResponse["user"] };
  if (data.user) applyUser(data.user);
  return true;
}

export function valuesEqual(a: RuntimeValues, b: RuntimeValues, keys: string[]): boolean {
  return keys.every((k) => JSON.stringify(a[k] ?? null) === JSON.stringify(b[k] ?? null));
}
