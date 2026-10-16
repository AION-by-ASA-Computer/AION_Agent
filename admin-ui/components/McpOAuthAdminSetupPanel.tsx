"use client";

import { useState } from "react";
import { AlertTriangle, BookOpen, Check, Copy, ExternalLink, KeyRound, Users } from "lucide-react";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";
import { ghostBtn, inputCls } from "@/components/ui/classes";
import { connectorOAuthSetupHints, defaultOAuthRedirectUri } from "@/lib/mcpOAuthSetup";

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

const linkCls = "focus-ring inline-flex items-center gap-1.5 rounded-md text-sm font-medium underline-offset-2 hover:underline";

export function McpOAuthAdminSetupPanel({ connector, oauthConfig, onChange, showUserManagedNote = true }: Props) {
  const t = useT();
  const k = "admin_hub.editors.oauth";
  const hints = connectorOAuthSetupHints(connector);
  const redirectUri = defaultOAuthRedirectUri();
  const [copied, setCopied] = useState(false);

  if (!hints.usesOAuth && !oauthConfig.authorization_server && !oauthConfig.client_id) return null;

  async function copyRedirectUri() {
    try {
      await navigator.clipboard.writeText(redirectUri);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      /* ignore */
    }
  }

  const scopeList = oauthConfig.scopes.length > 0 ? oauthConfig.scopes : hints.scopes;

  return (
    <div className="flex flex-col gap-3">
      {hints.needsAdminCredentials ? (
        <div className="flex items-start gap-3 rounded-2xl bg-warning/12 p-4">
          <KeyRound className="mt-0.5 h-4 w-4 shrink-0 text-warning" aria-hidden />
          <div className="min-w-0 flex-1">
            <h3 className="text-sm font-semibold">{t(`${k}.required_title`)}</h3>
            <p className="mt-1 text-sm leading-relaxed text-muted-foreground">{t(`${k}.required_body`, { name: hints.title })}</p>
            {hints.adminHint ? <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{hints.adminHint}</p> : null}
            <div className="mt-3 rounded-xl bg-background/70 p-3">
              <div className="text-xs font-medium text-muted-foreground">{t(`${k}.callback`)}</div>
              <div className="mt-1.5 flex flex-wrap items-center gap-2">
                <code className="min-w-0 break-all font-mono text-xs">{redirectUri}</code>
                <button type="button" onClick={() => void copyRedirectUri()} className={cn(ghostBtn, "h-8 shrink-0 px-2.5 text-xs")}>
                  {copied ? <Check className="h-3.5 w-3.5" aria-hidden /> : <Copy className="h-3.5 w-3.5" aria-hidden />}
                  <span role="status">{copied ? t(`${k}.copied`) : t(`${k}.copy`)}</span>
                </button>
              </div>
            </div>
            {hints.docUrl ? (
              <a href={hints.docUrl} target="_blank" rel="noopener noreferrer" className={cn(linkCls, "mt-3")}>
                <BookOpen className="h-3.5 w-3.5" aria-hidden />
                {t(`${k}.guide`)}
                <ExternalLink className="h-3 w-3 opacity-70" aria-hidden />
              </a>
            ) : null}
          </div>
        </div>
      ) : showUserManagedNote ? (
        <div className="flex items-start gap-3 rounded-2xl bg-secondary/60 p-4">
          <Users className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
          <div className="min-w-0">
            <h3 className="text-sm font-semibold">{t(`${k}.managed_title`)}</h3>
            <p className="mt-1 text-sm leading-relaxed text-muted-foreground">{t(`${k}.managed_body`)}</p>
            {oauthConfig.client_id_source === "dynamic_registration" && oauthConfig.client_id ? (
              <p className="mt-2 text-xs text-muted-foreground">{t(`${k}.dynamic_note`)}</p>
            ) : null}
            {hints.docUrl ? (
              <a href={hints.docUrl} target="_blank" rel="noopener noreferrer" className={cn(linkCls, "mt-2")}>
                {t(`${k}.docs`)}
                <ExternalLink className="h-3 w-3 opacity-70" aria-hidden />
              </a>
            ) : null}
          </div>
        </div>
      ) : null}

      {hints.needsAdminCredentials ? (
        <section className="flex flex-col gap-3 rounded-2xl border border-border/70 p-4">
          <h3 className="text-sm font-semibold">{t(`${k}.creds_title`)}</h3>
          <label className="block">
            <span className="mb-1.5 block text-xs font-medium text-muted-foreground">{t(`${k}.client_id`)}</span>
            <input
              type="text"
              autoComplete="off"
              value={oauthConfig.client_id}
              onChange={(e) => onChange({ client_id: e.target.value })}
              placeholder={t(`${k}.client_id_ph`)}
              className={inputCls}
            />
          </label>
          <label className="block">
            <span className="mb-1.5 block text-xs font-medium text-muted-foreground">{t(`${k}.client_secret`)}</span>
            <input
              type="password"
              autoComplete="new-password"
              value={oauthConfig.client_secret}
              onChange={(e) => onChange({ client_secret: e.target.value })}
              placeholder={t(`${k}.client_secret_ph`)}
              className={inputCls}
            />
          </label>
          {scopeList.length > 0 ? (
            <div>
              <div className="text-xs font-medium text-muted-foreground">{t(`${k}.scopes`)}</div>
              <p className="mt-1 break-words font-mono text-xs leading-relaxed">{scopeList.join(" ")}</p>
            </div>
          ) : null}
          {!oauthConfig.client_id ? (
            <p className="flex items-start gap-2 text-sm text-warning">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
              {t(`${k}.missing_id`)}
            </p>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}
