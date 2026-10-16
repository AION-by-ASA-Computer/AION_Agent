"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { apiBase } from "@/lib/api";
import { apiFetch } from "@/lib/api/headers";
import { getStoredToken } from "@/lib/auth/storage";
import { SCENARIOS, freshStatus } from "./scenarioList";
import type { LogEvent, ProfileOption, ReportFile, T, TestStatus } from "./types";

const DEFAULT_PROFILE = "generic_assistant";
const SCENARIO_IDS = new Set(SCENARIOS.map((s) => s.id));

type Payload = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any -- SSE frames are untyped JSON

/** Folds one SSE frame into the stream log: reasoning/token chunks merge, a tool_result completes its tool_call. */
function foldLog(prev: LogEvent[], data: Payload, entry: LogEvent): LogEvent[] {
  const last = prev.length - 1;
  const mergeInto = (text: string) => {
    const next = [...prev];
    next[last] = { ...prev[last], content: (prev[last].content || "") + text, timestamp: data.timestamp || prev[last].timestamp };
    return next;
  };

  if (data.step === "reasoning" && data.content) {
    return last >= 0 && prev[last].step === "reasoning" && prev[last].test === data.test ? mergeInto(data.content) : [...prev, entry];
  }
  if (data.step === "token" && (data.token || data.content)) {
    const text = data.token || data.content || "";
    return last >= 0 && prev[last].step === "token" && prev[last].test === data.test ? mergeInto(text) : [...prev, { ...entry, content: text }];
  }
  if (data.step === "tool_result") {
    for (let i = last; i >= 0; i--) {
      if (prev[i].step === "tool_call" && prev[i].test === data.test && prev[i].tool === data.tool) {
        const next = [...prev];
        next[i] = { ...prev[i], status: data.error ? "error" : "success", error: data.error, preview: data.preview, result: data.result };
        return next;
      }
    }
  }
  return [...prev, entry];
}

function foldStatus(curr: TestStatus, data: Payload, fallbackProfile: string): TestStatus {
  const next: TestStatus = {
    ...curr,
    assistant: data.assistant || curr.assistant || fallbackProfile,
    duration_sec: data.duration_sec ?? curr.duration_sec,
    single_report_filename: data.single_report_filename || curr.single_report_filename,
  };
  if (data.step === "test_start") next.status = "running";
  if (data.step === "test_error") next.status = "failed";
  if (data.step === "tool_call") {
    next.tool_count = curr.tool_count + 1;
    if (data.tool === "render_chart" && data.params) next.charts = [...(curr.charts || []), data.params];
  }
  if (data.step === "test_complete") {
    next.status = data.status === "failed" ? "failed" : "completed";
    next.final_output = data.final_output;
    next.reasoning = data.reasoning;
    next.timeline = data.timeline || curr.timeline;
    next.generated_files = data.generated_files || curr.generated_files;
    for (const key of ["tool_count", "score", "max_score", "rating", "passed", "eval_summary", "eval_criteria"] as const) {
      if (data[key] !== undefined) (next as any)[key] = data[key]; // eslint-disable-line @typescript-eslint/no-explicit-any
    }
  }
  return next;
}

export function useDiagnostics(t: T) {
  const [running, setRunning] = useState(false);
  const [tests, setTests] = useState<Record<string, TestStatus>>(() => freshStatus());
  const [logs, setLogs] = useState<LogEvent[]>([]);
  const [report, setReport] = useState({ content: "", name: "" });

  const [profiles, setProfiles] = useState<ProfileOption[]>([]);
  const [profilesLoading, setProfilesLoading] = useState(true);
  const [profile, setProfile] = useState(DEFAULT_PROFILE);

  const [history, setHistory] = useState<ReportFile[]>([]);
  const [historyState, setHistoryState] = useState<"loading" | "ready" | "error">("loading");

  const source = useRef<EventSource | null>(null);
  const seq = useRef(0);
  const profileRef = useRef(profile);
  profileRef.current = profile;

  const loadHistory = useCallback(async () => {
    setHistoryState("loading");
    try {
      const res = await apiFetch(`${apiBase()}/admin/diagnostics/reports`);
      if (!res.ok) throw new Error(String(res.status));
      setHistory(await res.json());
      setHistoryState("ready");
    } catch {
      setHistoryState("error");
    }
  }, []);

  useEffect(() => {
    loadHistory();
    (async () => {
      try {
        const res = await apiFetch(`${apiBase()}/admin/profiles`);
        const data = res.ok ? await res.json() : [];
        if (Array.isArray(data) && data.length > 0) {
          const mapped: ProfileOption[] = data.map((p: Payload) => ({
            slug: p.slug || String(p.name).replace(/\s+/g, "_").toLowerCase(),
            name: p.name || p.slug,
            description: p.description || "",
          }));
          setProfiles(mapped);
          if (!mapped.some((p) => p.slug === DEFAULT_PROFILE)) setProfile(mapped[0].slug);
        }
      } catch {
        /* the selector falls back to the default profile */
      } finally {
        setProfilesLoading(false);
      }
    })();
    return () => source.current?.close();
  }, [loadHistory]);

  const finish = useCallback(() => {
    source.current?.close();
    source.current = null;
    setRunning(false);
  }, []);

  const stop = useCallback(async () => {
    finish();
    try {
      await apiFetch(`${apiBase()}/admin/diagnostics/cancel`, { method: "POST" });
    } catch {
      /* the stream is already closed locally */
    }
    setLogs((prev) => [
      ...prev,
      { id: `cancelled_${seq.current++}`, step: "test_error", message: t("admin_diagnostics.stream.cancelled"), timestamp: new Date().toISOString(), error: t("admin_diagnostics.stream.cancelled") },
    ]);
  }, [finish, t]);

  const run = useCallback(() => {
    if (source.current) return;
    setRunning(true);
    setLogs([]);
    setReport({ content: "", name: "" });
    setTests(freshStatus(profileRef.current));

    const params = new URLSearchParams({ access_token: getStoredToken() || "" });
    if (profileRef.current) params.set("profile", profileRef.current);
    const es = new EventSource(`${apiBase()}/admin/diagnostics/run-tests?${params}`);
    source.current = es;

    es.onmessage = (event) => {
      let data: Payload;
      try {
        data = JSON.parse(event.data);
      } catch {
        return;
      }
      const entry: LogEvent = { ...data, id: `evt_${seq.current++}`, message: data.message || "", timestamp: data.timestamp || new Date().toISOString() } as LogEvent;
      setLogs((prev) => foldLog(prev, data, entry));

      if (data.test && SCENARIO_IDS.has(data.test)) {
        setTests((prev) => ({ ...prev, [data.test]: foldStatus(prev[data.test], data, profileRef.current) }));
      }
      if (data.step === "suite_complete") {
        if (data.report_content) setReport({ content: data.report_content, name: data.report_filename || "report_smoke_test.md" });
        loadHistory();
        finish();
      }
    };
    es.onerror = finish;
  }, [finish, loadHistory]);

  /** Returns true when the report loaded, so the caller can switch to the reader. */
  const openReport = useCallback(async (filename: string) => {
    try {
      const res = await apiFetch(`${apiBase()}/admin/diagnostics/reports/${encodeURIComponent(filename)}`);
      if (!res.ok) return false;
      const data = await res.json();
      setReport({ content: data.content, name: filename });
      return true;
    } catch {
      return false;
    }
  }, []);

  return { running, tests, logs, report, profiles, profilesLoading, profile, setProfile, history, historyState, loadHistory, run, stop, openReport };
}
