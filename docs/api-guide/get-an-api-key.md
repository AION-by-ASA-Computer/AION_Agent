---
sidebar_position: 2
title: Get an API key
description: Step by step - the administrator enables API keys for a user, the user creates a key with the right permissions, tests it, stores it and revokes it.
---

# Get an API key

An API key is the password a program uses to call AION on your behalf. This page shows how to obtain one, which permissions to choose, how to test it and how to keep it safe. It involves two people: the **administrator**, who allows a user to create keys, and the **user**, who creates them. (If you are both, do both parts.)

## Step 1 — The administrator enables API keys for the user

API keys are **off by default** for every user.

1. Open the **admin panel → Users**.
2. Edit the user and, in the **API keys** section, turn on **Can create API keys**.
3. Optionally adjust the limits:

| Setting | Default | Meaning |
|---|---|---|
| Maximum active keys | 5 | How many valid keys the user can have at the same time (1–100). |
| Maximum lifetime (days) | 90 | The longest expiry the user can choose for a key (1–3650). |

Turning the feature off later **revokes all of that user's keys immediately**. Lowering the limits does not touch existing keys.

:::tip Integrations that should not depend on a person
If the integration must keep working when an employee leaves, use a [service account](../security/service-accounts.md) instead: a non-human account (`svc-…`) whose keys only administrators create, from **admin panel → Service accounts**.
:::

## Step 2 — The user creates the key

1. Open the **chat app → Settings → API keys** (profile menu → Settings).
2. Click **New key**.
3. Fill in:
   - **Name** — where the key will be used, for example `n8n invoices workflow`.
   - **Permissions** — tick only what the integration needs (see the table below).
   - **Expiration** — the number of days the key stays valid, up to the maximum allowed.
4. Click **Create key** and **copy the key right away**. It looks like `aion_ab12cd34_…` and is shown **only once**: AION keeps only a fingerprint of it and cannot show it again. If you lose it, revoke it and create a new one.

### Which permissions do I need?

| Permission (scope) | Lets the key… | Needed for |
|---|---|---|
| **Chat** (`chat`) | Send messages to the agent and receive replies; list available profiles. | Almost every integration. |
| **Read conversations** (`conversations:read`) | List conversations and read their messages. | Reading history, checking the result of a turn. |
| **Manage conversations** (`conversations:write`) | Create, rename and delete conversations. | Creating a conversation with a title or tags before chatting. |
| **Read files** (`files:read`) | List and download files of a conversation. | Downloading reports or documents the agent produced. |
| **Upload files** (`files:write`) | Upload files to a conversation. | Asking the agent to analyze a document. |

A key can never do more than its owner: it sees only the owner's conversations, uses only the profiles the owner is allowed to use and never has administrator rights, even if the owner is an administrator. Some areas never accept keys at all: personal memory, integration credentials, scheduled jobs, settings, key management itself and the whole admin API.

## Step 3 — Test the key

Before using the key in an integration, check that it works with one quick request. The test asks AION for the list of **profiles** your key can use: if the list comes back, the key is valid.

You need two values:

| Value | Where to find it | Example |
|---|---|---|
| **AION address** | The address of your AION installation, followed by `/api` | `https://aion.example.com/api` |
| **API key** | The key you copied in step 2 | `aion_ab12cd34_...` |

Open a terminal and run the commands for your system, replacing the two example values with yours:

import Tabs from '@theme/Tabs';
import TabItem from '@theme/TabItem';

<Tabs groupId="os">
<TabItem value="windows" label="Windows (PowerShell)" default>

```powershell
# 1. Save the address and the key in two variables (replace with your values)
$env:AION_URL = "https://aion.example.com/api"
$env:AION_API_KEY = "aion_ab12cd34_..."

# 2. Ask AION for the profiles you can use
Invoke-RestMethod "$env:AION_URL/profiles" -Headers @{ Authorization = "Bearer $env:AION_API_KEY" } | Select-Object slug, name
```

</TabItem>
<TabItem value="unix" label="Linux / macOS (bash)">

```bash
# 1. Save the address and the key in two variables (replace with your values)
export AION_URL="https://aion.example.com/api"
export AION_API_KEY="aion_ab12cd34_..."

# 2. Ask AION for the profiles you can use
curl -s "$AION_URL/profiles" -H "Authorization: Bearer $AION_API_KEY"
```

</TabItem>
</Tabs>

The two variables `AION_URL` and `AION_API_KEY` are used by all the examples in the API guide: set them once and they stay valid until you close the terminal.

:::note The test calls AION, not the AI model
`AION_URL` is the address of your AION installation. The request reaches AION, which checks the key and answers with your profiles. The AI model behind AION is configured by the administrator and is never called directly by your scripts.
:::

If the key works (and has the **Chat** permission), you get the list of your profiles. In PowerShell:

```text
slug          name
----          ----
aion_std      AION Standard
```

With curl you get the same list as JSON, with more details for each profile (description, tools, skills):

```json
[{"slug": "aion_std", "name": "AION Standard", "description": "…", "mcp_servers": […], "skills": […]}]
```

If something is wrong, you get an error instead:

| Response | Meaning |
|---|---|
| `401 api_key_invalid` / `api_key_invalid_format` | The key was copied wrong (it must be the full `aion_<8 chars>_<32 chars>` string). |
| `401 api_key_expired` / `api_key_revoked` | Create a new key. |
| `401 api_key_owner_disabled` | The administrator disabled API keys for you, or your account. |
| `403 missing_scope` | The key does not have the permission this endpoint needs. |

## Keep it safe

- Treat the key like a password: store it in a secret manager or in an environment variable, **never** in source code, in a Git repository or in a web page that runs in the browser.
- Use **one key per integration**, with the minimum permissions and the shortest practical expiry. When a key leaks, you revoke only that one.
- Check **Last used** in the key list: a key that is never used can be revoked.
- Rotate keys before they expire: create the new key, update the integration, then revoke the old one.

## Revoke a key

In **chat app → Settings → API keys**, click **Revoke** next to the key. The effect is immediate: integrations using it start receiving `401 api_key_revoked`. Revoked and expired keys stay in the list as history.

## Manage keys from a program

The same operations are available through `GET/POST/DELETE /v1/me/api-keys`, but only with a user's login token, never with an API key (a key cannot create other keys). Details and the full validation rules: [API keys reference](../security/api-keys.md).

Next: [Your first API call](./first-api-call.md).
