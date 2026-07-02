"use client";

import { useEffect, useState, useCallback } from "react";
import { load as yamlLoad } from "js-yaml";
import {
  Plus, Trash2, ChevronDown, ChevronUp, Terminal, FolderOpen,
  FolderX, Gauge, Shield, AlertTriangle, Code, FileText,
} from "lucide-react";

// ─── Types ───────────────────────────────────────────────────────────────────

export interface ExecRule {
  executable: string;
  argv_prefix: string[];
  validate_path_positions: number[];
}

export interface FsPolicyLimits {
  max_file_read_bytes: number;
  max_file_write_bytes: number;
  max_edit_file_bytes: number;
  grep_max_file_bytes: number;
  grep_max_matches: number;
  glob_max_paths: number;
  chunk_max_lines: number;
}

export interface FsPolicyState {
  version: string;
  filesystem_allow: string[];
  filesystem_deny: string[];
  exec_enabled: boolean;
  exec_allowlist: ExecRule[];
  limits: FsPolicyLimits;
}

// ─── Default state ────────────────────────────────────────────────────────────

const DEFAULT_STATE: FsPolicyState = {
  version: "1.0",
  filesystem_allow: ["workspace/**"],
  filesystem_deny: [],
  exec_enabled: false,
  exec_allowlist: [],
  limits: {
    max_file_read_bytes: 2097152,
    max_file_write_bytes: 10485760,
    max_edit_file_bytes: 2097152,
    grep_max_file_bytes: 524288,
    grep_max_matches: 200,
    glob_max_paths: 500,
    chunk_max_lines: 500,
  },
};

// ─── YAML ↔ State helpers ─────────────────────────────────────────────────────

function yamlToPolicy(raw: string): { state: FsPolicyState; error: string | null } {
  try {
    const doc = yamlLoad(raw) as Record<string, unknown>;
    if (!doc || typeof doc !== "object") {
      return { state: DEFAULT_STATE, error: "Invalid YAML: root must be a mapping." };
    }

    const fs = (doc.filesystem as Record<string, unknown>) || {};
    const ex = (doc.exec as Record<string, unknown>) || {};
    const lim = (doc.limits as Record<string, unknown>) || {};

    const allowRaw = fs.allow;
    const denyRaw = fs.deny;

    const allow: string[] = Array.isArray(allowRaw) ? allowRaw.filter(Boolean).map(String) : [];
    const deny: string[] = Array.isArray(denyRaw) ? denyRaw.filter(Boolean).map(String) : [];

    const allowlistRaw = ex.allowlist;
    const allowlist: ExecRule[] = [];
    if (Array.isArray(allowlistRaw)) {
      for (const entry of allowlistRaw) {
        if (!entry || typeof entry !== "object") continue;
        const e = entry as Record<string, unknown>;
        allowlist.push({
          executable: String(e.executable || ""),
          argv_prefix: Array.isArray(e.argv_prefix)
            ? e.argv_prefix.filter(Boolean).map(String)
            : [],
          validate_path_positions: Array.isArray(e.validate_path_positions)
            ? e.validate_path_positions.map(Number).filter((n) => !isNaN(n))
            : [],
        });
      }
    }

    const g = (key: string, fallback: number) => {
      const v = lim[key];
      return typeof v === "number" ? v : fallback;
    };

    const state: FsPolicyState = {
      version: String(doc.version || "1.0"),
      filesystem_allow: allow,
      filesystem_deny: deny,
      exec_enabled: Boolean(ex.enabled),
      exec_allowlist: allowlist,
      limits: {
        max_file_read_bytes: g("max_file_read_bytes", 2097152),
        max_file_write_bytes: g("max_file_write_bytes", 10485760),
        max_edit_file_bytes: g("max_edit_file_bytes", 2097152),
        grep_max_file_bytes: g("grep_max_file_bytes", 524288),
        grep_max_matches: g("grep_max_matches", 200),
        glob_max_paths: g("glob_max_paths", 500),
        chunk_max_lines: g("chunk_max_lines", 500),
      },
    };
    return { state, error: null };
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e);
    return { state: DEFAULT_STATE, error: `YAML parse error: ${msg}` };
  }
}

