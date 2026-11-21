"use client";

/**
 * Network allowlist of a custom MCP server, edited in the Configure dialog (MCP Hub).
 *
 * Closed by default: the server reaches only the destinations listed here (host
 * names, IPs or subnets, optional ports, one per line, e.g.
 * `as400.azienda.local:446,8470-8476`); everything else, AION included, is
 * blocked. An empty list means no network at all. The developers declare the
 * initial list in aion-mcp.yaml (`network:`); the admin's edit wins and survives
 * new uploads, and when a newer manifest asks for different destinations the
 * dialog says so and offers to adopt them.
 *
 * Saved immediately (`PUT /admin/mcp-custom/servers/{slug}/network`, validated by
 * src/mcp_custom/egress.py): the server's workers restart and the change is audited.
 */

import { useState } from "react";
import { Loader2, Network, TriangleAlert } from "lucide-react";
import { apiBase } from "@/lib/api";
import { apiFetch } from "@/lib/api/headers";
import { outlineBtn } from "@/components/ui/classes";
import { useT } from "@/lib/i18n/use-t";

/** Lines of the textarea -> list of non-empty, trimmed entries. */
const toEntries = (text: string) =>
  text
    .split(/\r?\n/)
    .map((s) => s.trim())
    .filter(Boolean);

const sameList = (a: string[], b: string[]) => a.length === b.length && a.every((x, i) => x === b[i]);

export function CustomMcpNetworkPicker({
  slug,
  value,
  manifest,
  onSaved,
}: {
  slug: string;
  /** Allowlist in force (empty = no network). */
  value: string[];
  /** Allowlist requested by the manifest of the active version. */
  manifest: string[];
  onSaved: (entries: string[]) => void;
}) {
  const t = useT();
  const k = "admin_hub.config";
  const [text, setText] = useState(value.join("\n"));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const entries = toEntries(text);
  const dirty = !sameList(entries, value);
  const manifestDiffers = !sameList(manifest, value);

  const save = async (next: string[]) => {
    setSaving(true);
    setError(null);
    try {
      const res = await apiFetch(`${apiBase()}/admin/mcp-custom/servers/${encodeURIComponent(slug)}/network`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ allow: next }),
      });
      const body = await res.json().catch(() => null);
      if (!res.ok) throw new Error(body?.detail?.message || `HTTP ${res.status}`);
      // The backend returns the normalized list (canonical form, no duplicates).
      const saved: string[] = Array.isArray(body?.network) ? body.network : next;
      setText(saved.join("\n"));
      onSaved(saved);
    } catch (err: unknown) {
      setError(t(`${k}.custom_network_error`, { error: err instanceof Error ? err.message : String(err) }));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex flex-col gap-2">
      <span className="flex items-center gap-2 text-sm font-medium">
        <Network className="h-4 w-4 text-muted-foreground" aria-hidden />
        {t(`${k}.custom_network`)}
      </span>
      <p className="text-xs text-muted-foreground">{t(`${k}.custom_network_hint`)}</p>
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={Math.min(8, Math.max(3, entries.length + 1))}
        spellCheck={false}
        placeholder={t(`${k}.custom_network_placeholder`)}
        aria-label={t(`${k}.custom_network`)}
        className="focus-ring w-full rounded-xl border border-border bg-background px-3 py-2 font-mono text-xs"
      />
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" className={outlineBtn} disabled={!dirty || saving} onClick={() => void save(entries)}>
          {saving && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />}
          {t(`${k}.custom_network_save`)}
        </button>
        <span className="text-xs text-muted-foreground">
          {value.length === 0 ? t(`${k}.custom_network_closed`) : t(`${k}.custom_network_count`, { count: value.length })}
        </span>
      </div>
      {manifestDiffers && (
        <div className="flex flex-col gap-1.5 rounded-xl border border-border bg-background/60 p-3 text-xs">
          <p className="flex items-start gap-2 text-warning">
            <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
            {t(`${k}.custom_network_manifest_differs`)}
          </p>
          <code className="whitespace-pre-wrap break-all font-mono text-muted-foreground">
            {manifest.length ? manifest.join("\n") : t(`${k}.custom_network_closed`)}
          </code>
          <button type="button" className={`${outlineBtn} self-start`} disabled={saving} onClick={() => void save(manifest)}>
            {t(`${k}.custom_network_use_manifest`)}
          </button>
        </div>
      )}
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  );
}
