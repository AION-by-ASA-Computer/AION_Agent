---
title: Windows file shares (SMB)
sidebar_position: 7
description: The smb_files connector lets the agent read and write files on company Windows file servers using each user's own Windows credentials, so NTFS permissions always apply. Covers admin setup, user setup, multiple servers and credential sets, networking, account-lockout protection and security.
---

# Windows file shares (SMB)

The **`smb_files`** connector lets the AION agent find, read and save files on your company's
Windows file servers (SMB shares on the local network), just like you would in File Explorer.
It always works **with your own Windows username and password**, so it can only see and change
what you are already allowed to see and change. This page is for **administrators** (who connect
the file servers once) and **end users** (who enter their Windows credentials); the later sections
cover networking, security and internals for IT and developers.

:::note Terms used on this page
- **SMB** (Server Message Block): the protocol Windows uses for shared network folders (`\\server\share`).
- **MCP** (Model Context Protocol): the standard AION uses to plug tools and connectors into the agent. `smb_files` is an MCP server.
- **NTFS ACLs**: the file and folder permissions set on the Windows server.
- **AD** (Active Directory): the Windows domain that manages company accounts.
:::

## At a glance

| Who | What they do | Where | How often |
|-----|--------------|-------|-----------|
| Admin | Adds the file servers (alias, host, allowed shares, credential set) and the limits; enables the connector | admin-ui → Settings → **File server** + **MCP Hub** | Once (and for each new server) |
| User | Enters `DOMAIN\user` and Windows password, one pair per domain/credential set | chat-ui → **My integrations** | Once (and after every password change) |
| User | Asks the agent to search, read or save files | chat | Any time |

The servers can be **several**, even in **different domains**. Because each user connects with
their own account, the file server applies that user's **NTFS ACLs** and its audit log shows the
real person, not a shared service account.

## Why it works this way

- **Per-user credentials, not a service account.** A single account with access to everything
  would bypass NTFS ACLs and make the audit log useless: the agent would show anyone's files to
  whoever asked. With the user's own credentials, the agent can never do more than the user can
  already do in File Explorer.
- **The admin decides servers and shares.** Users do not choose what to connect to: the agent
  only reaches configured servers, and only the allowlisted shares on each. This limits the damage
  of a prompt injection (a file saying "read `\\otherserver\...`") and blocks access to system
  shares (`C$`, `ADMIN$`, `IPC$`). The list is a **ceiling**, not an assignment: the admin lists
  every share AION may use, and each user only works on the ones Windows lets them open.
- **Every server for everyone who has the connector, filtered by ACLs.** There is no per-user or
  per-group allowlist in AION: whoever has `smb_files` sees all enabled servers, and the file
  server decides what they can read or write. There is one source of truth for permissions (AD).
  `smb_list_shares` opens each share with the user's credentials and **hides the denied ones**
  (`omitted` reports how many): different users see different shares, with no per-user setup in AION.
- **Personal folders.** A share can have a **personal folder** (e.g. `{user}` or `Users/{user}`).
  `{user}` is replaced with the user's Windows account name (the part after `DOMAIN\` or before
  `@`). The path offered to the agent is already the user's own folder, and any path outside it is
  rejected (`outside_personal_folder`), even if a wrong ACL would allow it. Hidden non-system
  shares (`home$`, `users$`) are allowed precisely for this use.
- **No delete.** SMB has no recycle bin, so an agent mistake would be irreversible. The connector
  therefore only offers read, create, explicit update and rename.

## Admin setup

### 1. Requirements

In the backend `.env`: `AION_MCP_USER_CREDENTIALS=1` and `AION_CREDENTIAL_ENCRYPTION_KEY`
(see [credential store](user-isolation-and-credentials.md)).
`smbprotocol` is already in `requirements.txt`; no Docker image changes are needed.

### 2. Configure the file servers (admin-ui)

**Settings → File server** has two parts, each saved separately.

