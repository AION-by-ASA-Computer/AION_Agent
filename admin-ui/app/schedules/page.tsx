"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Clock,
  Play,
  Trash2,
  RefreshCw,
  Pencil,
  Power,
  PowerOff,
  History,
  X,
  AlertTriangle,
} from "lucide-react";
import { apiBase } from "@/lib/api";
import { apiFetch } from "@/lib/api/headers";
import { PageToast, ToastState } from "@/components/PageToast";

type CronJob = {
  job_id: string;
  user_id: string;
  name: string;
  cron_expression: string;
  timezone: string;
  profile_slug: string;
  prompt: string;
  session_mode: string;
  session_id?: string | null;
  enabled: boolean;
  next_run_at?: string | null;
  last_run?: { status?: string; started_at?: string } | null;
};

type CronRun = {
  run_id: string;
  status: string;
  started_at?: string;
  finished_at?: string;
  error_message?: string;
  assistant_preview?: string;
};

export default function SchedulesPage() {
  const [jobs, setJobs] = useState<CronJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [filterUser, setFilterUser] = useState("");
  const [filterEnabled, setFilterEnabled] = useState<string>("");
  const [toast, setToast] = useState<ToastState>(null);
  const [editing, setEditing] = useState<CronJob | null>(null);
  const [runsJob, setRunsJob] = useState<CronJob | null>(null);
  const [runs, setRuns] = useState<CronRun[]>([]);
  const [runsLoading, setRunsLoading] = useState(false);

  const [formName, setFormName] = useState("");
  const [formCron, setFormCron] = useState("");
  const [formPrompt, setFormPrompt] = useState("");
  const [formProfile, setFormProfile] = useState("generic_assistant");
  const [formTz, setFormTz] = useState("Europe/Rome");
  const [formSessionMode, setFormSessionMode] = useState("fixed");
  const [formEnabled, setFormEnabled] = useState(true);

  const [cronEnabledGlobal, setCronEnabledGlobal] = useState<boolean | null>(null);
  const [updatingGlobal, setUpdatingGlobal] = useState(false);
  const [restarting, setRestarting] = useState(false);
  const [showConfirmModal, setShowConfirmModal] = useState(false);
  const [pendingGlobalValue, setPendingGlobalValue] = useState<boolean | null>(null);

  const fetchGlobalCronStatus = useCallback(async () => {
    try {
      const res = await apiFetch(`${apiBase()}/admin/settings`);
      if (res.ok) {
        const data = await res.json();
        const enabled = data.settings?.AION_CRON_ENABLED === "1";
        setCronEnabledGlobal(enabled);
      }
    } catch (e) {
      console.error("Failed to load global cron settings", e);
    }
  }, []);

  const fetchJobs = useCallback(async () => {
    setLoading(true);
    try {
      const q = new URLSearchParams();
      if (filterUser.trim()) q.set("user_id", filterUser.trim());
      if (filterEnabled === "1") q.set("enabled", "true");
      if (filterEnabled === "0") q.set("enabled", "false");
      const res = await apiFetch(`${apiBase()}/admin/cron-jobs?${q.toString()}`);
      if (!res.ok) {
        if (res.status === 503) {
          const err = await res.json().catch(() => ({}));
          if (err.detail && err.detail.includes("AION_CRON_ENABLED=0")) {
            setCronEnabledGlobal(false);
            setJobs([]);
            return;
          }
        }
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Failed to load jobs");
      }
      const data = await res.json();
      setJobs(data.jobs || []);
    } catch (e: unknown) {
      setToast({
        message: e instanceof Error ? e.message : "Load failed",
        variant: "error",
      });
    } finally {
      setLoading(false);
    }
  }, [filterUser, filterEnabled]);

  const pollHealth = useCallback(async () => {
    const maxAttempts = 30;
    let attempt = 0;

    await new Promise((resolve) => setTimeout(resolve, 2000));

    const interval = setInterval(async () => {
      attempt++;
      try {
        const res = await fetch(`${apiBase()}/health`);
        if (res.ok) {
          const data = await res.json();
          if (data.status === "ok") {
            clearInterval(interval);
            setRestarting(false);
            setToast({ message: "API Container restarted and configuration applied successfully.", variant: "success" });
            fetchGlobalCronStatus();
            fetchJobs();
          }
        }
      } catch (err) {
        console.log("Waiting for backend to come back online...", err);
      }

      if (attempt >= maxAttempts) {
        clearInterval(interval);
        setRestarting(false);
        setToast({ message: "API Container took too long to restart. Please verify manually.", variant: "error" });
        fetchGlobalCronStatus();
        fetchJobs();
      }
    }, 1500);
  }, [fetchGlobalCronStatus, fetchJobs]);

  const toggleGlobalCron = async (forcedValue?: boolean) => {
    setUpdatingGlobal(true);
    try {
      const settingsRes = await apiFetch(`${apiBase()}/admin/settings`);
      if (!settingsRes.ok) throw new Error("Failed to fetch current settings");
      const currentSettingsData = await settingsRes.json();
      const currentSettings = currentSettingsData.settings || {};

      const nextVal = forcedValue !== undefined ? forcedValue : !cronEnabledGlobal;

      const res = await apiFetch(`${apiBase()}/admin/settings`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          settings: {
            ...currentSettings,
            AION_CRON_ENABLED: nextVal ? "1" : "0",
          },
        }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Failed to update global cron setting");
      }

      const data = await res.json();
      if (data.restarting) {
        setRestarting(true);
        pollHealth();
      } else {
        setToast({
          message: `Cron scheduler ${nextVal ? "enabled" : "disabled"} successfully.`,
          variant: "success",
        });
        await fetchGlobalCronStatus();
        await fetchJobs();
      }
    } catch (e: unknown) {
      setToast({
        message: e instanceof Error ? e.message : "Failed to toggle global scheduler status",
        variant: "error",
      });
    } finally {
      setUpdatingGlobal(false);
    }
  };

  const handleToggleClick = (forcedValue?: boolean) => {
    const nextVal = forcedValue !== undefined ? forcedValue : !cronEnabledGlobal;
    setPendingGlobalValue(nextVal);
    setShowConfirmModal(true);
  };

  const confirmToggleGlobalCron = async () => {
    if (pendingGlobalValue === null) return;
    setShowConfirmModal(false);
    const val = pendingGlobalValue;
    setPendingGlobalValue(null);
    await toggleGlobalCron(val);
  };

  useEffect(() => {
    fetchGlobalCronStatus();
    fetchJobs();
  }, [fetchJobs, fetchGlobalCronStatus]);

  const openEdit = (job: CronJob) => {
    setEditing(job);
    setFormName(job.name);
    setFormCron(job.cron_expression);
    setFormPrompt(job.prompt);
    setFormProfile(job.profile_slug);
    setFormTz(job.timezone);
    setFormSessionMode(job.session_mode);
    setFormEnabled(job.enabled);
  };

  const saveEdit = async () => {
    if (!editing) return;
    setLoading(true);
    try {
      const res = await apiFetch(`${apiBase()}/admin/cron-jobs/${editing.job_id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: formName,
          cron_expression: formCron,
          prompt: formPrompt,
          profile_slug: formProfile,
          timezone: formTz,
          session_mode: formSessionMode,
          enabled: formEnabled,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Save failed");
      }
      setEditing(null);
      setToast({ message: "Job updated", variant: "success" });
      await fetchJobs();
    } catch (e: unknown) {
      setToast({
        message: e instanceof Error ? e.message : "Save failed",
        variant: "error",
      });
    } finally {
      setLoading(false);
    }
  };

  const runNow = async (jobId: string) => {
    try {
      const res = await apiFetch(`${apiBase()}/admin/cron-jobs/${jobId}/run-now`, {
        method: "POST",
      });
      if (!res.ok) throw new Error("Run failed");
      setToast({ message: "Run started", variant: "success" });
      await fetchJobs();
    } catch (e: unknown) {
      setToast({
        message: e instanceof Error ? e.message : "Run failed",
        variant: "error",
      });
    }
  };

  const toggleEnabled = async (job: CronJob) => {
    try {
      const res = await apiFetch(`${apiBase()}/admin/cron-jobs/${job.job_id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: !job.enabled }),
      });
      if (!res.ok) throw new Error("Update failed");
      await fetchJobs();
    } catch (e: unknown) {
      setToast({
        message: e instanceof Error ? e.message : "Update failed",
        variant: "error",
      });
    }
  };

  const deleteJob = async (jobId: string) => {
    if (!confirm("Delete this scheduled job?")) return;
    try {
      const res = await apiFetch(`${apiBase()}/admin/cron-jobs/${jobId}`, {
        method: "DELETE",
      });
      if (!res.ok) throw new Error("Delete failed");
      setToast({ message: "Job deleted", variant: "success" });
      await fetchJobs();
    } catch (e: unknown) {
      setToast({
        message: e instanceof Error ? e.message : "Delete failed",
        variant: "error",
      });
    }
  };

  const openRuns = async (job: CronJob) => {
    setRunsJob(job);
    setRunsLoading(true);
    try {
      const res = await apiFetch(`${apiBase()}/admin/cron-jobs/${job.job_id}/runs`);
      if (!res.ok) throw new Error("Failed to load runs");
      const data = await res.json();
      setRuns(data.runs || []);
    } catch {
      setRuns([]);
    } finally {
      setRunsLoading(false);
    }
  };

  return (
    <div className="p-8 max-w-7xl mx-auto">
      <PageToast toast={toast} onDismiss={() => setToast(null)} />
      <div className="flex flex-wrap items-center gap-4 mb-6">
        <div className="flex items-center gap-3">
          <Clock className="w-8 h-8 text-blue-400" />
          <div>
            <h1 className="text-2xl font-bold">Scheduled jobs</h1>
            <p className="text-sm text-gray-400">Per-user cron jobs (requires AION_CRON_ENABLED=1)</p>
          </div>
        </div>

        {/* Global Scheduler Toggle Switch */}
        <div className="sm:ml-auto flex items-center gap-3 bg-[#171717] border border-[#262626] px-4 py-2 rounded-lg">
          <span className="text-sm font-medium text-gray-300">Global Scheduler:</span>
          {cronEnabledGlobal === null ? (
            <span className="text-xs text-gray-500 animate-pulse">Loading...</span>
          ) : (
            <button
              type="button"
              disabled={updatingGlobal}
              onClick={() => handleToggleClick()}
              className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors duration-200 focus:outline-none ${
                cronEnabledGlobal ? "bg-green-600" : "bg-zinc-800"
              } ${updatingGlobal ? "opacity-50 cursor-not-allowed" : "cursor-pointer"}`}
            >
              <span
                className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform duration-200 ${
                  cronEnabledGlobal ? "translate-x-6" : "translate-x-1"
                }`}
              />
            </button>
          )}
          <span className={`text-xs font-semibold ${cronEnabledGlobal ? "text-green-400" : "text-gray-500"}`}>
            {cronEnabledGlobal === null ? "" : cronEnabledGlobal ? "ENABLED" : "DISABLED"}
          </span>
        </div>

        <button
          type="button"
          onClick={() => {
            fetchGlobalCronStatus();
            fetchJobs();
          }}
          className="flex items-center gap-2 px-3 py-2 rounded bg-[#262626] hover:bg-[#333] text-sm"
        >
          <RefreshCw className="w-4 h-4" />
          Refresh
        </button>
      </div>

      {cronEnabledGlobal === false && (
        <div className="bg-amber-500/10 border border-amber-500/20 text-amber-400 p-4 rounded-xl flex items-center gap-3 mb-6 animate-in fade-in duration-300">
          <AlertTriangle className="w-5 h-5 flex-shrink-0" />
          <div className="text-sm text-left">
            <span className="font-bold">Global Scheduler is Disabled.</span> Active jobs will not fire automatically. You can enable it using the switch above.
          </div>
        </div>
      )}

      <div className="flex flex-wrap gap-3 mb-4">
        <input
          className="bg-[#171717] border border-[#333] rounded px-3 py-2 text-sm"
          placeholder="Filter user_id"
          value={filterUser}
          onChange={(e) => setFilterUser(e.target.value)}
        />
        <select
          className="bg-[#171717] border border-[#333] rounded px-3 py-2 text-sm"
          value={filterEnabled}
          onChange={(e) => setFilterEnabled(e.target.value)}
        >
          <option value="">All</option>
          <option value="1">Enabled</option>
          <option value="0">Disabled</option>
        </select>
      </div>

      {loading ? (
        <p className="text-gray-400">Loading…</p>
      ) : jobs.length === 0 ? (
        <p className="text-gray-400">No scheduled jobs.</p>
      ) : (
        <div className="overflow-x-auto border border-[#262626] rounded-lg">
          <table className="w-full text-sm">
            <thead className="bg-[#171717] text-left text-gray-400">
              <tr>
                <th className="p-3">User</th>
                <th className="p-3">Name</th>
                <th className="p-3">Cron</th>
                <th className="p-3">TZ</th>
                <th className="p-3">Profile</th>
                <th className="p-3">Session</th>
                <th className="p-3">Next</th>
                <th className="p-3">Last</th>
                <th className="p-3">On</th>
                <th className="p-3">Actions</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((j) => (
                <tr key={j.job_id} className="border-t border-[#262626]">
                  <td className="p-3 font-mono text-xs">{j.user_id}</td>
                  <td className="p-3">{j.name}</td>
                  <td className="p-3 font-mono text-xs">{j.cron_expression}</td>
                  <td className="p-3 text-xs">{j.timezone}</td>
                  <td className="p-3 text-xs">{j.profile_slug}</td>
                  <td className="p-3 text-xs">{j.session_mode}</td>
                  <td className="p-3 text-xs text-gray-400">
                    {j.next_run_at ? new Date(j.next_run_at).toLocaleString() : "—"}
                  </td>
                  <td className="p-3 text-xs">
                    {j.last_run?.status || "—"}
                  </td>
                  <td className="p-3">{j.enabled ? "✓" : "—"}</td>
                  <td className="p-3">
                    <div className="flex gap-1">
                      <button
                        type="button"
                        title="Edit"
                        onClick={() => openEdit(j)}
                        className="p-1.5 rounded hover:bg-[#333]"
                      >
                        <Pencil className="w-4 h-4" />
                      </button>
                      <button
                        type="button"
                        title="Run now"
                        onClick={() => runNow(j.job_id)}
                        className="p-1.5 rounded hover:bg-[#333]"
                      >
                        <Play className="w-4 h-4" />
                      </button>
                      <button
                        type="button"
                        title={j.enabled ? "Disable" : "Enable"}
                        onClick={() => toggleEnabled(j)}
                        className="p-1.5 rounded hover:bg-[#333]"
                      >
                        {j.enabled ? (
                          <PowerOff className="w-4 h-4" />
                        ) : (
                          <Power className="w-4 h-4" />
                        )}
                      </button>
                      <button
                        type="button"
                        title="History"
                        onClick={() => openRuns(j)}
                        className="p-1.5 rounded hover:bg-[#333]"
                      >
                        <History className="w-4 h-4" />
                      </button>
                      <button
                        type="button"
                        title="Delete"
                        onClick={() => deleteJob(j.job_id)}
                        className="p-1.5 rounded hover:bg-red-900/40 text-red-400"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {editing && (
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
          <div className="bg-[#0a0a0a] border border-[#333] rounded-lg w-full max-w-lg p-6">
            <div className="flex justify-between mb-4">
              <h2 className="font-semibold">Edit job</h2>
              <button type="button" onClick={() => setEditing(null)}>
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="space-y-3 text-sm">
              <input
                className="w-full bg-[#171717] border border-[#333] rounded px-3 py-2"
                value={formName}
                onChange={(e) => setFormName(e.target.value)}
                placeholder="Name"
              />
              <input
                className="w-full bg-[#171717] border border-[#333] rounded px-3 py-2 font-mono"
                value={formCron}
                onChange={(e) => setFormCron(e.target.value)}
                placeholder="Cron (5 fields)"
              />
              <textarea
                className="w-full bg-[#171717] border border-[#333] rounded px-3 py-2 min-h-[80px]"
                value={formPrompt}
                onChange={(e) => setFormPrompt(e.target.value)}
                placeholder="Prompt"
              />
              <input
                className="w-full bg-[#171717] border border-[#333] rounded px-3 py-2"
                value={formProfile}
                onChange={(e) => setFormProfile(e.target.value)}
                placeholder="Profile slug"
              />
              <input
                className="w-full bg-[#171717] border border-[#333] rounded px-3 py-2"
                value={formTz}
                onChange={(e) => setFormTz(e.target.value)}
                placeholder="Timezone"
              />
              <select
                className="w-full bg-[#171717] border border-[#333] rounded px-3 py-2"
                value={formSessionMode}
                onChange={(e) => setFormSessionMode(e.target.value)}
              >
                <option value="fixed">fixed session</option>
                <option value="new">new session each run</option>
              </select>
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={formEnabled}
                  onChange={(e) => setFormEnabled(e.target.checked)}
                />
                Enabled
              </label>
            </div>
            <div className="flex justify-end gap-2 mt-4">
              <button
                type="button"
                className="px-4 py-2 rounded bg-[#262626]"
                onClick={() => setEditing(null)}
              >
                Cancel
              </button>
              <button
                type="button"
                className="px-4 py-2 rounded bg-blue-600 hover:bg-blue-500"
                onClick={saveEdit}
              >
                Save
              </button>
            </div>
          </div>
        </div>
      )}

      {runsJob && (
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
          <div className="bg-[#0a0a0a] border border-[#333] rounded-lg w-full max-w-2xl max-h-[80vh] overflow-auto p-6">
            <div className="flex justify-between mb-4">
              <h2 className="font-semibold">Runs — {runsJob.name}</h2>
              <button type="button" onClick={() => setRunsJob(null)}>
                <X className="w-5 h-5" />
              </button>
            </div>
            {runsLoading ? (
              <p className="text-gray-400">Loading…</p>
            ) : runs.length === 0 ? (
              <p className="text-gray-400">No runs yet.</p>
            ) : (
              <ul className="space-y-2 text-sm">
                {runs.map((r) => (
                  <li key={r.run_id} className="border border-[#333] rounded p-3">
                    <div className="flex justify-between">
                      <span className="font-mono text-xs">{r.status}</span>
                      <span className="text-gray-500 text-xs">
                        {r.started_at ? new Date(r.started_at).toLocaleString() : ""}
                      </span>
                    </div>
                    {r.error_message && (
                      <p className="text-red-400 mt-1 text-xs">{r.error_message}</p>
                    )}
                    {r.assistant_preview && (
                      <p className="text-gray-400 mt-1 text-xs line-clamp-3">
                        {r.assistant_preview}
                      </p>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}

      {showConfirmModal && (
        <div className="fixed inset-0 bg-black/80 backdrop-blur-sm flex items-center justify-center z-50 p-4 animate-in fade-in duration-200">
          <div className="bg-[#0a0a0a] border border-[#333] rounded-2xl w-full max-w-md p-6 shadow-2xl shadow-amber-500/5 space-y-6">
            <div className="flex items-center gap-4">
              <div className="p-3 bg-amber-500/15 text-amber-500 rounded-xl">
                <AlertTriangle className="w-6 h-6 animate-pulse" />
              </div>
              <div>
                <h3 className="text-lg font-bold text-white">Restart Kernel Required</h3>
                <p className="text-xs text-gray-400">Action: {pendingGlobalValue ? "Enable" : "Disable"} Global Scheduler</p>
              </div>
            </div>

            <p className="text-sm text-gray-300 leading-relaxed text-left">
              Toggling the global scheduler requires restarting the <strong className="text-white">AI Kernel (API container)</strong> to apply the changes. 
              This will temporarily interrupt active background operations.
            </p>

            <div className="flex justify-end gap-3 pt-2">
              <button
                type="button"
                className="px-4 py-2 text-sm font-medium text-gray-400 bg-zinc-900 border border-[#262626] rounded-xl hover:bg-zinc-800 transition-colors"
                onClick={() => {
                  setShowConfirmModal(false);
                  setPendingGlobalValue(null);
                }}
              >
                Cancel
              </button>
              <button
                type="button"
                className="px-5 py-2 text-sm font-semibold text-white bg-amber-600 hover:bg-amber-500 rounded-xl transition-all shadow-lg shadow-amber-600/25 active:scale-95"
                onClick={confirmToggleGlobalCron}
              >
                Proceed & Restart
              </button>
            </div>
          </div>
        </div>
      )}

      {restarting && (
        <div className="fixed inset-0 bg-black/80 backdrop-blur-md flex flex-col items-center justify-center z-50 animate-in fade-in duration-300">
          <div className="bg-[#0d0d0d] border border-[#262626] rounded-3xl p-8 max-w-md w-full text-center space-y-6 shadow-2xl shadow-blue-500/10">
            <div className="relative w-20 h-20 mx-auto">
              <div className="absolute inset-0 border-4 border-blue-500/20 rounded-full" />
              <div className="absolute inset-0 border-4 border-t-blue-500 rounded-full animate-spin" />
            </div>
            <div className="space-y-2">
              <h3 className="text-xl font-bold text-white">Reinitializing AI Kernel</h3>
              <p className="text-sm text-gray-500">
                The API container is restarting to apply the new scheduler settings. This usually takes about 5 to 10 seconds.
              </p>
            </div>
            <div className="text-[10px] font-bold uppercase tracking-widest text-blue-500 bg-blue-500/10 px-3 py-1.5 rounded-full inline-block animate-pulse">
              Waiting for health check...
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
