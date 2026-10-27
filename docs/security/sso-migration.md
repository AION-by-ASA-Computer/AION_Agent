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
2. If the user clicks the SSO button but they haven't linked their account yet, login fails with `sso_not_linked`: while the migration is active no new account is created from an unlinked identity (this avoids duplicate ghost accounts).
3. Therefore, existing users must log in using the **username and password form**.
4. Upon successful password login, the API detects that the system requires SSO and the user hasn't linked their account. The API returns `sso_link_required: true`.
5. The Chat UI intercepts this flag and displays the **Security Update Modal** (SSO Link Modal), blocking access to the chat.
6. The user clicks "Collega account Microsoft". They are redirected to the Microsoft login page.
7. After authenticating with Microsoft, they are redirected back to AION. The backend securely verifies the SSO token, links the Microsoft identity to their local AION user, and logs them in.

## 2. Admin Perspective & Password Setup Links

The administrator **never sees or chooses a user's password**. Switching to an SSO mode does not create passwords. Users who already have a password keep it and link their SSO identity at their next login (step 6 above).

Users who can't log in (no password, or a forgotten one) need a password setup link. The administrator sends it from **Security → SSO migration** with "Invia link" (`POST /admin/auth/setup-links`). The platform emails the user a one-time link to `/set-password`, where they choose their own password. After that they sign in with it and the normal SSO link flow starts. See [Password setup by email](./password-setup-email.md).

- **Delivery and expiry**
  - Links need SMTP to be configured (admin-ui → Settings → SMTP). Without it the endpoint answers `409 smtp_not_configured`.
  - The response only reports the outcome: `{sent, failed, missing_email}`, never the link or the token.
  - A link expires after `AION_SSO_TEMP_PASSWORD_TTL_DAYS` days (default **7**).
  - Sending a new link invalidates the previous one.
  - Users without an email address are listed in `missing_email`.
  - A user who already linked the active provider gets `409 user_already_linked:<id>`.
- **Pending count.** A user counts as **pending** while they have a password **or** an active setup link. This keeps the migration, and the password form in chat-ui, open until they set the password and link. The `sso-migration/users?status=pending` list reports `has_password`, `setup_link_pending`, `setup_link_expires_at` and `setup_link_send_error`.
- **Mode switches.** When the switch is **SSO → password** or **SSO → another SSO provider**, users without a usable password receive the link automatically.
  - `PUT /admin/auth/login-mode` returns the delivery summary in `setup_links`.
  - It refuses the switch with `409 smtp_not_configured` when such users exist and SMTP is missing, so nobody is locked out.
  - `GET /admin/auth/login-mode/simulate` reports `affected_users`, `missing_email_count` and `smtp_configured`, so admin-ui can warn before confirming.
- **Legacy temporary passwords.** Temporary passwords issued by older versions keep working until they expire. An expired one is rejected with `temp_password_expired`. No new ones are generated.
- When `clear_password_on_link` is on (default), the local password is removed as soon as the user links SSO, **admins included**. The admin who activates SSO (after `admin_validate`) counts as migrated immediately and loses the password when the switch is applied. Emergency access goes through the recovery CLI (see Break-glass).
- While the migration is active (`origin = migration`, not completed) an IdP identity that is not yet linked can **not** create a new user: login fails with `sso_not_linked`. Only an explicit, authenticated link can attach an identity; there is never auto-linking by email.
- The migration completes automatically when no user is pending; the password form then disappears from chat-ui.
- **Reopening.** Unlinking a user's identity for the active provider, or sending a setup link, after the migration has completed (or after a `first_setup`) reopens it: `migration_completed_at` is cleared, `origin` becomes `migration` and `migration_started_at` is kept, so users who are already linked stay migrated. The password form comes back in chat-ui until that user links again, and then the migration closes by itself.
- **Unlink = standard relink.** `DELETE /admin/auth/users/{id}/sso-identities/{identity_id}` on an identity of the active provider puts the user back into the normal flow: password → `sso_link_required` → link the work account. A user without a password receives a setup link by email; the response carries the delivery summary in `setup_links`, or `setup_link_error` (e.g. `smtp_not_configured`) when it could not be sent: the unlink still happens and the link can be sent later from the migration list. A user who still has a password keeps it. Unlinking an identity of another provider changes nothing. While the migration is active, an SSO login whose email matches an existing account answers `sso_not_linked` (sign in with the password and link), whatever the new-account policy says.
- Admin sign-in from admin-ui sends `client: "admin"`: the SSO/password restrictions of the chat client do not apply to users with the `admin` role.
- In SSO mode the admin-ui login page shows an **"Accedi con Microsoft/Google"** button (`/auth/sso/start?client=admin`, callback purpose `admin_login`, handoff to `/admin/login/sso`). Only users with the `admin` role are accepted; new identities are never provisioned from this flow. The password form is shown only while at least one admin still has a local password (`admin_password_login` in `GET /auth/status`: migration still pending for an admin, or a password restored with the recovery CLI) or with `AION_SSO_FORCE_PASSWORD=1`. Once every admin has migrated, only the SSO button is shown.
- Each switch to SSO with `origin = migration` starts a **new** migration: only identities confirmed (linked or used to sign in) after `migration_started_at` count, so identities left over from a previous migration must be confirmed again.

### Break-glass

Set `AION_SSO_FORCE_PASSWORD=1` and restart the backend to restore password login for everyone (SSO gates, link requirement and migration lock are ignored). Remove it once the IdP is fixed.

Since migrated admins no longer have a local password, set a temporary one with the recovery CLI (prints a generated password, to be changed at first login):

```bash
# local checkout
python -m src.auth.recover set-password admin
# Docker install (install.sh), from the install directory
docker compose -f docker-compose.ghcr.yml exec backend python -m src.auth.recover set-password admin
```

