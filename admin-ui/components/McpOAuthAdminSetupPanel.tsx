"use client";

import { useState } from "react";
import { AlertTriangle, BookOpen, Check, Copy, ExternalLink, KeyRound, Users } from "lucide-react";

import {
  connectorOAuthSetupHints,
  defaultOAuthRedirectUri,
} from "@/lib/mcpOAuthSetup";

export type McpOauthConfigState = {
  provider: string;
  authorization_server: string;
  token_url: string;
  client_id: string;
  client_secret: string;
  scopes: string[];
  client_id_source?: string;
};

type Props = {
  connector: Record<string, unknown> | null | undefined;
  oauthConfig: McpOauthConfigState;
  onChange: (patch: Partial<McpOauthConfigState>) => void;
  showUserManagedNote?: boolean;
};

export function McpOAuthAdminSetupPanel({
  connector,
  oauthConfig,
  onChange,
  showUserManagedNote = true,
}: Props) {
  const hints = connectorOAuthSetupHints(connector);
  const redirectUri = defaultOAuthRedirectUri();
  const [copied, setCopied] = useState(false);

  if (!hints.usesOAuth && !oauthConfig.authorization_server && !oauthConfig.client_id) {
    return null;
  }

  async function copyRedirectUri() {
    try {
      await navigator.clipboard.writeText(redirectUri);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      /* ignore */
    }
  }

  const scopeList =
    oauthConfig.scopes.length > 0 ? oauthConfig.scopes : hints.scopes;

  return (
    <div className="mt-3 space-y-3">
      {hints.needsAdminCredentials ? (
        <div className="flex items-start gap-3 rounded-xl border border-amber-500/30 bg-amber-500/[0.08] p-4">
          <KeyRound className="mt-0.5 h-4 w-4 shrink-0 text-amber-300" />
          <div className="min-w-0 space-y-2">
            <div className="text-[10px] font-bold uppercase tracking-wider text-amber-200/90">
              OAuth app required — admin setup
            </div>
            <p className="text-[11px] leading-relaxed text-gray-300">
              <span className="font-semibold text-white">{hints.title}</span> does not support
              automatic client registration. Register an OAuth application with the provider,
              then paste <span className="font-semibold text-white">Client ID</span> and{" "}
              <span className="font-semibold text-white">Client secret</span> below before users
              can connect in chat-ui → My Integrations.
            </p>
            {hints.adminHint ? (
              <p className="mt-2 text-[11px] leading-relaxed text-amber-100/85">{hints.adminHint}</p>
            ) : null}
            <div className="mt-3 rounded-lg border border-white/10 bg-black/35 p-2.5">
              <div className="text-[9px] font-bold uppercase tracking-wider text-gray-500">
                Authorization callback URL (redirect URI)
              </div>
              <div className="mt-1 flex flex-wrap items-center gap-2">
                <code className="break-all text-[10px] text-emerald-300">{redirectUri}</code>
                <button
                  type="button"
                  onClick={() => void copyRedirectUri()}
                  className="inline-flex shrink-0 items-center gap-1 rounded-md border border-white/15 bg-white/5 px-2 py-1 text-[10px] font-semibold text-gray-200 hover:bg-white/10"
                >
                  {copied ? <Check className="h-3 w-3 text-emerald-400" /> : <Copy className="h-3 w-3" />}
                  {copied ? "Copied" : "Copy"}
                </button>
              </div>
            </div>
            {hints.docUrl ? (
              <a
                href={hints.docUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="mt-3 inline-flex items-center gap-1.5 text-[11px] font-semibold text-amber-200 hover:text-white"
              >
                <BookOpen className="h-3.5 w-3.5" />
                Provider setup guide
                <ExternalLink className="h-3 w-3 opacity-70" />
              </a>
            ) : null}
          </div>
        </div>
      ) : showUserManagedNote ? (
        <div className="flex items-start gap-3 rounded-xl border border-blue-500/20 bg-blue-500/[0.06] p-4">
          <Users className="mt-0.5 h-4 w-4 shrink-0 text-blue-300" />
          <div>
            <div className="mb-1 text-[10px] font-bold uppercase tracking-wider text-blue-300">
              OAuth — user-managed
            </div>
            <p className="text-[11px] leading-relaxed text-gray-400">
              This remote MCP server supports standard OAuth discovery (often with dynamic client
              registration). Users authenticate in chat-ui →{" "}
              <span className="font-semibold text-white">My Integrations</span>. Keep policy{" "}
              <span className="font-mono text-indigo-300">per_user</span>.
            </p>
            {oauthConfig.client_id_source === "dynamic_registration" && oauthConfig.client_id ? (
              <p className="mt-2 text-[10px] font-medium text-amber-300/90">
                Client ID obtained via dynamic registration (RFC 7591).
              </p>
            ) : null}
            {hints.docUrl ? (
              <a
                href={hints.docUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="mt-2 inline-flex items-center gap-1 text-[10px] text-blue-300 hover:text-white"
              >
                Documentation <ExternalLink className="h-3 w-3" />
              </a>
            ) : null}
          </div>
        </div>
      ) : null}

      {hints.needsAdminCredentials ? (
        <div className="space-y-3 rounded-xl border border-white/10 bg-black/25 p-4">
          <div className="text-[10px] font-bold uppercase tracking-wider text-gray-400">
            OAuth credentials (organization)
          </div>
          <label className="block space-y-1">
            <span className="text-xs font-semibold text-gray-300">Client ID</span>
            <input
              type="text"
              autoComplete="off"
              value={oauthConfig.client_id}
              onChange={(e) => onChange({ client_id: e.target.value })}
              placeholder="From provider developer console"
              className="w-full rounded-xl border border-white/10 bg-black/50 p-3 text-sm text-white outline-none focus:border-amber-500/70"
            />
          </label>
          <label className="block space-y-1">
            <span className="text-xs font-semibold text-gray-300">Client secret</span>
            <input
              type="password"
              autoComplete="new-password"
              value={oauthConfig.client_secret}
              onChange={(e) => onChange({ client_secret: e.target.value })}
              placeholder="Keep empty to leave unchanged on save"
              className="w-full rounded-xl border border-white/10 bg-black/50 p-3 text-sm text-white outline-none focus:border-amber-500/70"
            />
          </label>
          {scopeList.length > 0 ? (
            <div className="text-[10px] text-gray-500">
              <span className="font-bold uppercase tracking-wider text-gray-400">Scopes</span>
              <p className="mt-1 font-mono text-[10px] leading-relaxed text-gray-400">
                {scopeList.join(" ")}
              </p>
            </div>
          ) : null}
          {!oauthConfig.client_id ? (
            <p className="flex items-start gap-1.5 text-[10px] text-amber-300/90">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              Users will see an error until Client ID is saved here.
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