**General** (`PUT /admin/smb`): the connector switch and limits shared by all servers.

| Field | Meaning |
|-------|---------|
| Enabled | Connector on/off switch; mirrored on the `smb_files` entry in the MCP Hub |
| Read / write limits (MB) | Maximum size per file (default 25 MB, max 500) |
| Local block duration (minutes) | See [Account-lockout protection](#protezione-dal-blocco-account) (default 30, min 5) |

**Servers** (`POST /admin/smb/servers`, `PUT`/`DELETE /admin/smb/servers/{id}`): one card per
file server, added with **Add server**.

| Field | Meaning |
|-------|---------|
| Alias | Path prefix (`fs01/Share/...`), unique within the tenant |
| Label | Human-readable name shown to the agent (optional) |
| Host / Port | DNS name or IP of the file server (host only, no `\\` or `/`), unique within the tenant, and SMB port (default 445) |
| Default domain | Used when the user types only `mario.rossi`; ignored with `user@domain` or `DOMAIN\user` |
| Credential set | `DEFAULT` or a name (e.g. `ESTERO`) for servers in another domain; same domain → same set |
| Shares | Allowlist of share names, each with a label, an optional **personal folder** (`{user}`) and a **read-only** switch |
| Authentication protocol | `ntlm` (default) or `negotiate` (groundwork for Kerberos, see below) |
| Require SMB3 encryption | Rejects servers that do not encrypt traffic |
| Enabled | A disabled server stays as a draft (even without shares) and the agent does not see it |

Saving validates the data and rejects:

- system shares (`C$`…`Z$`, `ADMIN$`, `IPC$`, `PRINT$`, `FAX$`; other hidden shares such as `home$` are allowed);
- share names with sub-paths (a per-user subfolder belongs in the personal folder field);
- personal folders with `..`, invalid characters or placeholders other than `{user}` (`invalid_share_folder`);
- duplicate shares (share names are case-insensitive);
- an alias or host already used by another server (409);
- an enabled server with no shares.

While the connector is enabled, at least one enabled server must have shares **and** use the
`DEFAULT` set. Changes that would break this rule (removing, disabling or moving the last
`DEFAULT` server to another set) return 409 `default_credential_set_required`. Removing a server
deletes only its configuration, never files. Every operation is recorded in the audit log
(`smb.update`, `smb.server.create`, `smb.server.update`, `smb.server.delete`, `smb.server.test`).

**Test connection** on each card (`POST /admin/smb/servers/{id}/test`) checks only that card's
server and saves the result on it:

- without credentials: TCP connection + SMB negotiation, checking host, port and dialect;
- with a username and password entered for that test: also logon and access to **each** share,
  with a result per share. Test credentials live only in the request: they are not saved, logged
  or written to the audit log (only `with_credentials` is).

:::warning
A failed test logon counts towards AD account lockout. Use a test account.
:::

The test also works on a disabled server or connector, so you can check a server before turning it
on; it only needs a host and at least one share.

**Migration from the single-server version**: revision `f3a4b5c034` moves any existing
configuration into a server whose alias comes from the host name (first DNS label, e.g.
`fs01.corp.local` → `fs01`) with set `DEFAULT`. Paths used by the agent become `fs01/Share/...`;
credentials already saved by users stay valid.

### 3. Enable the connector

`smb_files` is **not** in the default profiles. In the **MCP Hub**, enable it for users and add it
to `mcp_servers:` in the profiles that should use it (e.g. `generic_assistant`).

## User setup

In chat-ui → **My integrations → Windows file server (SMB)**, enter:

- **Windows user**: `DOMAIN\mario.rossi`, `mario.rossi@company.com`, or just `mario.rossi` if the
  admin has set a default domain. The `@` form (UPN, the company "email" you use to sign in to
  Windows) is passed as-is to the file server, which resolves it itself: you do not need to know
  the short domain name. On a PC outside the domain, a Microsoft account email also works, with its
  password (not the PIN).
- **Windows password**: a **write-only** field. After saving, only `****` is shown and there is no
  way to read it back (the "eye" icon is hidden for these fields).
- If the admin has configured servers in other domains, one **Windows user/password (`<SET>`)** pair
  for each credential set, listing the servers it is for. These are optional: fill them in only for
  the domains where you have an account.

:::danger Never type your password in the chat
Chat text ends up in history, memory and logs. If you ask for a file before setting up
credentials, the agent replies with `credentials_missing` and points you to this page.
:::

When you change your password in Windows, update it here too. Saving restarts your MCP workers
(`restart_workers_for_user`), so the new password takes effect immediately.

## Tools available to the agent

| Tool | Type | What it does |
|------|------|--------------|
| `smb_list_shares` | read | Configured servers with their allowed shares, the prefix to use in paths and which are read-only |
| `smb_list_dir` | read | Contents of a folder |
| `smb_stat` | read | Type, size, modification date |
| `smb_search` | read | Search by name (glob or substring), limited by depth, number of results and time (20 s) |
| `smb_read_file` | read | Text of PDF, DOCX, XLSX, CSV, TXT, MD, JSON, paginated by characters |
| `smb_copy_to_session` | read | Copies the file into the session's `workspace/smb/` (for OCR or the sandbox, e.g. scanned PDFs) |
| `smb_write_text` | write | Creates a UTF-8 text file |
| `smb_upload_from_session` | write | Uploads a file from the session workspace |
| `smb_mkdir` | write | Creates a folder (including intermediate ones) |
| `smb_move` | write | Renames/moves **within the same server and the same share** |

Common rules:

- Paths are written `server/Share/sub/folder/file.ext`, where `server` is the alias (e.g.
  `fs01/Documenti/report.docx`), or in UNC form `\\host\Share\...` (the host must be a configured
  server). Shares with the same name on different servers are told apart by the alias. The tool
  descriptions tell the agent to call `smb_list_shares` first.
- Writes never overwrite: if the file exists the error is `already_exists`. `overwrite=True`
  requires the user's explicit confirmation, as stated in the tool description. Writes fail on
  read-only shares.
- Moving across different shares or servers is not supported (it would require a delete):
  `cross_share_move`.
- Errors are always JSON `{"ok": false, "error": "<code>", "message": "..."}`, never exceptions.
  Main codes: `credentials_missing`, `auth_failed`, `account_locked`, `password_expired`,
  `account_disabled`, `access_denied`, `not_found`, `already_exists`, `share_read_only`,
  `share_not_allowed`, `server_not_allowed`, `cross_share_move`, `invalid_path`, `too_large`,
  `timeout`, `unreachable`, `not_configured`.
- The MCP server's audit logs record user, operation and path, **never** file contents or passwords.

## Multiple servers and credential sets {#server-multipli-e-set-di-credenziali}

A tenant can configure up to **20 file servers**. Each one has:

- a short **alias** (`fs01`, `sede-milano`: lowercase letters, digits and `-`), unique within the
  tenant: it is the first segment of every path the agent uses;
- a **host** (unique within the tenant, because `smbclient` keeps one session per host), port,
  default domain, allowed shares, and its own protocol and encryption settings;
- a **credential set** (`DEFAULT`, `ESTERO`…: uppercase letters and digits).

The set says **which Windows account** to use. Servers in the same AD domain share the same
account, and therefore the same set: the user enters one username/password pair **per set**, not
per server.

| Set | Keys in the credential store | How it reaches the MCP process |
|-----|------------------------------|--------------------------------|
| `DEFAULT` | `SMB_USERNAME` / `SMB_PASSWORD` | Individual placeholders, as before |
| others (e.g. `ESTERO`) | `SMB_USERNAME__ESTERO` / `SMB_PASSWORD__ESTERO` | JSON in `SMB_EXTRA_CREDENTIALS` |

- The names of the extra keys depend on the admin configuration, so they cannot sit in the static
  `env:` of the registry. The wildcard placeholder `${AION_USER_<SLUG>__*}` resolves to a JSON of
  **all** the user's credentials for that slug (see
  [credential store](user-isolation-and-credentials.md#placeholder-nel-registry-env)).
  In the Hub probe it receives a non-JSON mock value, treated as "not configured".
- The `DEFAULT` pair remains the connector's **required** one: it decides whether the connector is
  configured and whether the worker can start. That is why, while the connector is enabled, at
  least one enabled server must use the `DEFAULT` set (`default_credential_set_required`).
- Pairs for other sets are **optional**: with ACL-only visibility, a user may have an account in
  just one domain. If they are missing, only that set's servers answer `credentials_missing` (the
  message names the server and set); the others keep working.
- chat-ui shows the extra fields with no changes needed: `GET /v1/integrations` adds to the form
  one pair for each set other than `DEFAULT` used by an enabled server, with the list of servers in
  that set. Extra passwords are `write_only`, like `SMB_PASSWORD`.
- For `smb_files`, `POST /v1/integrations/credentials` only accepts `SMB_USERNAME`/`SMB_PASSWORD`
  keys with an optional `__<SET>` suffix, otherwise 400 `credential_key_not_allowed`: the wildcard
  JSON cannot be padded with arbitrary keys.

## Architecture

```
chat-ui (My integrations)                  admin-ui (Settings → File server)
  SMB_USERNAME / SMB_PASSWORD                General: switch, limits, block duration
  SMB_USERNAME__<SET> / SMB_PASSWORD__<SET>  Servers: alias, host, domain, set, shares [+ read-only]
        │ POST /v1/integrations/credentials          │ /admin/smb, /admin/smb/servers[/{id}[/test]]
        ▼                                            ▼
 user_mcp_credentials (AES-256-GCM)          smb_settings (global) + smb_servers (N per tenant)
        │ env at spawn                               │ read by the MCP server (cache TTL 30 s)
        └──────────────► mcp_servers_std/smb_files/server.py (FastMCP, thin)
                               └─► src/tools/smb_files/* (testable logic) ─► smbprotocol ─► \\server\share (TCP 445)
```

- **User credentials** reuse the [per-user credential store](user-isolation-and-credentials.md).
  The registry (`config_std/mcp_registry.yaml`) declares
  `SMB_USERNAME: ${AION_USER_SMB_FILES__SMB_USERNAME}` and the same for the password; values are
  resolved from the DB only when the user's MCP process is spawned. That is why the connector's
  `credential_mode` is `per_user`. Pairs for the other sets arrive via
  `SMB_EXTRA_CREDENTIALS: ${AION_USER_SMB_FILES__*}` (see
  [Multiple servers and credential sets](#server-multipli-e-set-di-credenziali)).
- **Admin configuration**: `smb_settings` (one row per tenant: switch, limits, block duration) and
  `smb_servers` (one record per file server). The MCP server reads them for
  `AION_CURRENT_TENANT_ID` with a 30-second cache: an admin save takes effect within that time,
  without restarting workers.
- **One worker per chat**: `smb_files` is in `_DEFAULT_SESSION_SCOPED_SERVERS`
  (`src/mcp_manager.py`) because `smb_copy_to_session` and `smb_upload_from_session` use the chat
  session's workspace.
- **Lazy connection**: the MCP process also starts with empty or mock credentials (Hub probe, a
  user who has not configured anything yet). Startup and `list_tools` therefore do no network I/O;
  the SMB connection is opened inside each tool, and the tool schema does not depend on credentials.

Code: logic in `src/tools/smb_files/` (`paths`, `credentials`, `auth_guard`, `client`, `extract`,
`ops`, `probe`, `settings_store`), MCP wrapper in `mcp_servers_std/smb_files/server.py`, admin API
in `src/api/admin_smb.py`, UI in `admin-ui/components/settings/SmbSection.tsx` and
`SmbServerCard.tsx`, dynamic credential fields in `src/runtime/dynamic_credential_fields.py`.

## Network

- The backend must reach the file server on **TCP 445** (SMB2/3; SMB1 is not supported). No port
  needs to be exposed to the browser: the backend is the only SMB client.
- The configured host must resolve via **internal DNS**. In the backend container, DNS is the
  Docker host's: if it does not resolve the company domain names, add a `dns:` entry with the
  company DNS to the `backend` service in `docker-compose.yml`; alternatively an `extra_hosts:`
  entry with the name → IP pair, or enter the IP directly as the host in admin-ui.
- With multiple networks (VPN, VLAN), check with **Test connection** from the backend, not from
  your own PC: the backend is what opens the connection.
- For encrypted traffic, turn on "Require SMB3 encryption" (requires dialect 3.0+ on the server).

### Development environment

`docker-compose.dev.yml` includes two test Samba servers (profile `smb`):

| Service | From the backend | From the host | Users | Shares |
|---------|------------------|---------------|-------|--------|
| `samba` | `samba:445` | `localhost:1445` | `alice`, `bob` | `Documenti` (read/write), `Archivio` (read-only, `alice` only) |
| `samba2` | `samba2:445` | `localhost:1446` | `carla` | `Documenti` (read/write) |

```bash
docker compose -f docker-compose.dev.yml --profile smb up samba samba2
```

`samba2` has different accounts, like a server in another domain. In admin-ui, create `fs01`
(host `samba`, set `DEFAULT`) and `fs02` (host `samba2`, set `ESTERO`) and try them with
**Test connection** (`alice` / `alice-pass-dev`, `carla` / `carla-pass-dev`). In chat-ui the extra
`ESTERO` pair appears; with a wrong password on `fs02`, only `fs02` gets blocked.

## Account-lockout protection {#protezione-dal-blocco-account}

Active Directory locks an account after a few wrong passwords (typically 5-10). An agent retrying a
failed tool in a loop could lock the user's account **for all other company services too**. To
prevent this, the connector applies a local block (`auth_guard`):

1. On the **first** logon error (`auth_failed`, `account_locked`, `password_expired`,
   `account_disabled`) a marker is written in the user's isolated HOME
   (`data/users/<uid>/mcp_home/.smb_auth_block.<set>.json`, permissions 0600), so it is shared by
   all of that user's open chats. The marker is **per credential set**: AD lockout is per account,
   and a set is an account; an error on the `ESTERO` servers does not block the `DEFAULT` ones.
2. The marker contains an HMAC fingerprint of username+password (random salt) and the reason:
   **never the password**.
3. As long as the current credentials match that fingerprint, every tool immediately returns the
   same error **without contacting the server**.
4. If the user updates the credentials, the fingerprint changes and the connector tries again on
   its own.
5. For `account_locked`, the block expires after the configured "local block duration" (the
   server-side lockout expires too); a successful logon removes the marker.

In addition, empty or mock credentials (Hub probe, unconfigured user) are recognised **before** any
connection: a fake password must never reach the server as a failed attempt.

## NTLM and Kerberos

- **v1: NTLM** (`auth_protocol=ntlm`, via `smbprotocol`). Zero configuration: only a username and
  password are needed. Also works with hosts given as IP addresses.
- **Kerberos is prepared but not active**: the `negotiate` setting exists, but actually using it
  requires `krb5`/`gssapi` libraries in the backend image, realm configuration (`krb5.conf`), the
  host given by **DNS name** (not IP, because of the SPN) and synchronised clocks. It is on the
  roadmap: until it is done, the recommended value remains `ntlm`, and `negotiate` may fail with
  `auth_failed` if no usable mechanism is available.
- Domain controllers can disable NTLM by policy: in that case the test with credentials shows it,
  and Kerberos will be the only option.

## Security

| Risk | Countermeasure |
|------|----------------|
| Reading/writing beyond the user's permissions | Per-user credentials: the file server applies NTFS ACLs |
| Access to system disks or shares | Per-share allowlist; system shares (`C$`, `ADMIN$`, `IPC$`…) rejected both by admin-ui and at runtime |
| Access to a colleague's personal folder | With the `{user}` personal folder, any path outside your own folder is rejected before contacting the server |
| Path traversal (`..`, segments ending in dot/space, invalid characters) | `paths.resolve_path`: validation **before** any network call |
| A server other than the configured ones (arbitrary UNC, unknown alias) | Rejected with `server_not_allowed` |
| Irreversible data loss | No delete tool; no overwrite without an explicit flag; no moves across shares or servers |
| Accidental writes to archives | Shares can be marked **read-only** by the admin, enforced in the MCP server |
| Huge files filling memory/context | Per-file read and write limits; paginated reads |
| Reading the saved password | `write_only` field: `GET /v1/integrations/credentials/{slug}/{key}` returns 403 `secret_write_only` and chat-ui never shows the value |
| Password in logs or audit | Never logged; the admin test audit records only `with_credentials` |
| Arbitrary keys in the `SMB_EXTRA_CREDENTIALS` wildcard bundle | Only `SMB_(USERNAME\|PASSWORD)(__<SET>)?` accepted on save; the probe receives a mock |
| AD account lockout from agent retries | `auth_guard` (previous section) |
| **Prompt injection from file contents** | Text read from files is untrusted data: the tool descriptions say so and the server executes nothing. The structural countermeasure is that the agent never has more rights than the user, cannot delete, and cannot reach shares outside the allowlist. Shares containing third-party files are best marked read-only |

### Good to know

- A user can have the agent write anywhere they **have** write rights on allowlisted shares that
  are not marked read-only: if a file read contains hostile instructions, the worst case is the
  same as a user making a mistake, but without deletions.
- Content that is read enters the conversation, and therefore the agent's memory (STM/LTM, short-
  and long-term memory), like any other tool output: choose which shares to expose accordingly.

## Troubleshooting

| Symptom / code | Likely cause | Action |
|----------------|--------------|--------|
| `credentials_missing` | The user has not configured the connector, or the pair for the server's set (named in the message) is missing | My integrations → enter username and password (for the set named) |
| `auth_failed` repeated with no new attempts | Local block active after a failed logon | The user updates the credentials (the block clears by itself) |
| `account_locked` | Account locked by AD | IT unlocks it; the local block expires after the configured window |
| `password_expired` | Password expired or must be changed | Change it in Windows, then update it in chat-ui |
| `access_denied` | NTFS ACLs or share permissions | Check the user's rights on the file server |
| `share_not_allowed` | Share not in that server's allowlist | The admin adds it on the server card |
| `outside_personal_folder` | Path outside the user's personal folder on a share with `{user}` | Use the `path` returned by `smb_list_shares` |
| `server_not_allowed` | Alias or host not configured (or a path without alias, e.g. `Documenti/...`) | Use `alias/Share/...` (see `smb_list_shares`) or add the server |
| `unreachable` / `timeout` | Network, DNS or firewall (TCP 445) | **Test connection** from the backend; check `dns:` and firewall |
| `not_configured` | Connector disabled or no enabled server with shares | Complete and save the admin configuration |

## Out of scope (roadmap)

Kerberos authentication, file deletion, per-user or per-group server allowlists (today only NTFS
ACLs decide), an "all shares on the server" mode with automatic enumeration, an "invalid
credentials" badge in chat-ui, DFS namespaces.

## Tests

```bash
python -m pytest src/test/ -k "smb" -v
```

The tests use a mocked `smbclient`; no SMB server is needed.
