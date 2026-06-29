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

  const fetchJobs = useCallback(async () => {
    setLoading(true);
    try {
      const q = new URLSearchParams();
      if (filterUser.trim()) q.set("user_id", filterUser.trim());
      if (filterEnabled === "1") q.set("enabled", "true");
      if (filterEnabled === "0") q.set("enabled", "false");
      const res = await apiFetch(`${apiBase()}/admin/cron-jobs?${q.toString()}`);
      if (!res.ok) {
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

  useEffect(() => {
    fetchJobs();
  }, [fetchJobs]);

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
      <div className="flex items-center gap-3 mb-6">
        <Clock className="w-8 h-8 text-blue-400" />
        <div>
          <h1 className="text-2xl font-bold">Scheduled jobs</h1>
          <p className="text-sm text-gray-400">Per-user cron jobs (requires AION_CRON_ENABLED=1)</p>
        </div>
        <button
          type="button"
          onClick={() => fetchJobs()}
          className="ml-auto flex items-center gap-2 px-3 py-2 rounded bg-[#262626] hover:bg-[#333] text-sm"
        >
          <RefreshCw className="w-4 h-4" />
          Refresh
        </button>
      </div>

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
    </div>
  );
}
