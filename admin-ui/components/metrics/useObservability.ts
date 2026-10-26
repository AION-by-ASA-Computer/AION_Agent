"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { apiFetch } from "@/lib/api/headers";
import { apiBase } from "@/lib/api";

export type ProbeTarget = "prometheus" | "otel" | "opik";
export type Probe = { success: boolean; message: string; latency_ms?: number };
export type Notice = { type: "success" | "error"; text: string };

const DEFAULTS: Record<string, string> = {
  AION_PROMETHEUS_URL: "http://localhost:9090",
  AION_METRICS_ENABLED: "1",
  AION_METRICS_PATH: "/metrics",
  AION_OTEL_ENABLED: "0",
  AION_OTEL_ENDPOINT: "http://localhost:4317",
  AION_OTEL_PROTOCOL: "grpc",
  AION_OTEL_SERVICE_NAME: "aion-agent",
  AION_OTEL_TRACE_CONTENT: "1",
  AION_OTEL_METRIC_EXPORT_INTERVAL: "5000",
  AION_OPIK_ENABLED: "0",
  OPIK_URL_OVERRIDE: "http://localhost:5173/api",
  OPIK_PROJECT_NAME: "AION-Agent",
  OPIK_API_KEY: "",
};

/** Prometheus / OpenTelemetry / Opik settings: load, probe, save, and wait out the API restart. */
export function useObservability(onApplied: () => void, msg: { restarted: string; timeout: string; loadFailed: string; saved: string; probeOk: string; probeFail: string; network: string }) {
  const [open, setOpen] = useState(false);
  const [settings, setSettings] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [probing, setProbing] = useState<Partial<Record<ProbeTarget, boolean>>>({});
  const [probes, setProbes] = useState<Partial<Record<ProbeTarget, Probe | null>>>({});
  const [restarting, setRestarting] = useState(false);
  const timers = useRef<{ wait?: ReturnType<typeof setTimeout>; poll?: ReturnType<typeof setInterval> }>({});

  useEffect(() => () => {
    clearTimeout(timers.current.wait);
    clearInterval(timers.current.poll);
  }, []);

  const set = useCallback((key: string, value: string) => setSettings((s) => ({ ...s, [key]: value })), []);

  const show = async () => {
    setNotice(null);
    setProbes({});
    setOpen(true);
    setLoading(true);
    try {
      const res = await apiFetch(`${apiBase()}/admin/settings`);
      if (!res.ok) throw new Error(String(res.status));
      const cur = (await res.json()).settings || {};
      setSettings(Object.fromEntries(Object.entries(DEFAULTS).map(([k, d]) => [k, cur[k] !== undefined && cur[k] !== null && cur[k] !== "" ? String(cur[k]) : d])));
    } catch {
      setNotice({ type: "error", text: msg.loadFailed });
    } finally {
      setLoading(false);
    }
  };

  const probe = async (target: ProbeTarget) => {
    setProbing((p) => ({ ...p, [target]: true }));
    setProbes((p) => ({ ...p, [target]: null }));
    try {
      const body: Record<string, string> = { target };
      if (target === "prometheus") body.url = settings.AION_PROMETHEUS_URL || DEFAULTS.AION_PROMETHEUS_URL;
      if (target === "otel") {
        body.endpoint = settings.AION_OTEL_ENDPOINT || DEFAULTS.AION_OTEL_ENDPOINT;
        body.protocol = settings.AION_OTEL_PROTOCOL || "grpc";
      }
      if (target === "opik") {
        body.url = settings.OPIK_URL_OVERRIDE || DEFAULTS.OPIK_URL_OVERRIDE;
        body.api_key = settings.OPIK_API_KEY;
      }
      const res = await apiFetch(`${apiBase()}/admin/metrics/test-connection`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const d = await res.json();
      setProbes((p) => ({ ...p, [target]: { success: !!d.success, message: d.message || (d.success ? msg.probeOk : msg.probeFail), latency_ms: d.latency_ms } }));
    } catch {
      setProbes((p) => ({ ...p, [target]: { success: false, message: msg.network } }));
    } finally {
      setProbing((p) => ({ ...p, [target]: false }));
    }
  };

  const save = async () => {
    setSaving(true);
    setNotice(null);
    try {
      const res = await apiFetch(`${apiBase()}/admin/settings`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ settings }) });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || String(res.status));
      }
      const d = await res.json();
      if (d.restarting) {
        setRestarting(true);
        setOpen(false);
      } else {
        setNotice({ type: "success", text: d.message || msg.saved });
        onApplied();
      }
    } catch (e) {
      setNotice({ type: "error", text: e instanceof Error && e.message ? e.message : msg.loadFailed });
    } finally {
      setSaving(false);
    }
  };

  return { open, close: () => setOpen(false), show, settings, set, loading, saving, notice, setNotice, probing, probes, probe, save, restarting, setRestarting, onApplied };
}
