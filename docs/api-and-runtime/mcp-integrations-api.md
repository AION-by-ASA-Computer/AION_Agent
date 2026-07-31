---
sidebar_position: 3
title: MCP integrations API (chat)
description: /v1/integrations endpoints for per-user credentials; chat Bearer authentication, not API Key.
---

# MCP integrations API (`/v1/integrations`)

These endpoints live under `/v1` but do **not** follow the "API Key" authentication model described in [REST API v1](rest-api.md).

## Authentication

- **Chat Bearer JWT** — same token obtained from `POST /auth/login` used by the chat UI (`Authorization: Bearer ...`).
- **Open mode** — if `AION_CHAT_PASSWORD_AUTH=0`, `GET /v1/integrations` responds without a token (list without credentials hint). Write/modify operations (`POST` / `PATCH` / `DELETE`) still require a non-anonymous identity (`403` if missing).

When `AION_CHAT_UI_INTERNAL_SECRET` is configured, the backend also accepts the `X-AION-Chat-Ui-Secret` header for server-to-server calls (Next.js BFF), as with other user-facing endpoints.

## Prerequisites

`AION_MCP_USER_CREDENTIALS=1` and `AION_CREDENTIAL_ENCRYPTION_KEY` configured on the backend to use per-user credential saving.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/v1/integrations/status` | Returns the enablement status of the user credentials feature. |
| `GET` | `/v1/integrations` | List of servers enabled by the admin + schema + non-sensitive hints of saved credentials. |
| `GET` | `/v1/integrations/runtime-errors` | Returns the startup/handshake errors encountered by the enabled MCP servers in a profile. |
| `GET` | `/v1/integrations/pending` | Lists the enabled servers in a profile for which mandatory user credentials are missing. |
| `PATCH` | `/v1/integrations/{server_slug}/preference` | Enables or disables a specific MCP integration for the current user. |
| `POST` | `/v1/integrations/credentials` | Saves (encrypting via AES-256-GCM) the per-user credentials for an MCP server. |
| `DELETE` | `/v1/integrations/credentials/{server_slug}/{credential_key}` | Removes a saved credential for the current user. |
| `GET` | `/v1/integrations/oauth/start` | Starts OAuth 2.0 Authorization Code + PKCE (S256); returns `authorization_url` and `state`. |
| `GET` | `/v1/integrations/oauth/callback` | Browser redirect callback: exchanges code for tokens and redirects to chat-ui. |
| `POST` | `/v1/integrations/oauth/callback` | Programmatic code/token exchange (chat-ui legacy path). |
| `GET` | `/v1/integrations/{server_slug}/oauth-status` | Returns `{ connected: bool }` for the current user. |

## Endpoint Details

### 1. `GET /v1/integrations/status`
Verifies the status of the per-user credentials feature.

- **Authentication**: Optional.
- **Response (200 OK)**:
  ```json
  {
    "credentials_feature_enabled": true,
    "hint": null
  }
  ```
  If the feature is not active (`AION_MCP_USER_CREDENTIALS=0`), `credentials_feature_enabled` will be `false` and `hint` will contain the instructions for enablement.

---

### 2. `GET /v1/integrations`
Returns all integrations enabled by the administrator (present in the DB and registered in the backend), enriched with the credentials schema and non-sensitive hints (e.g. timestamp or presence of the masked value) for the current user.

- **Authentication**: Chat Bearer JWT (or anonymous if `AION_CHAT_PASSWORD_AUTH=0`).
- **Response (200 OK)**:
  ```json
  {
    "integrations": [
      {
        "server_slug": "email-mcp-server",
        "display_name": "Email Client",
        "description": "IMAP/SMTP integration to read and send emails",
        "icon_url": null,
        "category": "productivity",
        "credential_mode": "per_user",
        "requires_user_credentials": true,
        "credential_schema": [
          {
            "key": "EMAIL_USER",
            "label": "Email Address",
            "type": "text",
            "required": true
          }
        ],
        "has_oauth": false,
        "is_configured": true,
        "org_managed": false,
        "user_enabled": true,
        "can_disable": true,
        "credentials_hints": [
          {
            "key": "EMAIL_USER",
            "display_hint": "user@example.com",
            "expires_at": null,
            "updated_at": "2026-06-22T14:10:00Z",
            "is_expired": false
          }
        ]
      }
    ],
    "credentials_feature_enabled": true
  }
  ```

---

### 3. `GET /v1/integrations/runtime-errors`
Returns any errors encountered during startup or handshake with the MCP servers configured for a specific profile.

- **Authentication**: Chat Bearer JWT.
- **Query Parameters**:
  - `profile` (string, mandatory): Profile name (e.g., `generic_assistant`).
  - `session_id` (string, optional): Chat session ID to access cached errors.
  - `probe` (boolean, optional, default `false`): If `true`, performs a live test of MCP processes instead of returning the cached error.
- **Response (200 OK)**:
  ```json
  {
    "errors": [
      {
        "server_slug": "broken-mcp",
        "display_name": "Broken Mcp",
        "error": "FileNotFoundError: ...",
        "hint": "Verify that the executable file path is correct",
        "reason": "runtime_error",
        "message": "Verify that the executable file path is correct"
      }
    ],
    "has_errors": true,
    "probes": []
  }
  ```

---

### 4. `GET /v1/integrations/pending`
Lists the integrations assigned to the profile that require credentials not yet configured by the user (or for which the administrator has not completed the configuration).

- **Authentication**: Chat Bearer JWT.
- **Query Parameters**:
  - `profile` (string, mandatory): Profile name.
- **Response (200 OK)**:
  ```json
  {
    "pending": [
      {
        "server_slug": "email-mcp-server",
        "display_name": "Email Client",
        "reason": "credentials_missing",
        "missing_keys": ["EMAIL_USER", "EMAIL_PASSWORD"],
        "message": "Configure your personal credentials to use this tool.",
        "integration": { ... }
      }
    ],
    "credentials_feature_enabled": true
  }
  ```

---

### 5. `PATCH /v1/integrations/{server_slug}/preference`
Allows the user to locally enable or disable an MCP server at the session/profile level.

- **Authentication**: Chat Bearer JWT (requires non-anonymous identity).
- **Path Parameters**:
  - `server_slug` (string, mandatory): Slug of the MCP server.
- **Body**:
  ```json
  {
    "is_active": false
  }
  ```
- **Responses**:
  - `200 OK`: Preference saved successfully.
  - `403 Forbidden`: If attempting to disable a mandatory integration (`user_may_disable` set to `false` by the admin), or if the user is anonymous.
  - `404 Not Found`: If attempting to enable an integration that is not enabled for users (`is_enabled_for_users == false` in the DB).

---

### 6. `POST /v1/integrations/credentials`
Saves in an encrypted manner (AES-256-GCM) a set of credentials for a given MCP server for the current user.

- **Authentication**: Chat Bearer JWT (requires non-anonymous identity).
- **Body**:
  ```json
  {
    "server_slug": "email-mcp-server",
    "credentials": {
      "EMAIL_USER": "user@example.com",
      "EMAIL_PASSWORD": "secretpassword"
    },
    "display_hints": {
      "EMAIL_USER": "user@example.com"
    }
  }
  ```
- **Responses**:
  - `200 OK`: Credentials saved. Returns `{"ok": true, "server_slug": "...", "saved_keys": [...]}`.
  - `403 Forbidden`: If the user is anonymous.
  - `404 Not Found`: If the MCP server does not exist or is not enabled for users.
  - `501 Not Implemented`: If `AION_MCP_USER_CREDENTIALS` is not enabled.

---

### 7. `DELETE /v1/integrations/credentials/{server_slug}/{credential_key}`
Deletes a specific stored credential key for the MCP server.

- **Authentication**: Chat Bearer JWT (requires non-anonymous identity).
- **Path Parameters**:
  - `server_slug` (string, mandatory): Slug of the MCP server.
  - `credential_key` (string, mandatory): Key of the credential to be removed (e.g., `EMAIL_PASSWORD`).
- **Responses**:
  - `200 OK`: Credential successfully deleted (`{"ok": true}`).
  - `404 Not Found`: If the credential does not exist for the current user.
  - `501 Not Implemented`: If the user credentials feature is not enabled.

---

### 8. OAuth flow (`/v1/integrations/oauth/*`)

Full OAuth 2.0 Authorization Code + PKCE (S256) for remote MCP connectors.

**Start** — `GET /v1/integrations/oauth/start?server_slug=...`

- Discovers authorization server metadata (RFC 9728 / RFC 8414) when needed.
- Optionally performs Dynamic Client Registration (RFC 7591) when `AION_MCP_OAUTH_DYNAMIC_REGISTRATION=1` (default).
- Returns `{ "authorization_url": "...", "state": "..." }`.

**Callback (browser)** — `GET /v1/integrations/oauth/callback?code=...&state=...`

- Exchanges the authorization code for `OAUTH_TOKEN` / `OAUTH_REFRESH_TOKEN` (encrypted in DB).
- Redirects to chat-ui (`AION_CHAT_URL`) with `oauth_status=success|error`.

**Callback (API)** — `POST /v1/integrations/oauth/callback`

- Same token exchange as the GET callback, but returns JSON (`{"ok": true, "server_slug": "..."}`).
- Body:
  ```json
  {
    "server_slug": "clickup",
    "code": "auth_code_from_provider",
    "state": "oauth_state",
    "code_verifier": "optional_pkce_verifier",
    "redirect_uri": "optional_override"
  }
  ```

**Status** — `GET /v1/integrations/{server_slug}/oauth-status`

- Returns `{ "connected": true|false, "server_slug": "..." }`.
- Expired access tokens with a valid refresh token are renewed automatically (lazy refresh in `credential_store`).

**Token refresh**

- When `OAUTH_TOKEN` expires, the backend attempts `grant_type=refresh_token` before MCP workers start.
- Configure `AION_OAUTH_TOKEN_EXPIRY_BUFFER_SECONDS` (default `60`) to refresh slightly before expiry.
- On refresh failure (`invalid_grant`), stored OAuth credentials are deleted and `connected` becomes `false`.

**PKCE state**

- OAuth `state` / `code_verifier` pairs are held in-process (`_oauth_pending`). The API must run with `--workers 1` (documented constraint).

## References

- [MCP user isolation and credential store](../mcp/user-isolation-and-credentials.md)
- Source code: `src/api/v1/mcp_integrations.py`
