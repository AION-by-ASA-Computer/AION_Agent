"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { FolderSearch, Loader2, ScanSearch, ShieldCheck, ShieldAlert } from "lucide-react";
import { apiBase } from "@/lib/api";
import { apiFetch } from "@/lib/api/headers";
import { getStoredToken } from "@/lib/auth/storage";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";
import { PageToast, type ToastState } from "@/components/PageToast";
import { Dialog } from "@/components/profiles/Dialog";
import { Select } from "@/components/ui/Select";
import { ghostBtn, inputCls, outlineBtn, solidBtn } from "@/components/ui/classes";
import { fullWhen, shortWhen, toMs } from "@/components/conversations/format";
import { FindingsList } from "@/components/security/FindingsList";
import { ReportPanel } from "@/components/security/ReportPanel";
import {
  baseName,
  extractInvestigation,
  stripJson,
  type Investigation,
  type SavedReport,
  type ScanResult,
  type ScanSummary,
} from "@/components/security/report";

const k = "admin_security";
type Tab = "findings" | "scans" | "reports";

export default function SecurityPage() {
  const t = useT();
  const [tab, setTab] = useState<Tab>("findings");
  const [targetPath, setTargetPath] = useState("");
  const [scan, setScan] = useState<ScanResult | null>(null);
  const [scanning, setScanning] = useState(false);
  const [toast, setToast] = useState<ToastState>(null);

  const [agent, setAgent] = useState("");
  const [profiles, setProfiles] = useState<{ name: string }[]>([]);
  const [history, setHistory] = useState<ScanSummary[]>([]);
  const [saved, setSaved] = useState<SavedReport[]>([]);
  const [now] = useState(() => Date.now());

  const [file, setFile] = useState<string | null>(null);
  const [report, setReport] = useState("");
  const [data, setData] = useState<Investigation | null>(null);
  const [streaming, setStreaming] = useState(false);
  const [failed, setFailed] = useState(false);
  const [trustFile, setTrustFile] = useState<string | null>(null);
  const source = useRef<EventSource | null>(null);

  const loadHistory = useCallback(() => {
    apiFetch(`${apiBase()}/admin/security/scans`)
      .then((r) => (r.ok ? r.json() : Promise.reject(r)))
      .then((d) => setHistory(d.scans || []))
      .catch(() => setToast({ message: t(`${k}.history.error`), variant: "error" }));
  }, [t]);

  const loadReports = useCallback(() => {
    apiFetch(`${apiBase()}/admin/security/reports`)
      .then((r) => (r.ok ? r.json() : Promise.reject(r)))
      .then((d) => setSaved(d.reports || []))
      .catch(() => {});
  }, []);

  useEffect(() => {
    apiFetch(`${apiBase()}/admin/profiles`)
      .then((r) => (r.ok ? r.json() : Promise.reject(r)))
      .then((d) => {
        const list: { name: string }[] = Array.isArray(d) ? d : [];
        setProfiles(list);
        setAgent((cur) => cur || list[0]?.name || "");
      })
      .catch(() => {});
    loadHistory();
    loadReports();
    return () => source.current?.close();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const runScan = async () => {
    setScanning(true);
    try {
      const res = await apiFetch(`${apiBase()}/admin/mcp/scan`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: targetPath.trim() || "mcp_servers" }),
      });
      if (!res.ok) throw new Error(String(res.status));
      setScan(await res.json());
      setTab("findings");
      setToast({ message: t(`${k}.scan.ok`), variant: "success" });
      loadHistory();
    } catch (e) {
      setToast({ message: t(`${k}.scan.failed`, { error: e instanceof Error ? e.message : "" }), variant: "error" });
    } finally {
      setScanning(false);
    }
  };

  const openScan = async (id: string) => {
    try {
      const res = await apiFetch(`${apiBase()}/admin/security/scans/${id}`);
      if (!res.ok) throw new Error();
      const d: ScanResult = await res.json();
      setScan(d);
      setTab("findings");
      setToast({ message: t(`${k}.history.loaded`, { when: fullWhen(toMs(d.timestamp)) }), variant: "info" });
    } catch {
      setToast({ message: t(`${k}.history.load_error`), variant: "error" });
    }
  };

  const openReport = async (id: string, profile: string) => {
    source.current?.close();
    setStreaming(false);
    setFailed(false);
    try {
      const res = await apiFetch(`${apiBase()}/admin/security/report/${id}`);
      if (!res.ok) throw new Error();
      const d = await res.json();
      setFile(d.path);
      setAgent(profile || agent);
      setReport(d.content);
      setData(extractInvestigation(d.content));
    } catch {
      setToast({ message: t(`${k}.saved.load_error`), variant: "error" });
    }
  };

  const investigate = (path: string) => {
    if (!agent) return;
    source.current?.close();
    setFile(path);
    setReport("");
    setData(null);
    setFailed(false);
    setStreaming(true);

    const url = `${apiBase()}/admin/security/investigate?path=${encodeURIComponent(path)}&profile=${encodeURIComponent(agent)}&access_token=${getStoredToken()}`;
    const es = new EventSource(url);
    source.current = es;
    let full = "";
    es.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.type === "token") {
        full += msg.content;
        setReport(full);
      } else if (msg.type === "final") {
        es.close();
        setReport(full);
        setData(extractInvestigation(full));
        setStreaming(false);
        loadReports();
      }
    };
    es.onerror = () => {
      es.close();
      setStreaming(false);
      if (!full) setFailed(true);
    };
  };

  const confirmTrust = async () => {
    const path = trustFile;
    setTrustFile(null);
    if (!path || !scan?.id) return;
    try {
      const res = await apiFetch(`${apiBase()}/admin/security/scans/${scan.id}/trust`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path }),
      });
      if (!res.ok) throw new Error();
      setScan((prev) => {
        if (!prev) return prev;
        const violations = { ...prev.violations, [path]: { ...prev.violations[path], is_trusted: true } };
        const is_safe = Object.values(violations).every((v) => v.is_trusted || !v.list.some((x) => x.severity === "high" || x.severity === "critical"));
        return { ...prev, violations, is_safe };
      });
      setToast({ message: t(`${k}.trust.done`, { name: baseName(path) }), variant: "success" });
      loadHistory();
    } catch {
      setToast({ message: t(`${k}.trust.failed`), variant: "error" });
    }
  };

  const exportReport = () => {
    if (!file) return;
    const lines = [`# AION security audit`, ``, `**File**: \`${file}\``, `**Date**: ${new Date().toLocaleString()}`, `**Investigator**: ${agent}`, ``];
    if (data) {
      lines.push(`## Summary`, ``, `> **Verdict**: ${data.verdict || "UNKNOWN"}`, `> **Risk score**: ${data.risk_score ?? "N/A"}%`, ``, data.summary || "", ``);
      if (data.fixes?.length) lines.push(`### Recommended mitigations`, ...data.fixes.map((f) => `- [ ] ${f}`), ``);
    }
    lines.push(`## Technical analysis`, ``, stripJson(report));
    const url = URL.createObjectURL(new Blob([lines.join("\n")], { type: "text/markdown" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `AION_Security_Report_${baseName(file)}.md`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  };

  const tabs: { id: Tab; label: string; count?: number }[] = [
    { id: "findings", label: t(`${k}.tabs.findings`), count: scan ? Object.values(scan.violations || {}).filter((v) => !v.is_trusted).length : undefined },
    { id: "scans", label: t(`${k}.tabs.scans`) },
    { id: "reports", label: t(`${k}.tabs.reports`) },
  ];

  const agentOptions = profiles.map((p) => p.name).map((n) => ({ value: n, label: n }));

  return (
    <div className="mx-auto flex max-w-[84rem] flex-col gap-6">
      <header className="flex flex-col gap-4 pt-2 sm:flex-row sm:items-end">
        <div className="min-w-0 flex-1">
          <h1 className="text-balance text-2xl font-semibold tracking-[-0.02em] sm:text-[28px]">{t(`${k}.title`)}</h1>
          <p className="mt-1 max-w-[60ch] text-sm text-muted-foreground">{t(`${k}.subtitle`)}</p>
        </div>
      </header>

      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (!scanning) runScan();
        }}
      >
        <label className="flex min-w-[14rem] flex-1 flex-col gap-1.5 sm:max-w-md">
          <span className="text-xs font-medium text-muted-foreground">{t(`${k}.scan.path_label`)}</span>
          <span className="relative">
            <FolderSearch className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
            <input
              value={targetPath}
              onChange={(e) => setTargetPath(e.target.value)}
              placeholder={t(`${k}.scan.path_placeholder`)}
              spellCheck={false}
              autoComplete="off"
              className={cn(inputCls, "bg-card pl-10 font-mono")}
            />
          </span>
        </label>
        <div className="flex w-56 flex-col gap-1.5">
          <span className="text-xs font-medium text-muted-foreground" id="agent-label">
            {t(`${k}.scan.investigator`)}
          </span>
          <Select value={agent} onChange={setAgent} options={agentOptions} aria-label={t(`${k}.scan.investigator`)} className="bg-card" />
        </div>
        <button type="submit" className={cn(solidBtn, "h-[2.65rem]")} disabled={scanning}>
          {scanning ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <ScanSearch className="h-4 w-4" aria-hidden />}
          {scanning ? t(`${k}.scan.running`) : t(`${k}.scan.run`)}
        </button>
        {scan && (
          <p className="ml-auto flex min-w-0 items-center gap-2 pb-2.5 text-sm text-muted-foreground">
            {scan.is_safe ? <ShieldCheck className="h-4 w-4 shrink-0 text-success" aria-hidden /> : <ShieldAlert className="h-4 w-4 shrink-0 text-destructive" aria-hidden />}
            <span className="truncate font-mono text-[13px]">{scan.target_path}</span>
            <span className="shrink-0 tabular-nums">· {shortWhen(toMs(scan.timestamp), now)}</span>
          </p>
        )}
      </form>

      <div className="grid gap-6 lg:h-[calc(100dvh-19rem)] lg:min-h-[34rem] lg:grid-cols-[minmax(0,26rem)_minmax(0,1fr)]">
        <section className="flex max-h-[34rem] min-h-[22rem] flex-col overflow-hidden rounded-3xl border border-border/70 bg-card lg:max-h-none">
          <div role="tablist" aria-label={t(`${k}.tabs.aria`)} className="no-scrollbar flex gap-1 overflow-x-auto border-b border-border/60 px-2">
            {tabs.map((x) => {
              const active = tab === x.id;
              return (
                <button
                  key={x.id}
                  type="button"
                  role="tab"
                  id={`sec-tab-${x.id}`}
                  aria-selected={active}
                  aria-controls="sec-panel"
                  onClick={() => setTab(x.id)}
                  className={cn(
                    "focus-ring relative inline-flex h-11 shrink-0 items-center gap-2 px-3 text-sm font-medium transition-colors",
                    active ? "text-foreground" : "text-muted-foreground hover:text-foreground",
                  )}
                >
                  {x.label}
                  {!!x.count && <span className="rounded-full bg-secondary px-1.5 py-px text-xs tabular-nums text-muted-foreground">{x.count}</span>}
                  <span aria-hidden className={cn("absolute inset-x-3 bottom-0 h-0.5 rounded-full bg-foreground transition-opacity", active ? "opacity-100" : "opacity-0")} />
                </button>
              );
            })}
          </div>

          <div id="sec-panel" role="tabpanel" aria-labelledby={`sec-tab-${tab}`} className="flex min-h-0 flex-1 flex-col">
            {tab === "findings" && (
              <FindingsList scan={scan} activeFile={file} streaming={streaming} onInvestigate={investigate} onTrust={setTrustFile} t={t} />
            )}
            {tab === "scans" &&
              (history.length === 0 ? (
                <p className="px-6 py-16 text-center text-sm text-muted-foreground">{t(`${k}.history.empty`)}</p>
              ) : (
                <ul className="min-h-0 flex-1 overflow-y-auto">
                  {history.map((s) => (
                    <li key={s.id} className="border-b border-border/40 last:border-b-0">
                      <button
                        type="button"
                        onClick={() => openScan(s.id)}
                        aria-current={scan?.id === s.id ? "true" : undefined}
                        className={cn("focus-ring flex w-full items-center gap-3 px-5 py-3 text-left transition-colors hover:bg-secondary/60", scan?.id === s.id && "bg-secondary")}
                      >
                        <span className="min-w-0 flex-1">
                          <span className="block truncate font-mono text-[13px] font-medium">{s.target_path}</span>
                          <span className="block text-xs tabular-nums text-muted-foreground">{fullWhen(toMs(s.timestamp))}</span>
                        </span>
                        <span className={cn("shrink-0 text-xs font-semibold", s.is_safe ? "text-success" : "text-destructive")}>
                          {s.is_safe ? t(`${k}.history.clean`) : t(`${k}.history.threats`)}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              ))}
            {tab === "reports" &&
              (saved.length === 0 ? (
                <p className="mx-auto max-w-[32ch] px-6 py-16 text-center text-sm text-muted-foreground">{t(`${k}.saved.empty`)}</p>
              ) : (
                <ul className="min-h-0 flex-1 overflow-y-auto">
                  {saved.map((r) => (
                    <li key={r.id} className="border-b border-border/40 last:border-b-0">
                      <button
                        type="button"
                        onClick={() => openReport(r.id, r.profile)}
                        className={cn("focus-ring flex w-full flex-col px-5 py-3 text-left transition-colors hover:bg-secondary/60", file === r.path && !streaming && "bg-secondary")}
                      >
                        <span className="truncate font-mono text-[13px] font-medium" title={r.path}>
                          {baseName(r.path)}
                        </span>
                        <span className="truncate text-xs text-muted-foreground">
                          {r.profile} · <span className="tabular-nums">{fullWhen(toMs(r.timestamp))}</span>
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              ))}
          </div>
        </section>

        <section className="flex min-h-[26rem] flex-col overflow-hidden rounded-3xl border border-border/70 bg-card" aria-label={t(`${k}.tabs.reports`)}>
          <ReportPanel file={file} agent={agent} report={report} data={data} streaming={streaming} failed={failed} onExport={exportReport} t={t} />
        </section>
      </div>

      {trustFile && (
        <Dialog title={t(`${k}.trust.title`)} closeLabel={t(`${k}.trust.cancel`)} onClose={() => setTrustFile(null)}>
          <div className="flex flex-col gap-5">
            <p className="text-sm text-muted-foreground">{t(`${k}.trust.body`, { name: baseName(trustFile) })}</p>
            <div className="flex justify-end gap-2">
              <button type="button" className={ghostBtn} onClick={() => setTrustFile(null)}>
                {t(`${k}.trust.cancel`)}
              </button>
              <button type="button" className={solidBtn} autoFocus onClick={confirmTrust}>
                {t(`${k}.trust.confirm`)}
              </button>
            </div>
          </div>
        </Dialog>
      )}
      <PageToast toast={toast} onDismiss={() => setToast(null)} />
    </div>
  );
}