The admin login page then shows the password form again (an admin has a password). `--password <value>` sets a specific password instead of a generated one.

## 3. New accounts in SSO mode

With an SSO mode active, accounts are created **only** by single sign-on, at each person's first login (auto-provisioning, after the migration has completed or with `origin = first_setup`):

- `POST /admin/users` returns `409 {"code": "sso_active_user_creation_disabled"}`: no new password accounts. The admin-ui hides the "Add user" button and points to the new-account policy instead.
- The default-admin bootstrap (`AION_SETUP_ADMIN_BOOTSTRAP`, backend startup and `setup_aion_env.py`) and the setup wizard's chat user are skipped. Emergency access still goes through the recovery CLI (see Break-glass).

### New-account policy

Since every account of the company tenant/domain could sign in, the administrator decides who may get a **new** account (admin-ui → Users → Sign-in → *New accounts*). Stored per tenant in `auth_settings.sso_signup_policy` / `sso_signup_allowlist`:

| Policy | Effect on a first SSO login | Error code |
|--------|-----------------------------|------------|
| `open` (default) | Every identity accepted by the provider (and its `allowed_domains`) gets an account | — |
| `allowlist` | Only listed full emails (`mario.rossi@azienda.it`) or whole domains (`@azienda.it`, exact match, no subdomains) | `sso_signup_not_allowed` |
| `closed` | No new accounts | `sso_signup_closed` |

- The policy applies **only to new accounts**: a user whose identity is already linked keeps signing in. To revoke access, delete the user (this also removes their SSO identities, and closes the migration if they were the last pending user).
- It is checked **before** the migration gate: while a migration is active an unknown identity that the policy rejects gets `sso_signup_closed` / `sso_signup_not_allowed`; one the policy accepts gets `sso_not_linked` (it must link from an existing account first). The admin-ui SSO login never creates accounts and always answers `sso_not_linked`.
- It can be configured while still in password mode (e.g. before switching), and is enforced only in SSO mode. The list is kept when switching to `closed`, so a gradual rollout can be paused and resumed.
- Entries are case-insensitive and deduplicated; at most 2000.
- chat-ui shows a translated message for both error codes (`login.sso_error.*`).

## 4. The `handoff` State

Because the SSO callback flow happens in a separate browser context (or requires redirects), AION uses a `handoff` mechanism.

When the user completes the SSO login or link flow, they are redirected to `/login/sso#code=...`. The frontend reads the short-lived `code` (valid for 60 seconds) and POSTs it to `/v1/auth/sso/exchange`. 

This endpoints exchanges the code for a full `access_token` and `user_id`, preventing tokens from leaking in the URL history or referer headers.

## 5. API Endpoints for Migration

The administrator UI interacts with the following endpoints:

- `GET /v1/admin/auth/login-mode`: Returns the current mode (`password`, `microsoft`, `google`), the migration status (`sso_migration_active`), and counts of pending/migrated users.
- `PUT /v1/admin/auth/login-mode`: Changes the mode. Requires a provider validated in the last 30 minutes and an admin already linked to it. Re-selecting the current mode does not restart the migration.
- `GET /v1/admin/auth/sso-migration/users?status=pending|migrated|exempt|no_access`: User lists per migration state.
- `POST /v1/admin/auth/sso-migration/users/{id}/exempt`: Exempt/reinstate a user.
- `GET /v1/admin/auth/login-mode/simulate?mode=...`: `{affected_users, missing_email_count, smtp_configured}`: who would receive a setup link on that switch.
- `POST /v1/admin/auth/setup-links` `{user_ids: [...]}`: Email a password setup link to the selected users. Returns `{setup_links: {sent, failed, missing_email}}`; `409` with `smtp_not_configured` or `user_already_linked:<id>`.
- `DELETE /v1/admin/auth/users/{id}/sso-identities/{identity_id}`: Unlink an identity. For the active provider it reopens the migration and, if the user has no password, emails a setup link (`setup_links` / `setup_link_error` in the response).
- `GET /v1/admin/auth/signup-policy`: `{policy, allowlist, applies, max_entries}` (`applies` is true when an SSO mode is active).
- `PUT /v1/admin/auth/signup-policy` `{policy: "open"|"allowlist"|"closed", allowlist: [...]}`: Saves the new-account policy. `400` with `invalid_signup_policy`, `invalid_allowlist_entry` (+ `entry`) or `allowlist_too_long` (+ `max`).
- `GET /v1/admin/sso/providers/redirect-uri`: Redirect URI to register at the IdP (derived from the backend public URL).
- The active provider cannot be disabled or deleted directly (`use_login_mode`, `provider_in_use`); changing its client id/secret requires re-validation but keeps it active.

## 5. Security Measures

- **Unique Constraints**: The database enforces a unique constraint `(tenant_id, user_id, provider)` on the `user_sso_identities` table to prevent linking issues.
- **CSRF Protection**: The `/auth/sso/link/start` endpoint strictly checks the authorized user context before generating the OAuth `state` token, preventing attackers from linking their SSO to a victim's account.
- **Short-Lived Codes**: Handoff codes are single-use (consumed atomically, a replay returns `code_already_used`) and expire after 60 seconds.

## 6. Interaction with Two-Factor Authentication

The optional [TOTP 2FA](./two-factor-auth.md) policy applies only while `login_mode = password` and cannot be enabled while an SSO mode is active. Switching to SSO does **not** remove existing TOTP enrollments: a user who already configured 2FA keeps it, and the code is still required at every password login until they link their SSO account. The TOTP secret is removed only when the user links (or signs in via SSO); nobody is asked to enroll during a migration.