function policyToYaml(state: FsPolicyState): string {
  const lines: string[] = [];
  lines.push(`version: "${state.version}"`);
  lines.push(``);
  lines.push(`filesystem:`);
  lines.push(`  allow:`);
  for (const g of state.filesystem_allow) lines.push(`    - "${g}"`);
  if (state.filesystem_allow.length === 0) lines.push(`    []`);
  lines.push(`  deny:`);
  for (const g of state.filesystem_deny) lines.push(`    - "${g}"`);
  if (state.filesystem_deny.length === 0) lines.push(`    []`);
  lines.push(``);
  lines.push(`exec:`);
  lines.push(`  enabled: ${state.exec_enabled}`);
  lines.push(`  allowlist:`);
  if (state.exec_allowlist.length === 0) {
    lines.push(`    []`);
  } else {
    for (const rule of state.exec_allowlist) {
      lines.push(`    - executable: "${rule.executable}"`);
      if (rule.argv_prefix.length > 0) {
        const prefixItems = rule.argv_prefix.map((p) => `"${p}"`).join(", ");
        lines.push(`      argv_prefix: [${prefixItems}]`);
      } else {
        lines.push(`      argv_prefix: []`);
      }
      if (rule.validate_path_positions.length > 0) {
        lines.push(
          `      validate_path_positions: [${rule.validate_path_positions.join(", ")}]`
        );
      }
    }
  }
  lines.push(``);
  lines.push(`limits:`);
  const lim = state.limits;
  lines.push(`  max_file_read_bytes: ${lim.max_file_read_bytes}`);
  lines.push(`  max_file_write_bytes: ${lim.max_file_write_bytes}`);
  lines.push(`  max_edit_file_bytes: ${lim.max_edit_file_bytes}`);
  lines.push(`  grep_max_file_bytes: ${lim.grep_max_file_bytes}`);
  lines.push(`  grep_max_matches: ${lim.grep_max_matches}`);
  lines.push(`  glob_max_paths: ${lim.glob_max_paths}`);
  lines.push(`  chunk_max_lines: ${lim.chunk_max_lines}`);
  lines.push(``);
  return lines.join("\n");
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function SectionHeader({
  icon,
  title,
  subtitle,
  open,
  onToggle,
}: {
  icon: React.ReactNode;
  title: string;
  subtitle?: string;
  open: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      className="w-full flex items-center justify-between py-3 border-b border-[#1a1a1a] group/sec hover:border-amber-500/20 transition-colors"
    >
      <div className="flex items-center gap-2.5">
        <span className="text-amber-500">{icon}</span>
        <div className="text-left">
          <p className="text-sm font-bold text-white">{title}</p>
          {subtitle && (
            <p className="text-[10px] text-gray-500 uppercase tracking-wider font-bold">
              {subtitle}
            </p>
          )}
        </div>
      </div>
      {open ? (
        <ChevronUp className="w-4 h-4 text-gray-500" />
      ) : (
        <ChevronDown className="w-4 h-4 text-gray-500" />
      )}
    </button>
  );
}

function GlobTagList({
  label,
  values,
  onChange,
  readOnly,
  placeholder,
}: {
  label: string;
  values: string[];
  onChange: (next: string[]) => void;
  readOnly: boolean;
  placeholder?: string;
}) {
  const [draft, setDraft] = useState("");

  const add = () => {
    const v = draft.trim();
    if (v && !values.includes(v)) {
      onChange([...values, v]);
      setDraft("");
    }
  };

  return (
    <div className="space-y-2">
      <label className="text-[10px] font-bold uppercase text-gray-500 tracking-wider">
        {label}
      </label>
      <div className="flex flex-wrap gap-2 p-3 bg-[#070707] border border-[#1f1f1f] rounded-xl min-h-[52px]">
        {values.map((v, i) => (
          <span
            key={i}
            className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-amber-500/10 border border-amber-500/20 text-amber-300 text-xs font-mono"
          >
            {v}
            {!readOnly && (
              <button
                type="button"
                onClick={() => onChange(values.filter((_, j) => j !== i))}
                className="text-amber-500/60 hover:text-red-400 transition-colors ml-0.5"
              >
                ×
              </button>
            )}
          </span>
        ))}
        {!readOnly && (
          <div className="flex items-center gap-1.5">
            <input
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  add();
                }
              }}
              placeholder={placeholder || "Add glob pattern..."}
              className="bg-transparent text-xs font-mono text-gray-200 outline-none placeholder:text-gray-700 min-w-[140px]"
            />
            <button
              type="button"
              onClick={add}
              className="p-1 rounded-md bg-amber-500/20 hover:bg-amber-500/30 text-amber-400 transition-colors"
            >
              <Plus className="w-3 h-3" />
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

function ExecRuleRow({
  rule,
  index,
  onChange,
  onRemove,
  readOnly,
}: {
  rule: ExecRule;
  index: number;
  onChange: (next: ExecRule) => void;
  onRemove: () => void;
  readOnly: boolean;
}) {
  const [argvDraft, setArgvDraft] = useState(rule.argv_prefix.join(", "));
  const [posDraft, setPosDraft] = useState(rule.validate_path_positions.join(", "));

  const commitArgv = () => {
    const parts = argvDraft
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    onChange({ ...rule, argv_prefix: parts });
  };

  const commitPos = () => {
    const parts = posDraft
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean)
      .map(Number)
      .filter((n) => !isNaN(n));
    onChange({ ...rule, validate_path_positions: parts });
  };

  return (
    <div className="p-3 bg-[#070707] border border-[#1f1f1f] rounded-xl space-y-3 hover:border-amber-500/20 transition-colors group/rule">
      <div className="flex items-center justify-between">
        <span className="text-[10px] font-bold uppercase text-amber-500/60 tracking-wider">
          Rule #{index + 1}
        </span>
        {!readOnly && (
          <button
            type="button"
            onClick={onRemove}
            className="p-1 rounded-md text-gray-600 hover:text-red-400 hover:bg-red-500/10 transition-all opacity-0 group-hover/rule:opacity-100"
          >
            <Trash2 className="w-3.5 h-3.5" />
          </button>
        )}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <div className="space-y-1">
          <label className="text-[10px] font-bold uppercase text-gray-600 tracking-wider">
            Executable
          </label>
          <input
            type="text"
            value={rule.executable}
            onChange={(e) => onChange({ ...rule, executable: e.target.value })}
            readOnly={readOnly}
            placeholder="e.g. python3"
            className={`w-full bg-[#0d0d0d] border rounded-lg px-3 py-2 text-sm font-mono outline-none transition-all ${
              readOnly
                ? "border-[#1a1a1a] text-gray-500"
                : !rule.executable.trim()
                ? "border-red-500/50 text-gray-200 focus:border-red-500 focus:ring-1 focus:ring-red-500/20"
                : "border-[#262626] text-gray-200 focus:border-amber-500/50 focus:ring-1 focus:ring-amber-500/20"
            }`}
          />
          {!readOnly && !rule.executable.trim() && (
            <p className="text-[10px] text-red-500 mt-1">Executable name is required</p>
          )}
        </div>

        <div className="space-y-1">
          <label className="text-[10px] font-bold uppercase text-gray-600 tracking-wider">
            Argv Prefix (CSV)
          </label>
          <input
            type="text"
            value={argvDraft}
            onChange={(e) => setArgvDraft(e.target.value)}
            onBlur={commitArgv}
            readOnly={readOnly}
            placeholder='e.g. -r, -E'
            className={`w-full bg-[#0d0d0d] border rounded-lg px-3 py-2 text-sm font-mono outline-none transition-all ${
              readOnly
                ? "border-[#1a1a1a] text-gray-500"
                : "border-[#262626] text-gray-200 focus:border-amber-500/50 focus:ring-1 focus:ring-amber-500/20"
            }`}
          />
        </div>

        <div className="space-y-1">
          <label className="text-[10px] font-bold uppercase text-gray-600 tracking-wider">
            Validate Path Positions (CSV)
          </label>
          <input
            type="text"
            value={posDraft}
            onChange={(e) => setPosDraft(e.target.value)}
            onBlur={commitPos}
            readOnly={readOnly}
            placeholder="e.g. 1, 2, 3"
            className={`w-full bg-[#0d0d0d] border rounded-lg px-3 py-2 text-sm font-mono outline-none transition-all ${
              readOnly
                ? "border-[#1a1a1a] text-gray-500"
                : "border-[#262626] text-gray-200 focus:border-amber-500/50 focus:ring-1 focus:ring-amber-500/20"
            }`}
          />
        </div>
      </div>
    </div>
  );
}

function ByteInput({
  label,
  value,
  onChange,
  readOnly,
  description,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  readOnly: boolean;
  description?: string;
}) {
  const mb = (value / (1024 * 1024)).toFixed(2);
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between">
        <label className="text-[10px] font-bold uppercase text-gray-500 tracking-wider">
          {label}
        </label>
        <span className="text-[10px] text-gray-600 font-mono">{mb} MB</span>
      </div>
      <input
        type="number"
        value={value}
        onChange={(e) => onChange(parseInt(e.target.value, 10) || 0)}
        readOnly={readOnly}
        className={`w-full bg-[#0d0d0d] border rounded-xl px-4 py-2.5 text-sm font-mono outline-none transition-all ${
          readOnly
            ? "border-[#1a1a1a] text-gray-500"
            : "border-[#262626] text-gray-200 focus:border-amber-500/50 focus:ring-1 focus:ring-amber-500/20"
        }`}
      />
      {description && (
        <p className="text-[10px] text-gray-600">{description}</p>
      )}
    </div>
  );
}

