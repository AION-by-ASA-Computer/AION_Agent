"use client";

import { useEffect, useState, useCallback } from "react";
import { load as yamlLoad } from "js-yaml";
import { ChevronDown, Plus, Trash2, TriangleAlert, X } from "lucide-react";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";
import { inputCls, outlineBtn } from "@/components/ui/classes";
import { Switch } from "@/components/settings/ui";

const k = "admin_settings.policy";

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

const fieldCls = (readOnly: boolean, invalid = false) =>
  cn(inputCls, "font-mono text-[13px]", readOnly && "cursor-default border-border/60 text-muted-foreground hover:border-border/60", invalid && "border-destructive/60");

/** Collapsible block of the policy. */
function Block({
  title,
  hint,
  open,
  onToggle,
  children,
}: {
  title: string;
  hint: string;
  open: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}) {
  return (
    <section className="overflow-hidden rounded-2xl border border-border/60 bg-background/40">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="focus-ring flex w-full items-center gap-3 px-4 py-3.5 text-left transition-colors hover:bg-secondary/40"
      >
        <span className="min-w-0 flex-1">
          <span className="block text-sm font-semibold">{title}</span>
          <span className="block text-xs text-muted-foreground">{hint}</span>
        </span>
        <ChevronDown className={cn("h-4 w-4 shrink-0 text-muted-foreground transition-transform duration-200", open && "rotate-180")} aria-hidden />
      </button>
      {open && <div className="border-t border-border/50 px-4 py-4">{children}</div>}
    </section>
  );
}

function GlobTagList({
  label,
  values,
  onChange,
  readOnly,
  placeholder,
  removeLabel,
  addLabel,
}: {
  label: string;
  values: string[];
  onChange: (next: string[]) => void;
  readOnly: boolean;
  placeholder: string;
  removeLabel: string;
  addLabel: string;
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
    <div className="flex flex-col gap-1.5">
      <span className="text-sm font-medium">{label}</span>
      <div className="flex min-h-[46px] flex-wrap items-center gap-1.5 rounded-xl border border-border bg-background p-1.5">
        {values.map((v, i) => (
          <span key={`${v}-${i}`} className="inline-flex items-center gap-1 rounded-lg bg-secondary py-1 pl-2.5 pr-1.5 font-mono text-xs">
            {v}
            {!readOnly && (
              <button
                type="button"
                onClick={() => onChange(values.filter((_, j) => j !== i))}
                aria-label={`${removeLabel} ${v}`}
                className="focus-ring inline-flex h-5 w-5 items-center justify-center rounded text-muted-foreground transition-colors hover:text-destructive"
              >
                <X className="h-3 w-3" aria-hidden />
              </button>
            )}
          </span>
        ))}
        {values.length === 0 && readOnly && <span className="px-2 text-xs text-muted-foreground">—</span>}
        {!readOnly && (
          <span className="flex min-w-[10rem] flex-1 items-center gap-1">
            <input
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  add();
                }
              }}
              placeholder={placeholder}
              aria-label={label}
              className="h-8 min-w-0 flex-1 bg-transparent px-2 font-mono text-xs outline-none placeholder:text-muted-foreground/70"
            />
            <button
              type="button"
              onClick={add}
              disabled={!draft.trim()}
              aria-label={addLabel}
              className="focus-ring inline-flex h-8 w-8 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground disabled:opacity-40"
            >
              <Plus className="h-3.5 w-3.5" aria-hidden />
            </button>
          </span>
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
  const t = useT();
  const [argvDraft, setArgvDraft] = useState(rule.argv_prefix.join(", "));
  const [posDraft, setPosDraft] = useState(rule.validate_path_positions.join(", "));

  const commitArgv = () => {
    onChange({ ...rule, argv_prefix: argvDraft.split(",").map((s) => s.trim()).filter(Boolean) });
  };

  const commitPos = () => {
    onChange({
      ...rule,
      validate_path_positions: posDraft.split(",").map((s) => s.trim()).filter(Boolean).map(Number).filter((n) => !isNaN(n)),
    });
  };

  const missing = !readOnly && !rule.executable.trim();

  return (
    <li className="px-4 py-3.5">
      <div className="mb-2.5 flex items-center justify-between">
        <span className="text-xs font-medium text-muted-foreground">{t(`${k}.rule`, { n: index + 1 })}</span>
        {!readOnly && (
          <button
            type="button"
            onClick={onRemove}
            aria-label={t(`${k}.remove_rule`, { n: index + 1 })}
            className="focus-ring inline-flex h-8 w-8 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-secondary hover:text-destructive"
          >
            <Trash2 className="h-3.5 w-3.5" aria-hidden />
          </button>
        )}
      </div>
      <div className="grid gap-3 md:grid-cols-3">
        <label className="flex flex-col gap-1.5">
          <span className="text-xs font-medium">{t(`${k}.executable`)}</span>
          <input
            type="text"
            value={rule.executable}
            onChange={(e) => onChange({ ...rule, executable: e.target.value })}
            readOnly={readOnly}
            aria-invalid={missing || undefined}
            placeholder="python3"
            className={fieldCls(readOnly, missing)}
          />
          {missing && <span className="text-xs text-destructive">{t(`${k}.executable_required`)}</span>}
        </label>
        <label className="flex flex-col gap-1.5">
          <span className="text-xs font-medium">{t(`${k}.argv`)}</span>
          <input type="text" value={argvDraft} onChange={(e) => setArgvDraft(e.target.value)} onBlur={commitArgv} readOnly={readOnly} placeholder="-r, -E" className={fieldCls(readOnly)} />
        </label>
        <label className="flex flex-col gap-1.5">
          <span className="text-xs font-medium">{t(`${k}.positions`)}</span>
          <input type="text" value={posDraft} onChange={(e) => setPosDraft(e.target.value)} onBlur={commitPos} readOnly={readOnly} placeholder="1, 2, 3" className={fieldCls(readOnly)} />
        </label>
      </div>
    </li>
  );
}

