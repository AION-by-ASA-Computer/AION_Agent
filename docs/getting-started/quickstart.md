---
sidebar_position: 3
title: Quickstart
description: Install AION on a Linux machine or a laptop with Docker, configure the AI model, send the first message and the first API call.
---

# Quickstart

This guide takes you from nothing to a working AION in about 15 minutes, on a Linux server or on a laptop with Docker. It is meant for IT people who want to try the product; no knowledge of the code is needed. For a production installation with your own domain and HTTPS, follow [Deploy with Docker](../deployment/docker.md) afterwards.

## What you need

- A machine with **Docker** and **Docker Compose** (Linux, macOS, or Windows with WSL2). For a trial a small server or a recent laptop is enough, because the AI model normally runs elsewhere; size the machine up only if you also host the model on it.
- `bash` and `curl`.
- Access to the **AI model** you want to use (its address and, if required, its API key).

## 1. Install

Run the installer. It downloads the ready-made images (no source code needed), creates a folder `aion-agent/` with the configuration and starts everything:

```bash
curl -fsSL https://raw.githubusercontent.com/AION-by-ASA-Computer/AION_Agent/main/scripts/install.sh | bash
```

Useful options (append after `bash -s --`, for example `... | bash -s -- --domain aion.example.com --email it@example.com`):

| Option | Meaning |
|---|---|
| `--domain <name>` | Public domain name. AION then gets an HTTPS certificate automatically (Let's Encrypt). Without it, AION answers on plain HTTP at `http://localhost`. |
| `--email <address>` | Contact email for the HTTPS certificate. |
| `--dir <path>` | Installation folder (default `./aion-agent`). |
| `--version <tag>` | A specific AION version (default: the latest). |

When it finishes, these addresses are available:

| Address | What it is |
|---|---|
| `http://localhost/` | Chat app |
| `http://localhost/admin` | Admin panel |
| `http://localhost/api/health` | Health check of the API server (answers `{"status": "ok"}`) |
| `http://localhost/docs/` | This documentation |

With `--domain`, replace `http://localhost` with `https://<your domain>`.

## 2. First login and AI model

1. Open the **admin panel** (`/admin`) and sign in with user **`admin`** and password **`admin`**.
2. You are asked to **change the password**. Do it now: this is the only administrator account.
3. The **First setup** wizard opens. The important step is the first one, **LLM**: enter the details of your AI model (provider, address, key), click **Test connection**, pick the model from the list. The next steps (embeddings, OCR, web search, policy, SSO) can be left at their defaults and changed later from **Settings**.
4. At the end of the wizard AION restarts the services it needs to apply the configuration.

## 3. Send the first message

1. Open the **chat app** (`/`) and sign in with the same `admin` account.
2. Write a message, for example *"What can you do?"*, and press Enter. The answer appears as it is generated.
3. Try a file: drag a PDF into the chat and ask *"Summarize this document in 5 bullet points"*.

To add colleagues, go to **Admin panel → Users** (see the [Administrator checklist](../admin-guide/checklist.md)).

## 4. Make the first API call (optional)

1. In the **admin panel → Users**, edit your user and turn on **Can create API keys**.
2. In the **chat app → Settings → API keys**, create a key with the **Chat** permission and copy it (it is shown only once).
3. Call the agent:

```bash
curl -s http://localhost/api/v1/chat \
  -H "Authorization: Bearer aion_XXXXXXXX_XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX" \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello! Answer in one sentence."}'
```

The answer is a JSON object whose `text` field contains the reply. The [API guide](../api-guide/overview.md) continues from here.

## Stop, restart, update

Run these commands from the installation folder (`aion-agent/`):

```bash
docker compose -f docker-compose.ghcr.yml ps        # status of the services
docker compose -f docker-compose.ghcr.yml logs -f backend   # API server logs
docker compose -f docker-compose.ghcr.yml down      # stop (data is kept)
docker compose -f docker-compose.ghcr.yml up -d     # start again
```

To update to a new version, use the **Update now** button in the admin panel (when available) or run the installer in `upgrade` mode; both make a backup first. See [Self-update](../deployment/self-update.md).

## Something went wrong?

| Symptom | What to check |
|---|---|
| The page does not open | `docker compose -f docker-compose.ghcr.yml ps`: all services should be `running`/`healthy`. The first start can take a couple of minutes. |
| The chat answers with an error about the model | The LLM configuration: **Admin panel → Settings → LLM**, run **Test connection** again. |
| HTTPS certificate not issued | The domain's DNS `A` record must point to this server, and ports 80 and 443 must be reachable from the internet. |

More answers in the [FAQ](./faq.md).
