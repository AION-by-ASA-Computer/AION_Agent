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

If an administrator enables SSO *before* some users have set up a local password, those users would be permanently locked out (since they cannot perform step 3 above). 

To prevent this, AION's **Auth Settings** engine automatically generates **Temporary Passwords** when the login mode is changed.

- The backend scans all active users.
- If a user has no password set (or hasn't logged in recently) and hasn't linked an SSO identity, the system generates a random 12-character password.
- These passwords are returned to the administrator in a **one-time pop-up dialog** containing a downloadable CSV file.
- The administrator must securely distribute these temporary passwords to the affected users.
- The temporary passwords expire after 48 hours.

## 3. The `handoff` State

Because the SSO callback flow happens in a separate browser context (or requires redirects), AION uses a `handoff` mechanism.

When the user completes the SSO login or link flow, they are redirected to `/login/sso#code=...`. The frontend reads the short-lived `code` (valid for 60 seconds) and POSTs it to `/v1/auth/sso/exchange`. 

This endpoints exchanges the code for a full `access_token` and `user_id`, preventing tokens from leaking in the URL history or referer headers.

## 4. API Endpoints for Migration

The administrator UI interacts with the following endpoints:

- `GET /v1/admin/auth/login-mode`: Returns the current mode (`password`, `microsoft`, `google`), the migration status (`sso_migration_active`), and counts of pending/migrated users.
- `PUT /v1/admin/auth/login-mode`: Changes the mode. This endpoint performs the temporary password generation and triggers the migration state lock.

## 5. Security Measures

- **Unique Constraints**: The database enforces a unique constraint `(tenant_id, user_id, provider)` on the `user_sso_identities` table to prevent linking issues.
- **CSRF Protection**: The `/auth/sso/link/start` endpoint strictly checks the authorized user context before generating the OAuth `state` token, preventing attackers from linking their SSO to a victim's account.
- **Short-Lived Codes**: Handoff codes are deleted immediately after use or after 60 seconds.