function NumField({ label, value, onChange, readOnly, bytes }: { label: string; value: number; onChange: (v: number) => void; readOnly: boolean; bytes?: boolean }) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="flex items-baseline justify-between gap-2 text-sm font-medium">
        {label}
        {bytes && <span className="font-mono text-xs font-normal tabular-nums text-muted-foreground">{(value / (1024 * 1024)).toFixed(2)} MB</span>}
      </span>
      <input type="number" inputMode="numeric" value={value} onChange={(e) => onChange(parseInt(e.target.value, 10) || 0)} readOnly={readOnly} className={fieldCls(readOnly)} />
    </label>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

interface PolicyEditorProps {
  value: string;
  onChange: (yaml: string) => void;
  readOnly?: boolean;
}

export function PolicyEditor({ value, onChange, readOnly = false }: PolicyEditorProps) {
  const t = useT();
  const [state, setState] = useState<FsPolicyState>(DEFAULT_STATE);
  const [parseError, setParseError] = useState<string | null>(null);
  const [showRaw, setShowRaw] = useState(false);

  const [lastSentYaml, setLastSentYaml] = useState<string | null>(null);

  const [openSections, setOpenSections] = useState({ general: false, filesystem: true, exec: true, limits: false });

  // Parse incoming YAML → state
  useEffect(() => {
    if (!value) return;
    if (value === lastSentYaml) return;
    const { state: parsed, error } = yamlToPolicy(value);
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch on mount
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
      exec_allowlist: [...prev.exec_allowlist, { executable: "", argv_prefix: [], validate_path_positions: [] }],
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
    update((prev) => ({ ...prev, exec_allowlist: prev.exec_allowlist.filter((_, j) => j !== i) }));
  };

  const setLimit = (key: keyof FsPolicyLimits) => (v: number) => update((p) => ({ ...p, limits: { ...p.limits, [key]: v } }));

  const rawPreview = policyToYaml(state);

  return (
    <div className="flex flex-col gap-3">
      {parseError && (
        <div className="flex items-start gap-2.5 rounded-xl bg-secondary/60 px-3.5 py-3 text-sm" role="alert">
          <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0 text-destructive" aria-hidden />
          <p className="text-muted-foreground">
            <strong className="font-medium text-foreground">{t(`${k}.parse_error`)}</strong> {parseError} {t(`${k}.parse_error_hint`)}
          </p>
        </div>
      )}

      <Block title={t(`${k}.fs_title`)} hint={t(`${k}.fs_hint`)} open={openSections.filesystem} onToggle={() => toggleSection("filesystem")}>
        <div className="flex flex-col gap-4">
          <GlobTagList
            label={t(`${k}.allow`)}
            values={state.filesystem_allow}
            onChange={(v) => update({ filesystem_allow: v })}
            readOnly={readOnly}
            placeholder="workspace/**"
            removeLabel={t(`${k}.remove`)}
            addLabel={t(`${k}.add_pattern`)}
          />
          <GlobTagList
            label={t(`${k}.deny`)}
            values={state.filesystem_deny}
            onChange={(v) => update({ filesystem_deny: v })}
            readOnly={readOnly}
            placeholder="/etc/**"
            removeLabel={t(`${k}.remove`)}
            addLabel={t(`${k}.add_pattern`)}
          />
        </div>
      </Block>

      <Block title={t(`${k}.exec_title`)} hint={t(`${k}.exec_hint`)} open={openSections.exec} onToggle={() => toggleSection("exec")}>
        <div className="flex flex-col gap-4">
          <div className="flex items-center gap-4">
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium">{t(`${k}.exec_enabled`)}</p>
              <p className="text-xs text-muted-foreground">{t(`${k}.exec_enabled_hint`)}</p>
            </div>
            <Switch checked={state.exec_enabled} disabled={readOnly} onChange={(v) => update({ exec_enabled: v })} label={t(`${k}.exec_enabled`)} />
          </div>

          {!state.exec_enabled && (
            <div className="flex items-start gap-2.5 rounded-xl bg-secondary/60 px-3.5 py-3 text-sm text-muted-foreground">
              <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0 text-warning" aria-hidden />
              {t(`${k}.exec_off`)}
            </div>
          )}

          <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between gap-3">
              <span className="text-sm font-medium">{t(`${k}.allowlist`, { count: state.exec_allowlist.length })}</span>
              {!readOnly && (
                <button type="button" onClick={addExecRule} className={outlineBtn}>
                  <Plus className="h-3.5 w-3.5" aria-hidden />
                  {t(`${k}.add_rule`)}
                </button>
              )}
            </div>

            {state.exec_allowlist.length === 0 ? (
              <p className="rounded-xl border border-dashed border-border px-4 py-6 text-sm text-muted-foreground">
                {t(`${k}.no_rules`)} {!readOnly && t(`${k}.no_rules_cta`)}
              </p>
            ) : (
              <ul className="divide-y divide-border/40 overflow-hidden rounded-xl border border-border/60">
                {state.exec_allowlist.map((rule, i) => (
                  <ExecRuleRow key={i} rule={rule} index={i} onChange={(next) => updateExecRule(i, next)} onRemove={() => removeExecRule(i)} readOnly={readOnly} />
                ))}
              </ul>
            )}
          </div>
        </div>
      </Block>

      <Block title={t(`${k}.limits_title`)} hint={t(`${k}.limits_hint`)} open={openSections.limits} onToggle={() => toggleSection("limits")}>
        <div className="grid gap-x-5 gap-y-4 md:grid-cols-2">
          <NumField bytes label={t(`${k}.max_read`)} value={state.limits.max_file_read_bytes} onChange={setLimit("max_file_read_bytes")} readOnly={readOnly} />
          <NumField bytes label={t(`${k}.max_write`)} value={state.limits.max_file_write_bytes} onChange={setLimit("max_file_write_bytes")} readOnly={readOnly} />
          <NumField bytes label={t(`${k}.max_edit`)} value={state.limits.max_edit_file_bytes} onChange={setLimit("max_edit_file_bytes")} readOnly={readOnly} />
          <NumField bytes label={t(`${k}.grep_bytes`)} value={state.limits.grep_max_file_bytes} onChange={setLimit("grep_max_file_bytes")} readOnly={readOnly} />
          <NumField label={t(`${k}.grep_matches`)} value={state.limits.grep_max_matches} onChange={setLimit("grep_max_matches")} readOnly={readOnly} />
          <NumField label={t(`${k}.glob_paths`)} value={state.limits.glob_max_paths} onChange={setLimit("glob_max_paths")} readOnly={readOnly} />
          <NumField label={t(`${k}.chunk_lines`)} value={state.limits.chunk_max_lines} onChange={setLimit("chunk_max_lines")} readOnly={readOnly} />
        </div>
      </Block>

      <Block title={t(`${k}.general_title`)} hint={t(`${k}.general_hint`)} open={openSections.general} onToggle={() => toggleSection("general")}>
        <label className="flex max-w-xs flex-col gap-1.5">
          <span className="text-sm font-medium">{t(`${k}.version`)}</span>
          <input type="text" value={state.version} onChange={(e) => update({ version: e.target.value })} readOnly={readOnly} placeholder="1.0" className={fieldCls(readOnly)} />
        </label>
      </Block>

      <Block title={t(`${k}.raw_title`)} hint={t(`${k}.raw_hint`)} open={showRaw} onToggle={() => setShowRaw((p) => !p)}>
        <pre className="overflow-x-auto whitespace-pre rounded-xl border border-border/60 bg-background p-4 font-mono text-xs leading-relaxed text-muted-foreground">{rawPreview}</pre>
      </Block>
    </div>
  );
}
