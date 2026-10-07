---
title: SSO Migration & Authentication Modes
sidebar_position: 2
description: How the AION agent handles migration between local passwords and Single Sign-On (SSO) providers.
---

# SSO Migration & Authentication Modes

This document explains how the AION platform handles the migration from local password-based authentication to external SSO providers (like Microsoft Entra ID or Google Workspace).

## The Core Philosophy

When AION is switched from "Password Mode" to "SSO Mode" (e.g., Microsoft or Google), it enters a **Migration State**. 

1. **No Auto-Provisioning for Existing Accounts**: AION will never automatically link an incoming SSO login to an existing local account merely based on a matching email address. This prevents account takeover attacks.
2. **Explicit Linking**: A user with an existing local account must first authenticate using their **local password**, and *then* explicitly authorize the SSO provider to link the identities.
3. **SSO Enforced**: Once migration is active, users who have not yet linked their accounts will be denied access to the chat until they complete the linking flow.

## 1. Migration Flow (User Perspective)

When the administrator switches the system to "Microsoft" or "Google":

1. The user visits the login page. The SSO button (e.g., "Accedi con Microsoft") is displayed.
2. If the user clicks the SSO button but they haven't linked their account yet, AION will create a *new* account for them, or show an error if auto-provisioning is disabled. (Auto-provisioning is disabled during migration by default to avoid creating duplicate ghost accounts).
3. Therefore, existing users must log in using the **username and password form**.
4. Upon successful password login, the API detects that the system requires SSO and the user hasn't linked their account. The API returns `sso_link_required: true`.
5. The Chat UI intercepts this flag and displays the **Security Update Modal** (SSO Link Modal), blocking access to the chat.
6. The user clicks "Collega account Microsoft". They are redirected to the Microsoft login page.
7. After authenticating with Microsoft, they are redirected back to AION. The backend securely verifies the SSO token, links the Microsoft identity to their local AION user, and logs them in.

## 2. Admin Perspective & Temporary Passwords

Switching to an SSO mode does **not** generate passwords automatically. Users who already have a password keep it and link their SSO identity at the next login (step 6 above). For users who cannot log in (no password, or a forgotten one), the administrator generates a temporary password on demand from **Security → SSO migration** (`POST /admin/auth/temp-passwords`).

- Temporary passwords are random 12-character strings, stored hashed, shown **once** to the admin (dialog + CSV).
- They expire after `AION_SSO_TEMP_PASSWORD_TTL_DAYS` days (default **7**). Expiry is cleared when the user links SSO or changes the password.
- An expired temporary password is rejected with `temp_password_expired`.
- When `clear_password_on_link` is on (default), the local password of a **non-admin** user is removed as soon as they link SSO. Admins always keep their password (break-glass).
- While the migration is active (`origin = migration`, not completed) an IdP identity that is not yet linked can **not** create a new user: login fails with `sso_not_linked`. Only an explicit, authenticated link can attach an identity; there is never auto-linking by email.
- The migration completes automatically when no user is pending; the password form then disappears from chat-ui.
- Admin sign-in from admin-ui sends `client: "admin"`: the SSO/password restrictions of the chat client do not apply to users with the `admin` role.

### Break-glass

Set `AION_SSO_FORCE_PASSWORD=1` and restart the backend to restore password login for everyone (SSO gates, link requirement and migration lock are ignored). Remove it once the IdP is fixed.

## 3. The `handoff` State

Because the SSO callback flow happens in a separate browser context (or requires redirects), AION uses a `handoff` mechanism.

When the user completes the SSO login or link flow, they are redirected to `/login/sso#code=...`. The frontend reads the short-lived `code` (valid for 60 seconds) and POSTs it to `/v1/auth/sso/exchange`. 

This endpoints exchanges the code for a full `access_token` and `user_id`, preventing tokens from leaking in the URL history or referer headers.

## 4. API Endpoints for Migration

The administrator UI interacts with the following endpoints:

- `GET /v1/admin/auth/login-mode`: Returns the current mode (`password`, `microsoft`, `google`), the migration status (`sso_migration_active`), and counts of pending/migrated users.
- `PUT /v1/admin/auth/login-mode`: Changes the mode. Requires a provider validated in the last 30 minutes and an admin already linked to it. Re-selecting the current mode does not restart the migration.
- `GET /v1/admin/auth/sso-migration/users?status=pending|migrated|exempt|no_access`: User lists per migration state.
- `POST /v1/admin/auth/sso-migration/users/{id}/exempt`: Exempt/reinstate a user.
- `POST /v1/admin/auth/temp-passwords`: Generate temporary passwords for selected users.
- `DELETE /v1/admin/auth/users/{id}/sso-identities/{identity_id}`: Unlink an identity.
- `GET /v1/admin/sso/providers/redirect-uri`: Redirect URI to register at the IdP (derived from the backend public URL).
- The active provider cannot be disabled or deleted directly (`use_login_mode`, `provider_in_use`); changing its client id/secret requires re-validation but keeps it active.

## 5. Security Measures

- **Unique Constraints**: The database enforces a unique constraint `(tenant_id, user_id, provider)` on the `user_sso_identities` table to prevent linking issues.
- **CSRF Protection**: The `/auth/sso/link/start` endpoint strictly checks the authorized user context before generating the OAuth `state` token, preventing attackers from linking their SSO to a victim's account.
- **Short-Lived Codes**: Handoff codes are single-use (consumed atomically, a replay returns `code_already_used`) and expire after 60 seconds.

## 6. Interaction with Two-Factor Authentication

The optional [TOTP 2FA](./two-factor-auth.md) applies only to the password login while `login_mode = password`. During an SSO migration (any SSO mode active) it is not enforced, and it cannot be enabled until the system returns to password mode.
