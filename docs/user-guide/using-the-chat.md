---
sidebar_position: 1
title: Using the chat
description: Everyday guide to the AION chat app - conversations, profiles, files, thinking, web search, voice, integrations, settings and API keys.
---

# Using the chat

The chat app is where you work with AION every day: you write a request, the agent works on it — reading files, using company tools, searching the web — and answers. This page explains the main features for people who use the chat; no technical knowledge is needed. What you can see depends on what your administrator has enabled, so some options may be missing for you.

## Signing in

Open the address your company gave you (for example `https://aion.example.com`). Depending on the configuration you sign in with:

- **username and password** — the first time you may receive an email link to set your password, or a temporary password that you must change at first login;
- **your Microsoft or Google company account** (single sign-on);
- a **verification code** from an authenticator app, if two-factor authentication is enabled.

Forgot your password? Use **Forgot password** on the sign-in page: you receive a reset link by email.

## Conversations

- **New conversation** (sidebar) starts a fresh chat. Each conversation remembers its own messages and files.
- The **sidebar** lists your past conversations; use **Search conversations…** to find one by its content.
- Conversations are **private**: nobody else, administrators included, can read them from the admin panel.
- Conversations started from other channels (WhatsApp, Telegram, API integrations that use your key) appear in the same list.

## Writing a request

Write as you would to a colleague, and be specific. Good requests say **what** you want, **from which source** and **in what format**:

> "From the attached Excel file, list the 5 customers with the highest revenue in 2025 and make a bar chart."

While the agent works you see its progress: which tools it is using and, if you open the step, what it sent and received. You can **stop** an answer at any moment, **regenerate** it, and rate it to help administrators improve the service.

## Choosing the profile

A **profile** is a version of the agent specialised for a job (general assistant, file-server assistant, data analysis, IT operations…). Choose it with the **Profile** selector before writing. Each profile has its own instructions and tools, so the right profile gives better answers. You only see the profiles your administrator has allowed for you.

## Files

- **Attach** files with **+** or by dragging them into the chat: PDF, Word (also old `.doc`), Excel, CSV, images, text, audio. Scanned documents are read with OCR.
- The agent can **create files** — reports, Word documents, spreadsheets, charts. They appear in the conversation and in the file panel, ready to download.
- Files belong to the conversation: to reuse a document in a new chat, attach it again.

## Options in the message box

| Option | What it does | When to use it |
|---|---|---|
| **Thinking** (Off / Minimal / Medium / Maximum) | How much the AI model reasons before answering. | Off or Minimal for quick questions; Maximum for complex analyses. Higher is slower. |
| **Web search** | Lets the agent search the internet; **Advanced search** limits it to specific sites. | Questions about recent facts, prices, documentation. Turn it off to use only company sources and your files. |
| **Model** | Which AI model answers, if more than one is configured. | Leave the system default unless told otherwise. |
| **Deep Research** | Autonomous, longer research on the web, with a dedicated panel and a final report. | In-depth research that would take you hours by hand. |
| **Microphone** | Dictate the message instead of typing (`Esc` cancels). Shown only if enabled and the site uses HTTPS. | Long requests, on the move. |

## Side threads

Select a passage of an answer to open a **side thread**: a small separate conversation to ask about that detail without cluttering the main chat. See [Side threads](../clients/side-threads.md).

## Integrations: let the agent act as you

Some connectors need **your own credentials** — for example your Windows account to read the company file shares, or your sign-in to an external service. Open **Integrations** in the sidebar, choose the service and enter the credentials or click **Sign in with…**. Credentials are stored encrypted and used only for your requests; passwords cannot be read back, not even by you.

If an integration says it is *managed by the administrator*, it uses a shared company account and there is nothing for you to enter.

More: [Windows file shares](../mcp/smb-files.md), [Microsoft 365](../mcp/microsoft-365.md).

## Automations

**Automations** (sidebar) lets you schedule a request to run regularly — for example "every Monday at 8:00, summarise last week's open tickets". Each run is saved in a conversation that you can open from the sidebar.

## Settings

Open **Settings** from your profile menu:

| Tab | What you find |
|---|---|
| **Profile** | Photo, avatar colour and account details. |
| **Appearance** | Theme, text size and application language. |
| **Security** | Password and account protection. |
| **Instructions** | Personal instructions added to every conversation, e.g. "Answer in Italian" or "I work in purchasing; amounts are in EUR". |
| **API keys** | Personal keys to call AION from scripts and tools — see [Get an API key](../api-guide/get-an-api-key.md). Visible only if your administrator enabled it. |
| **WhatsApp / Telegram** | Link your phone to chat with AION from the messaging app — see [WhatsApp](../integrations/whatsapp.md) and [Telegram](../telegram/RUNBOOK.md). |

## Memory: what AION remembers

AION remembers useful facts about you across conversations (your role, preferences, recurring information) to give better answers over time. Within a long conversation, older messages are summarised automatically so the conversation can continue. If the agent remembers something wrong, tell it in the chat ("forget that…", "from now on…") or update your **Instructions**.

## Tips

- One topic per conversation: the agent focuses better and you find things more easily.
- Ask the agent to show its sources ("tell me which file and page you used").
- If an answer is wrong, say what is wrong instead of starting over: the agent corrects itself using the context.
- Check important numbers: the agent is a very capable assistant, but like any AI it can make mistakes.
