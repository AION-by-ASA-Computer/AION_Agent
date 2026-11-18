---
sidebar_position: 6
title: Remote MCP servers (remote-bridge)
description: How AION reaches streamable HTTP MCP servers with a Bearer token through the mcp-remote stdio bridge - org_shared and per_user credentials, HTTP brokers, pinned version, reduced environment and sizing.
---

# Remote MCP servers via `mcp-remote` (`remote-bridge`)

Some MCP (Model Context Protocol) servers do not run next to AION but on another machine, reachable over HTTP. This page explains how AION connects to them through a small bridge process, how the access token is passed, and how many resources the bridge uses. It is for administrators and developers/operators who add remote MCP servers or size an installation.

A remote MCP server (streamable HTTP or SSE) is installed as a `type: remote-bridge` entry. AION does not open the HTTP connection itself: it starts the [`mcp-remote`](https://www.npmjs.com/package/mcp-remote) bridge, which to AION looks like a normal stdio server and forwards requests to the remote server with an `Authorization` header.

This is how AION SRE connects its brokers (one container per data source, read-only tools, Bearer token).

## Registry entry

The admin "install from URL" action (`build_remote_bridge_registry_config` in `src/mcp_remote_install.py`) produces an entry like this:

```yaml
ssh_broker:
  type: remote-bridge
  command: node
  args:
    - node_modules/mcp-remote/dist/proxy.js
    - http://ssh-broker:8080/mcp
    - --header
    - "Authorization: Bearer ${API_KEY}"
  env:
    API_KEY: ${API_KEY}
  auth_env_var: API_KEY
  remote_url: http://ssh-broker:8080/mcp
  allow_http: true          # only for HTTP brokers on the internal network
  enabled_tools: [read_status, search_logs]
```

`${API_KEY}` in the header is resolved by `mcp-remote` from its own environment, so the token never appears in the process arguments.

## Credentials

| `credential_mode` | Token | Variable (`auth_env_var`) |
| --- | --- | --- |
| `org_shared` | One for the whole organization, encrypted in the `credential_store` | `API_KEY` / `OAUTH_TOKEN` / `BASIC_AUTH` |
| `per_user` | One per user, connected from chat-ui | `AION_USER_<SLUG>__<KEY>` |

AION SRE brokers use `org_shared`: one token for AION, not one per user.

If the token is missing, AION does not start the bridge (`_remote_bridge_auth_missing` in `src/mcp_manager.py`). Without a Bearer token, `mcp-remote` would try its own OAuth flow in the browser. With a wrong token, a broker that answers `401` to every request (including OAuth client registration) makes `mcp-remote` exit immediately (in under a second), with no callback left waiting.

:::note `org_shared` entries installed before the fix
Up to the version that introduced this page, `org_shared` entries had `auth_env_var: AION_USER_<SLUG>__…` while the token arrived in `API_KEY`, so the bridge never started. `resolve_remote_bridge_auth_env_var` now uses the header variable in this case, so existing entries work without changes.
:::

## HTTP brokers: `allow_http`

`mcp-remote` rejects `http://` URLs that do not point to localhost. For a broker reached over HTTP on the internal Docker network, set `allow_http: true` on the entry (YAML only, `config/mcp_registry.local.yaml`). AION adds `--allow-http` at start time (`resolve_remote_bridge_spawn`) without writing it into the saved `args`.

:::warning
Unencrypted traffic is acceptable only on a private, non-shared network. Otherwise expose the broker over HTTPS.
:::

## Which tools the agent sees

The filter is `enabled_tools` on the registry entry (admin `POST /admin/mcp/{name}/tools-config`), applied on top of the read-only tools exposed by the broker. AION does not use the `--ignore-tool` option of `mcp-remote`.

## `mcp-remote` version

All traffic to remote servers goes through the bridge, so its version is pinned:

- `MCP_REMOTE_VERSION` in `src/mcp_remote_install.py`;
- `docker/package.mcp-remote.json` (exact version) and `docker/package-lock.mcp-remote.json`, installed in the backend image with `npm ci --omit=dev`;
- outside Docker, without a local `node_modules/mcp-remote`, AION runs `npx -y mcp-remote@<MCP_REMOTE_VERSION>`.

To upgrade:

1. Change the version in the constant and in `package.mcp-remote.json`.
2. Regenerate the lockfile (`npm install --package-lock-only` in a folder containing that `package.json`).
3. Run `src/test/test_mcp_remote_install.py` (checks that the three versions match) and `src/test/test_mcp_remote_bridge_broker.py`.

## Process environment

The bridge is third-party software, so it only receives `PATH`, `HOME`, locale, proxy and certificate variables (`NODE_EXTRA_CA_CERTS`, …) plus the registry `env:` block, i.e. the token. It gets none of the backend's `AION_*` variables, except the context ones (`AION_CURRENT_*`, `AION_CHAT_SESSION_ID`). See `AION_MCP_ENV_SCRUB` and `AION_MCP_ENV_ALLOWLIST` in [MCP user isolation and credentials](user-isolation-and-credentials.md).

## Sizing

Measured on a local FastMCP broker (macOS, Node 22, `mcp-remote` 0.1.49): about **100 MB of RSS** per process, unchanged after 20 calls.

How many processes exist depends on the pool (`AION_MCP_POOL=1`):

| Configuration | `mcp-remote` processes | Idle shutdown |
| --- | --- | --- |
| `AION_MCP_USER_POOL=1` (default) | one per **user** and per broker, shared by all of that user's conversations | only with `AION_MCP_USER_POOL_IDLE_CLEANUP=1`, after `AION_MCP_POOL_IDLE_SEC` |
| `AION_MCP_USER_POOL=0` | one per **conversation** and per broker | after `AION_MCP_POOL_IDLE_SEC` (default 1800 s, checked every 60 s) |

With the default, all `sre-bot` investigations share one process per broker (memory ≈ brokers × 100 MB) and the worker serializes calls: with many concurrent investigations, calls to the same broker queue up. With `AION_MCP_USER_POOL=0` calls run in parallel, but the number of processes becomes concurrent investigations × brokers; the AION SRE concurrency limit keeps that under control.

## Tests

`src/test/test_mcp_remote_bridge_broker.py` (marker `integration`) starts a streamable HTTP FastMCP broker that checks the Bearer token and reaches it with the real `mcp-remote`: correct token, missing token, wrong token, and an HTTP broker on a non-loopback IP with and without `allow_http`. The test is skipped if `node` or a local `mcp-remote` is missing; to point to one installed elsewhere:

```bash
AION_TEST_MCP_REMOTE_PROXY=/path/to/node_modules/mcp-remote/dist/proxy.js \
  python -m pytest src/test/test_mcp_remote_bridge_broker.py -v
```
