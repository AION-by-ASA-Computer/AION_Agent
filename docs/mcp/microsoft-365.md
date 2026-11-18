---
sidebar_position: 5
title: Microsoft 365 (Softeria)
description: Microsoft Graph connector for mail, calendar, files and tasks, using your own Entra app and a per-user sign-in token.
---

# Microsoft 365 (Softeria)

The `ms365` connector lets the AION agent read each user's Outlook mail and calendar, OneDrive
files, contacts and Microsoft To Do tasks. Every user signs in with their own Microsoft account,
so the agent only sees that person's data. This page is mainly for **administrators** (steps 1-2:
register an app in Microsoft Entra and install the connector); **end users** only need
[step 3](#3-connect-your-account-end-user), a single sign-in from chat-ui.

:::note What it is under the hood
The connector starts [`@softeria/ms-365-mcp-server`](https://github.com/softeria/ms-365-mcp-server)
as a stdio process (`npx`) and talks to Microsoft Graph. It is an MCP server (Model Context
Protocol, the standard AION uses to plug tools and connectors into the agent).
:::

It is a different product from the **Microsoft SharePoint** and **Microsoft OneDrive** connectors
already in the catalog. Those are remote Agent 365 endpoints (`agent365.svc.cloud.microsoft`) and
stay as they are. `ms365` is the Softeria server, running locally next to the AION backend.

## Setup in short

| Who | What | Where |
|-----|------|-------|
| Admin | Register an Entra app, copy client ID and secret | Microsoft Entra admin center |
| Admin | Install **Microsoft 365**, paste client ID and secret, add `ms365` to profiles | admin-ui → MCP Hub |
| User | Click **Sign in** on Microsoft 365, then start a new chat | chat-ui → integrations |

## Why you need your own Entra app

On its own, the Softeria server signs in with a **device code** and stores the tokens in the
operating-system keychain of the process. In AION that process is shared by every user of the
backend: a sign-in from the terminal would link a single Microsoft account to the whole instance.

So AION does not use that sign-in. AION itself obtains a Graph token **per user** (the same OAuth
flow used in chat) and passes it to the process in the `MS365_MCP_OAUTH_TOKEN` variable (the
server's BYOT, "bring your own token", method). AION also handles the refresh, because the server
does not renew a token it received ready-made.

The app published by Softeria does not have AION's redirect URI. You must register your own Entra
app and paste its client ID and client secret into the MCP Hub. Without those two values, the
**Sign in** button in chat cannot complete the login.

## What is already set up

Installing from the catalog (`id: ms365`) registers this launch command:

```text
npx -y @softeria/ms-365-mcp-server --org-mode --read-only --preset mail,calendar,files,tasks
```

- **Read-only.** Sending mail, creating events or changing files is disabled until you remove
  `--read-only` (see below).
- **`--org-mode`.** Without this flag the server only exposes tools for personal accounts. With it,
  work/school tools are available too (Teams and SharePoint are not in the default preset).
- **Presets** `mail`, `calendar`, `files`, `tasks`. The server has hundreds of tools: the preset
  keeps the agent's context focused on mail, calendar, files and tasks.
- **Token.** The registry env is `MS365_MCP_OAUTH_TOKEN=${AION_USER_MS365__OAUTH_TOKEN}`. The
  installed slug must stay `ms365`, otherwise the placeholder cannot find the credential.
- **Graph scopes** already in the catalog: `offline_access`, `openid`, `profile`, `User.Read`,
  `Mail.Read`, `Calendars.Read`, `Contacts.Read`, `Files.Read`, `Tasks.Read`.
- **Tenant `common`.** Works for many work accounts. Personal accounts have an exception, described
  below.

The Docker backend includes Node.js. In local development (`uvicorn` on your machine) you need
Node.js 20 or later, because the server starts with `npx`.

## 1. Register the app in Entra (admin)

1. Open the [Microsoft Entra admin center](https://entra.microsoft.com) → **Identity** →
   **Applications** → **App registrations** → **New registration**.
2. Name, for example `AION Microsoft 365`.
3. **Supported account types**, matching the tenant you will use in the OAuth URLs:
   - tenant `common`: *Accounts in any organizational directory and personal Microsoft accounts*;
   - tenant `consumers`: personal Microsoft accounts only;
   - a directory GUID: *Accounts in this organizational directory only*.
4. **Redirect URI**: platform **Web** (not "Mobile and desktop"). The URI must match the one AION
   sends at sign-in:

   | Where AION runs | Redirect URI |
   | --- | --- |
   | Local API, port 8001 | `http://localhost:8001/v1/integrations/oauth/callback` |
   | Docker with Caddy (`https://DOMAIN`) | `https://DOMAIN/api/v1/integrations/oauth/callback` |

   Caddy strips the `/api` prefix before forwarding to the backend. The public redirect keeps
   `/api`; the internal path is `/v1/integrations/oauth/callback`.

5. **Certificates & secrets** → **New client secret**. Copy the value right away: the portal will
   not show it again.
6. **API permissions** → **Add a permission** → **Microsoft Graph** → **Delegated** (not
   Application). Add the same scopes as the catalog: `offline_access`, `openid`, `profile`,
   `User.Read`, `Mail.Read`, `Calendars.Read`, `Contacts.Read`, `Files.Read`, `Tasks.Read`.
7. On a work tenant, click **Grant admin consent**. If the tenant blocks user consent, sign-in fails
   for everyone without this step.
8. From the **Overview** page, copy the **Application (client) ID**. The **Directory (tenant) ID**
   is only needed if you move away from `common`.

:::warning
Do not commit the secret. It lives only in the MCP server's OAuth configuration, in the database.
:::

## 2. Install the connector (admin)

In **Admin → MCP Hub**, in the list of recommended connectors, install **Microsoft 365**
(`POST /admin/mcp/install-from-catalog?connector_id=ms365`).

Then, in that server's OAuth configuration:

- **Client ID**: the Application (client) ID of the Entra app.
- **Client secret**: the secret you just created.

The endpoints are already set to `https://login.microsoftonline.com/common/oauth2/v2.0/authorize`
and `.../token`. Change them only if you change tenant (see
[Personal accounts](#personal-accounts-and-the-consumers-tenant)).

Add `ms365` to the profiles that should use it (`mcp_servers` in the profile YAML, or the profiles
UI).

## 3. Connect your account (end user)

Each person opens **chat-ui → integrations** and chooses **Sign in** on Microsoft 365. The token
stays on that person's own credential row, not in a shared file.

The MCP session is cached: after connecting for the first time, **start a new chat** so the process
starts with the token.

## Personal accounts and the `consumers` tenant

Since June 2026, refresh tokens issued on the `common` authority for personal accounts
(`@outlook.com`, `@hotmail.com`, `@live.com`) are rejected at the first renewal. The session dies
after about an hour.

For those accounts:

1. In the Entra app, set supported accounts to personal only, if you do not also need work accounts.
2. In the Hub, replace `common` with `consumers` in the authorization endpoint and token URL.
3. In the server registry (`config/mcp_registry.local.yaml`, entry `ms365`), set
   `MS365_MCP_TENANT_ID: "consumers"`.

For a single company, use the directory GUID instead of `common` in the same three places, and
restrict the app to that tenant.

## Write access, Teams, other presets

The default is deliberately narrow. To widen it, change the args in the registry and, if you add
permissions, the OAuth scopes in the Hub as well. Users must click **Sign in** again after a scope
change.

| Goal | Args to add or remove | Extra delegated Graph scopes |
| --- | --- | --- |
| Send and edit mail, events, files, tasks | remove `--read-only` | `Mail.ReadWrite`, `Mail.Send`, `Calendars.ReadWrite`, `Files.ReadWrite`, `Tasks.ReadWrite` |
| Outlook only (no files) | `--preset outlook` instead of the list | remove `Files.Read` and `Tasks.Read` if not needed |
| Teams, read-only | keep `--org-mode`, preset `teams` | `Chat.Read`, `ChannelMessage.Read.All`, `Team.ReadBasic.All`, `Channel.ReadBasic.All` |
| Fewer tokens in the context | add `--discovery` | none |

The exact preset names are the server's: `mail`, `calendar`, `files`, `personal`, `work`, `excel`,
`contacts`, `tasks`, `onenote`, `search`, `users`, `outlook`, `onedrive`, `teams`, `teams-write`,
`all`. For the current list: `npx -y @softeria/ms-365-mcp-server --list-presets`.

`--read-only` and the preset do not replace Entra permissions. A write tool with a read-only token
fails on Graph even if you remove the flag.

## What not to configure

- **`npx @softeria/ms-365-mcp-server --login`** on the AION server. It writes the token into the
  system user's keychain, visible to every chat.
- The server's **`login` / `verify-login` tools** as a substitute for the **Sign in** button. Same
  shared store.
- Softeria's **`--http` mode** behind Caddy, unless it is a separate deployment. AION already talks
  to the process over stdio and must not expose the server's port 3000.
- The `MS365_MCP_CLIENT_ID` and `MS365_MCP_CLIENT_SECRET` variables in the process. With the token
  passed by AION, the process does not do its own sign-in. Client ID and secret belong in the Hub's
  OAuth configuration.

## Verify

1. In the Hub, run **Test** on the `ms365` server as the same user who clicked **Sign in** in chat.
   The probe uses that token; an admin who has not connected Microsoft gets an authentication
   error, not a fake token.
2. In a chat with a profile that includes `ms365`, ask for recent mail or today's events. The first
   start downloads the npm package and can take a few seconds.
3. If Graph answers `Insufficient privileges` or `403`, the scope is not in the token: add it to the
   app and to the Hub, then sign in again.
4. If the redirect is rejected (`AADSTS50011`), the URI in the portal is not identical to the one in
   the table above, including `http`/`https` and the `/api` prefix.