function NumberInput({
  label,
  value,
  onChange,
  readOnly,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  readOnly: boolean;
}) {
  return (
    <div className="space-y-1.5">
      <label className="text-[10px] font-bold uppercase text-gray-500 tracking-wider">
        {label}
      </label>
      <input
        type="number"
        value={value}
        onChange={(e) => onChange(parseInt(e.target.value, 10) || 0)}
        readOnly={readOnly}
        className={`w-full bg-[#0d0d0d] border rounded-xl px-4 py-2.5 text-sm font-mono outline-none transition-all ${
          readOnly
            ? "border-[#1a1a1a] text-gray-500"
            : "border-[#262626] text-gray-200 focus:border-amber-500/50 focus:ring-1 focus:ring-amber-500/20"
        }`}
      />
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

interface PolicyEditorProps {
  value: string;
  onChange: (yaml: string) => void;
  readOnly?: boolean;
}

export function PolicyEditor({ value, onChange, readOnly = false }: PolicyEditorProps) {
  const [state, setState] = useState<FsPolicyState>(DEFAULT_STATE);
  const [parseError, setParseError] = useState<string | null>(null);
  const [showRaw, setShowRaw] = useState(false);

  const [lastSentYaml, setLastSentYaml] = useState<string | null>(null);

  // Track which sections are open
  const [openSections, setOpenSections] = useState({
    general: true,
    filesystem: true,
    exec: true,
    limits: false,
  });

  // Parse incoming YAML → state
  useEffect(() => {
    if (!value) return;
    if (value === lastSentYaml) return;
    const { state: parsed, error } = yamlToPolicy(value);
    setParseError(error);
    setState(parsed);
  }, [value, lastSentYaml]);

  // Serialize state → YAML → propagate
  const update = useCallback(
    (patch: Partial<FsPolicyState> | ((prev: FsPolicyState) => FsPolicyState)) => {
      setState((prev) => {
        const next = typeof patch === "function" ? patch(prev) : { ...prev, ...patch };
        const nextYaml = policyToYaml(next);
        setTimeout(() => {
          setLastSentYaml(nextYaml);
          onChange(nextYaml);
        }, 0);
        return next;
      });
    },
    [onChange]
  );

  const toggleSection = (key: keyof typeof openSections) => {
    setOpenSections((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  const addExecRule = () => {
    update((prev) => ({
      ...prev,
      exec_allowlist: [
        ...prev.exec_allowlist,
        { executable: "", argv_prefix: [], validate_path_positions: [] },
      ],
    }));
  };

  const updateExecRule = (i: number, next: ExecRule) => {
    update((prev) => {
      const list = [...prev.exec_allowlist];
      list[i] = next;
      return { ...prev, exec_allowlist: list };
    });
  };

  const removeExecRule = (i: number) => {
    update((prev) => ({
      ...prev,
      exec_allowlist: prev.exec_allowlist.filter((_, j) => j !== i),
    }));
  };

  const rawPreview = policyToYaml(state);

  return (
    <div className="space-y-1">
      {parseError && (
        <div className="p-3 mb-4 bg-red-500/10 border border-red-500/20 rounded-xl flex items-start gap-2 text-xs text-red-400">
          <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
          <span>
            <strong>Parse error:</strong> {parseError}
            <br />
            Showing defaults. Fix the YAML source or start fresh.
          </span>
        </div>
      )}

      {/* ── General ── */}
      <div className="bg-[#0d0d0d] rounded-2xl border border-[#1a1a1a] overflow-hidden">
        <div className="px-5 pt-2">
          <SectionHeader
            icon={<FileText className="w-4 h-4" />}
            title="General"
            subtitle="Policy Version"
            open={openSections.general}
            onToggle={() => toggleSection("general")}
          />
        </div>
        {openSections.general && (
          <div className="px-5 pb-5 pt-4">
            <div className="space-y-1.5 max-w-xs">
              <label className="text-[10px] font-bold uppercase text-gray-500 tracking-wider">
                Version
              </label>
              <input
                type="text"
                value={state.version}
                onChange={(e) => update({ version: e.target.value })}
                readOnly={readOnly}
                placeholder="1.0"
                className={`w-full bg-[#070707] border rounded-xl px-4 py-2.5 text-sm font-mono outline-none transition-all ${
                  readOnly
                    ? "border-[#1a1a1a] text-gray-500"
                    : "border-[#262626] text-gray-200 focus:border-amber-500/50 focus:ring-1 focus:ring-amber-500/20"
                }`}
              />
            </div>
          </div>
        )}
      </div>

      {/* ── Filesystem ── */}
      <div className="bg-[#0d0d0d] rounded-2xl border border-[#1a1a1a] overflow-hidden">
        <div className="px-5 pt-2">
          <SectionHeader
            icon={<FolderOpen className="w-4 h-4" />}
            title="Filesystem"
            subtitle="Allow & Deny glob patterns"
            open={openSections.filesystem}
            onToggle={() => toggleSection("filesystem")}
          />
        </div>
        {openSections.filesystem && (
          <div className="px-5 pb-5 pt-4 space-y-4">
            <GlobTagList
              label="Allow Paths"
              values={state.filesystem_allow}
              onChange={(v) => update({ filesystem_allow: v })}
              readOnly={readOnly}
              placeholder='e.g. workspace/**'
            />
            <GlobTagList
              label="Deny Paths"
              values={state.filesystem_deny}
              onChange={(v) => update({ filesystem_deny: v })}
              readOnly={readOnly}
              placeholder='e.g. /etc/**'
            />
          </div>
        )}
      </div>

      {/* ── Exec ── */}
      <div className="bg-[#0d0d0d] rounded-2xl border border-[#1a1a1a] overflow-hidden">
        <div className="px-5 pt-2">
          <SectionHeader
            icon={<Terminal className="w-4 h-4" />}
            title="Command Execution"
            subtitle="Sandbox exec policy & allowlist"
            open={openSections.exec}
            onToggle={() => toggleSection("exec")}
          />
        </div>
        {openSections.exec && (
          <div className="px-5 pb-5 pt-4 space-y-5">
            {/* Toggle */}
            <div className="flex items-center justify-between p-4 bg-[#070707] border border-[#1f1f1f] rounded-xl">
              <div>
                <p className="text-sm font-bold text-white">Exec Enabled</p>
                <p className="text-xs text-gray-500 mt-0.5">
                  Allow the agent to execute system commands via the allowlist below.
                </p>
              </div>
              <button
                type="button"
                onClick={() => !readOnly && update({ exec_enabled: !state.exec_enabled })}
                className={`w-12 h-6 rounded-full transition-all flex items-center px-1 ${
                  readOnly
                    ? "cursor-not-allowed opacity-60"
                    : "cursor-pointer"
                } ${state.exec_enabled ? "bg-amber-500" : "bg-gray-700"}`}
              >
                <div
                  className={`w-4 h-4 rounded-full bg-white transition-transform ${
                    state.exec_enabled ? "translate-x-6" : "translate-x-0"
                  }`}
                />
              </button>
            </div>

            {/* Warning if exec disabled */}
            {!state.exec_enabled && (
              <div className="flex items-center gap-2 p-3 bg-yellow-500/5 border border-yellow-500/20 rounded-xl text-xs text-yellow-400">
                <Shield className="w-4 h-4 shrink-0" />
                Exec is OFF — the allowlist below is saved but not active until you enable exec.
              </div>
            )}

            {/* Allowlist */}
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <label className="text-[10px] font-bold uppercase text-gray-500 tracking-wider">
                  Allowlist ({state.exec_allowlist.length} rules)
                </label>
                {!readOnly && (
                  <button
                    type="button"
                    onClick={addExecRule}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-amber-500/10 border border-amber-500/20 text-amber-400 text-xs font-bold hover:bg-amber-500/20 transition-all active:scale-95"
                  >
                    <Plus className="w-3.5 h-3.5" />
                    Add Rule
                  </button>
                )}
              </div>

              {state.exec_allowlist.length === 0 ? (
                <div className="p-6 text-center text-gray-600 text-sm border border-dashed border-[#1f1f1f] rounded-xl">
                  <FolderX className="w-8 h-8 mx-auto mb-2 text-gray-700" />
                  No exec rules defined.
                  {!readOnly && " Click «Add Rule» to add one."}
                </div>
              ) : (
                <div className="space-y-2">
                  {state.exec_allowlist.map((rule, i) => (
                    <ExecRuleRow
                      key={i}
                      rule={rule}
                      index={i}
                      onChange={(next) => updateExecRule(i, next)}
                      onRemove={() => removeExecRule(i)}
                      readOnly={readOnly}
                    />
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {/* ── Limits ── */}
      <div className="bg-[#0d0d0d] rounded-2xl border border-[#1a1a1a] overflow-hidden">
        <div className="px-5 pt-2">
          <SectionHeader
            icon={<Gauge className="w-4 h-4" />}
            title="Resource Limits"
            subtitle="File sizes and operation ceilings"
            open={openSections.limits}
            onToggle={() => toggleSection("limits")}
          />
        </div>
        {openSections.limits && (
          <div className="px-5 pb-5 pt-4 grid grid-cols-1 md:grid-cols-2 gap-4">
            <ByteInput
              label="Max File Read Bytes"
              value={state.limits.max_file_read_bytes}
              onChange={(v) => update((p) => ({ ...p, limits: { ...p.limits, max_file_read_bytes: v } }))}
              readOnly={readOnly}
            />
            <ByteInput
              label="Max File Write Bytes"
              value={state.limits.max_file_write_bytes}
              onChange={(v) => update((p) => ({ ...p, limits: { ...p.limits, max_file_write_bytes: v } }))}
              readOnly={readOnly}
            />
            <ByteInput
              label="Max Edit File Bytes"
              value={state.limits.max_edit_file_bytes}
              onChange={(v) => update((p) => ({ ...p, limits: { ...p.limits, max_edit_file_bytes: v } }))}
              readOnly={readOnly}
            />
            <ByteInput
              label="Grep Max File Bytes"
              value={state.limits.grep_max_file_bytes}
              onChange={(v) => update((p) => ({ ...p, limits: { ...p.limits, grep_max_file_bytes: v } }))}
              readOnly={readOnly}
            />
            <NumberInput
              label="Grep Max Matches"
              value={state.limits.grep_max_matches}
              onChange={(v) => update((p) => ({ ...p, limits: { ...p.limits, grep_max_matches: v } }))}
              readOnly={readOnly}
            />
            <NumberInput
              label="Glob Max Paths"
              value={state.limits.glob_max_paths}
              onChange={(v) => update((p) => ({ ...p, limits: { ...p.limits, glob_max_paths: v } }))}
              readOnly={readOnly}
            />
            <NumberInput
              label="Chunk Max Lines"
              value={state.limits.chunk_max_lines}
              onChange={(v) => update((p) => ({ ...p, limits: { ...p.limits, chunk_max_lines: v } }))}
              readOnly={readOnly}
            />
          </div>
        )}
      </div>

      {/* ── Raw YAML preview ── */}
      <div className="bg-[#0d0d0d] rounded-2xl border border-[#1a1a1a] overflow-hidden">
        <div className="px-5 pt-2">
          <SectionHeader
            icon={<Code className="w-4 h-4" />}
            title="Raw YAML Preview"
            subtitle="Read-only serialized output"
            open={showRaw}
            onToggle={() => setShowRaw((p) => !p)}
          />
        </div>
        {showRaw && (
          <div className="px-5 pb-5 pt-4">
            <pre className="w-full bg-[#030303] border border-[#1a1a1a] rounded-xl p-4 text-xs font-mono text-amber-400/70 leading-relaxed overflow-x-auto whitespace-pre">
              {rawPreview}
            </pre>
          </div>
        )}
      </div>
    </div>
  );
}
