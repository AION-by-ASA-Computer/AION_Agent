---
title: Telegram channel
sidebar_position: 2
description: Set up, use, operate and test the AION Telegram channel - manager bot, personal assistants, account linking and troubleshooting.
---

# Telegram channel

The Telegram channel lets employees chat with AION from Telegram through
**personal assistants**: Telegram bots that each user creates for themselves,
each with its own agent profile and project. Use it when people want AION on
their phone or desktop Telegram app instead of the chat-ui. Telegram
conversations are regular AION sessions, so they also appear in the chat-ui
sidebar and can be continued there. This page is for administrators who set
up the channel, users who link their account and create assistants, and
operators who run and troubleshoot it.

| Section | For |
|---------|-----|
| [How it works](#how-it-works), [Setup](#setup), [Startup](#startup) | Administrator |
| [Link your Telegram account](#link-your-account), [Manager bot and personal assistants](#roles), [Create a personal assistant](#personal-bots), [Personal and shared assistants](#personal-and-shared), [Chatting with the agent](#chatting-with-the-agent), [Replies, stop and attachments](#replies-stop-attachments) | End user |
| [Administration](#administration), [Assistant lifecycle](#lifecycle), [Webhook mode](#webhook-mode), [Encryption key rotation](#key-rotation), [Guaranteed behaviour](#guaranteed-behaviour), [Troubleshooting](#troubleshooting) | Administrator / operator |
| [Manual test checklists](#manual-test-checklists) | Developers and QA |

:::note
The bots' replies and AION's `telegram:` log lines are currently written in
Italian. Log lines are quoted verbatim (in code font) so you can search for
them; bot replies are quoted in English translation.
:::

## How it works {#how-it-works}

The channel runs **inside the AION process**: the `_lifespan` of
`src/api/main.py` starts and stops it. By default it receives updates with
long polling, so it only needs outbound traffic to `api.telegram.org:443`,
with no webhook and no tunnel. Alternatively it can receive updates via
**webhook** (see [Webhook mode](#webhook-mode)).

There are two kinds of bot:

- one **manager bot** per installation, created by the administrator in
  @BotFather. Users link their account and create assistants here;
- **personal assistants**, created by each user from the manager bot with
  `/newbot`. This is where users chat with the agent.

## Setup (admin) {#setup}

The channel configuration is managed **only** from **admin-ui → Telegram**
(`GET/PUT /admin/telegram/settings`), on the **Connection**, **Policies** and
**Chat** tabs, and is stored **only in the database**: table `tg_settings`,
one row per tenant, with all values (including the manager token) in a single
JSON encrypted with `AION_CREDENTIAL_ENCRYPTION_KEY`.

:::warning
`.env` is not read, neither as an initial value nor as a fallback. Fields
that were never saved use the defaults below, and if `AION_TELEGRAM_*`
variables are still set in the environment, the log reports that they are
ignored.
:::

Typical first setup:

1. Create the manager bot in @BotFather and copy its token.
2. In @BotFather, turn on **Bot Management Mode** for it (see
   [Startup](#startup)); it is needed to create personal assistants.
3. In admin-ui → Telegram → **Connection**: tick **Enable Telegram
   integration**, paste the token, optionally set a proxy, and click
   **Test token**.
4. On **Policies**, select the profiles (and projects) allowed on Telegram:
   with an empty list nothing is allowed.
5. Save. The gateway starts right away, without a restart.

The page also shows the manager bot's status (connected, Bot Management Mode,
assistants listening, encryption key) and a **Test token** button (`getMe` on
Telegram, without saving). The token is never returned: the field only shows
the last 4 characters of the saved one, and leaving it empty keeps it.

On save, the new configuration applies **immediately, without restarting the
API or the container**: the Telegram gateway stops and restarts by itself
with the new values (log: `telegram: impostazioni riapplicate`). Every save
writes a `settings_updated` line to the operations log, with only the names of
the changed fields.

### Settings

The first column is the field name, as used by the API and in the rest of
this page.

| Field | Default | Notes |
|---|---|---|
| `enabled` | `0` | with `0`, AION loads nothing of the channel |
| `manager_token` | — | manager bot token from @BotFather; never in git |
| `proxy_url` | — | `http://`, `https://` or `socks5://` (corporate proxy) |
| `delivery_mode` | `polling` | how updates arrive: `polling` (long polling, default) or `webhook` (Telegram calls AION on a public HTTPS URL, see [Webhook mode](#webhook-mode)) |
| `polling_timeout` | `50` | long-polling seconds for `getUpdates` (`polling` mode only) |
| `shutdown_grace_sec` | `10` | how long to wait for running handlers at shutdown (fixed, cannot be changed from admin-ui) |
| `pairing_code_ttl_min` | `15` | validity (minutes) of account-linking links |
| `manager_chat` | `0` | `0`: the manager bot only manages accounts and assistants; users chat with their personal assistants. `1`: re-enables chat on the manager (`/new`, `/profile`, `/project`, `/stop`); use only in emergencies or for demos |
| `default_profile` | `generic_assistant` | profile offered first (⭐) in the `/newbot` wizard; with `manager_chat=1` it is also the initial profile of the manager chat |
| `max_concurrent_jobs` | `1` | agent turns running in parallel; the others wait in a queue |
| `stream_edit_interval_ms` | `1000` | how often the streamed reply is updated |
| `turn_timeout_sec` | `900` | maximum duration of a turn started from Telegram |
| `default_thinking_level` | — | reasoning level of Telegram turns: `off`, `min`, `medium`, `max`; empty = system default (`AION_DEFAULT_REASONING_EFFORT`). As on WhatsApp, it is copied into the conversation metadata and the chat-ui composer shows it |
| `max_outbound_files` | `5` | files generated by the agent in a turn that are sent back to the chat; the rest stay in the session and the bot writes "📁 N more files are available on AION" |
| `rich_messages` | `1` | replies in Telegram's rich format (see [Replies, stop and attachments](#replies-stop-attachments)); `0` = HTML only |
| `show_reasoning` | `1` | the model's reasoning in a collapsible section (rich format only) |
| `show_tools` | `1` | shows the tools being called (while streaming and in a box at the end of the reply) |
| `max_running_bots` | `200` | personal bots listening at the same time (safety net; above the limit a bot is not started and the log says so) |
| `reconcile_interval_min` | `30` | periodic check of the assistants (see [Assistant lifecycle](#lifecycle)); `0` turns it off |
| `max_bots_per_user` | `3` | personal bots per AION user created with `/newbot` (deleted ones do not count) |
| `allowed_profiles` | — | channel policy (strict allowlist): profiles (comma-separated slugs) usable from Telegram; empty = none |
| `allowed_projects` | — | channel policy (strict allowlist): projects (comma-separated slugs) usable from Telegram; empty = none ("No project" is always available) |
| `AION_CREDENTIAL_ENCRYPTION_KEY` | — | the key AION already uses for credentials; it also encrypts the personal bots' tokens. Without it, development uses an insecure key; in production `/newbot` is disabled. In admin-ui → Settings it appears masked (`***`). This one is an environment variable, not a field of the Telegram page |

Dependencies: `aiogram[proxy]` in `requirements.txt`
(`uv pip install -r requirements.txt`).

## Startup {#startup}

```bash
uvicorn src.api.main:app --reload --reload-exclude data/sessions
```

Expected logs when the channel is enabled (logger `aion.telegram`):

- `telegram: gateway avviato (long polling)` (or `(webhook)`) — gateway started
- `telegram: bot manager @<username> (id=…) can_manage_bots=True|False`

If `can_manage_bots=False`, open the **@BotFather Mini App** (the *Open*
button in the chat, or `https://t.me/BotFather?startapp`), choose the bot and
turn on **Bot Management Mode** (*Mode Settings* section). The option is not
in the text menu `/mybots`. It is required from Phase 4 on (personal
assistants).

---

## Link your Telegram account (user) {#link-your-account}

Every user links their own Telegram account from **chat-ui → Settings →
Telegram**:

1. **Link Telegram** generates a one-time link
   `https://t.me/<bot>?start=pair_<code>` (plus a QR code), valid for
   `pairing_code_ttl_min` minutes. Generating a new one invalidates the
   previous one.
2. Open the link on your phone and tap **Start**: the bot redeems the code and
   links your Telegram account to your AION user. The settings page updates by
   itself.
3. An AION user has at most one Telegram account, and a Telegram account at
   most one AION user. Linking a new Telegram account replaces the previous
   one.

Rules:

- **Link security.** The link is a temporary credential: whoever opens it
  before it expires links *their own* Telegram to your user. Do not share it.
  The database only stores the SHA-256 of the code.
- **Bot access.** Users who are not linked can only use `/start`, `/help` and
  `/whoami`; any other message gets an invitation to link. The manager bot
  only replies in private chats.
- **Unlinking.** With `/unlink` in the bot or **Unlink** in the chat-ui (in
  that case the bot notifies the user on Telegram). It takes effect
  immediately: the link is re-read on every message.
- **Deleted user.** If the admin deletes an AION user, their link and codes
  are deleted too (FK `ON DELETE CASCADE`).
- **Audit.** Every action (code created, linked, unlinked) is recorded in
  `tg_audit`.
- **Tables.** `tg_links`, `tg_pairing_codes` and `tg_audit` are created by
  migration `t0g1l2k029` on existing installations, or when the channel
  starts on new databases.

## Manager bot and personal assistants {#roles}

- **Manager bot** (`manager_token`, one per installation): account linking
  (`/start`, `/me`, `/unlink`, `/whoami`) and assistant management
  (`/newbot`, `/mybots`, `/cancel`). **It does not chat with the agent**: to
  free text it replies with buttons that open the user's assistants, or
  reminds them they can create one with `/newbot`. Creating an assistant is
  never mandatory and never suggested automatically: it only starts when the
  user asks.
- **Personal assistants** (Phases 4/5): the only place where users chat with
  the agent, each with its own profile and project, accessible only to its
  owner (or to every linked user, for shared assistants).
- **chat-ui → Settings → Telegram**: link status and the list of assistants,
  each with an "Open" link. Telegram chats are in the sidebar, like other
  conversations.
- With `manager_chat=1` the manager chats again, as described in
  [Chatting with the agent](#chatting-with-the-agent).

## Create a personal assistant (Phase 4) {#personal-bots}

Every linked user can create their own bots from the manager bot (Telegram
"managed bots"), without opening @BotFather and without touching `.env`. This
requires **Bot Management Mode** on the manager (at startup the log reports
`can_manage_bots=True`).

- **`/newbot`.** A guided procedure: name → mode (personal or shared, see
  [Personal and shared assistants](#personal-and-shared)) → profile (only the
  ones the user may use) → project (if any) → summary. On confirmation, the
  **🤖 Create the bot** button appears: Telegram asks you to confirm the name
  and username (it must end with `bot`). Alternatively there is a link
  `t.me/newbot/<manager>/<username>`. The request is valid for 30 minutes;
  `/cancel` cancels it. During the procedure, what you type is the bot's name,
  not a question to the agent; any other command interrupts it.
- **Registration.** Telegram notifies the manager (`managed_bot_created` and
  `managed_bot`); AION fetches the token with `getManagedBotToken`, stores it
  **encrypted** in `tg_bots` (never in clear text in the database or logs),
  sets the bot's commands and descriptions, and restricts access to the owner
  (`setManagedBotAccessSettings`). The user receives "✅ @bot_name is ready".
- **Quota.** At most `max_bots_per_user` bots per user. A bot created outside
  the procedure (direct link) beyond the quota is registered but stays
  suspended.
- **`/mybots`.** List with status (being configured, active, suspended,
  error) and, for each bot: change profile and project, suspend/reactivate,
  "Retry configuration" if it is in error, delete.
- **Deletion.** Marks the bot as deleted, stops listening to it and revokes
  its token (`replaceManagedBotToken`; the new token is discarded). The
  revocation makes Telegram send a "token changed" update, which is ignored
  for a deleted bot (log: `update per il bot eliminato ... ignorato`). The Bot
  API cannot delete the bot: it stays visible on Telegram but no longer
  answers. To remove it completely, use @BotFather.
- **Later events.** If the token is regenerated in @BotFather, AION stores the
  new one. If the bot is transferred to another Telegram account, it is
  suspended and the old owner is notified.

## Personal and shared assistants {#personal-and-shared}

In `/newbot`, after the name, you choose the **mode** (it can be changed
later from `/mybots` → assistant):

| | 🔒 Personal | 👥 Shared |
|---|---|---|
| Who can write | only the creator | any AION user who has linked Telegram |
| AION identity of the turn | the creator's | **the writer's** (their permissions, memory, conversations) |
| Telegram access (`setManagedBotAccessSettings`) | restricted to the owner | open: AION does the check |
| Groups | no (leaves by itself) | **disabled for now**; with the flag on, only the creator can add it |
| Profile and project | the bot's | the bot's (see "Project in groups" below) |

- Someone who writes to a shared assistant without having linked Telegram is
  invited to do so.
- Only the creator can change the project (`/project`) and settings
  (`/mybots`).

:::info Groups are disabled (2026-11)
For now, assistants do not work in groups: `GROUPS_ENABLED = False` in
`src/channels/telegram/groups.py`. An assistant added to a group, or that
receives a message from a group, writes "AION assistants are not available in
groups yet" and leaves; the group menu (`/ask`) is not registered and the
texts of `/newbot` and `/mybots` do not mention groups. "Shared" therefore
only applies in private chats. The group code is kept and its tests run with
the flag on.

Before re-enabling groups, the group context must be removed from the stored
user message (see "Group context" below): now that Telegram chats are chat-ui
sessions, that prefix would show up in the history. It should be passed to the
turn as system context instead. The items below describe the behaviour with
the flag on.
:::

### Behaviour in groups (when enabled)

- **Project in groups (decision 2026-10-30).** In a private chat with a shared
  assistant, access is checked per person: whoever is not a member of the
  bot's project is refused. **In groups**, instead, the project is used with
  the **creator's permissions**: anyone in the group can ask questions and
  read the answers, including project data, because everyone in the group sees
  the answers anyway. Whoever adds the bot (only the creator) is responsible
  for putting it only in groups whose members may see that data, for example a
  dedicated group. Conversation and personal memory stay with the writer; if
  the creator loses access to the project, the group gets a refusal.
  Implementation: per-conversation, per-turn delegation
  (`src/runtime/project_access_delegation.py`), read by the pipeline's access
  check, by the context and tools of the SQL memory and by the pre/post-turn
  hooks; without delegations, the core behaves as before.
- **Groups.** The assistant only answers messages addressed to it: a mention
  `@bot_name`, a reply to one of its messages, or `/ask question`. The answer
  quotes the question and is visible to everyone; there is no animated
  preview (`sendMessageDraft` only works in private chats). Each participant
  has their own AION conversation (`/new` restarts it), marked with
  `metadata.telegram_chat = <group title>`.
- **Group context.** Questions and answers addressed to the assistant in the
  group are stored in `tg_group_messages` (last 50 per group). With each new
  question, the agent receives, before the text, the questions from **other**
  participants asked after the writer's last question (at most 8, truncated),
  plus the group title and the name of the person asking. This prefix also
  ends up in the message stored in the asker's conversation.
- **Joining groups.** If a shared assistant is added by someone other than the
  creator, or if the assistant is personal, it writes a message and leaves
  the group.
- **Privacy mode (verified).** With Telegram's privacy mode on (the default),
  in groups the bot only receives commands addressed to it
  (`/ask@bot_name question`, which the `/` menu inserts automatically) and
  replies to its messages: **`@bot_name question` mentions do not arrive**.
  The Bot API cannot change this. To enable mentions: **make the bot a group
  administrator** (administrators receive all messages; the assistant still
  only answers those addressed to it), or turn off privacy mode in @BotFather
  (Bot Settings → Group Privacy) and add the bot to the group again. The
  welcome message explains how to ask questions in each case; when promoted
  to administrator, the assistant announces that it now also answers
  mentions.

## Chatting with the agent (Phase 3) {#chatting-with-the-agent}

A linked user writes to the bot and the AION agent answers **on behalf of
their AION user**: same memory, same permissions on profiles and projects,
same pipeline as the chat-ui. This applies to personal assistants and, only
with `manager_chat=1`, to the manager bot (`/profile` and `/project` are
manager commands).

- **Conversations = AION sessions.** Each Telegram chat points to an AION
  conversation (`tg_sessions`: bot, chat, thread, user → conversation), which
  keeps the context until you use `/new`, like `/nuova` on WhatsApp. It is a
  real session, indistinguishable from a chat-ui one: marked
  `metadata.source = "telegram"`, titled after the first message, with
  uploads, generated files and session memory. The turn uses the same logic
  as WhatsApp, in `src/channels/session_turn.py`:
  - **chat-ui.** The conversation appears in the sidebar right away with the
    Telegram icon and can be continued from there: same history, you can
    write, regenerate, rate. The final reply on Telegram ends with the link
    "💬 Continue on AION" (only if `AION_PUBLIC_CHAT_URL` is not `localhost`).
  - **Turn can be followed live.** While the agent answers on Telegram, the
    turn is registered as a background run (`_background_runs` + redis
    `stream_active`): opening the conversation in the chat-ui shows the
    streaming live (`/v1/chat/stream/reconnect`). Stopping from the chat-ui
    also stops the reply on Telegram.
  - **Reasoning.** The channel's `default_thinking_level`, copied into
    `metadata.thinking_enabled` / `metadata.reasoning_effort` on every turn.
  - **Attachments.** The agent receives the message's files ("new") and all
    the session's earlier uploads ("historical"), as in the chat-ui.
  - **Generated files.** Files created by the agent during the turn (CSV,
    PDF, charts...) come back to the chat: jpeg/png up to 10 MB as photos,
    everything else as documents (bot limit: 50 MB). At most
    `max_outbound_files` per turn; the rest stay in the session.
- **Profile and project.** Initial profile `default_profile`; `/profile` and
  `/project` only show what the user may use. Changes apply from the next
  message, in the same conversation.
- **Streaming.** In private chats the bot uses `sendMessageDraft` (animated
  preview, then the final message). If Telegram refuses it, the bot switches
  by itself to sending a message that is updated every
  `stream_edit_interval_ms`; the log shows `sendMessageDraft non disponibile`.
- **Tools.** While answering, the list of called tools is shown (⏳ running,
  ✓ succeeded, ✗ error), even for tools that take a few milliseconds; the
  final message keeps a collapsible "🔧 Tools used" box. Turn it off with
  `show_tools=0`.
- **On-demand tools.** With `AION_DEFER_TOOL_GROUPS=1` (AION default) some
  groups, including `web_research`, are only loaded if the model calls
  `activate_tool_group`. If it does not, it answers that it has no web search:
  this is the same behaviour as the chat-ui, not a channel issue.
- **Formatting.** The agent's Markdown becomes Telegram HTML: bold, italic,
  code, links, quotes, lists; tables stay aligned in a monospace block.
  Replies over 4096 characters are split into several messages without
  breaking code blocks. (With `rich_messages=1`, see
  [Replies, stop and attachments](#replies-stop-attachments).)
- **Queue.** At most `max_concurrent_jobs` turns at once across all users;
  two quick messages in the same chat run one after the other. Whoever waits
  gets "⏳ Queued (position N)".
- **Stop and limits.** `/stop` interrupts the reply (the part already written
  stays, with "⏹️ Reply interrupted"). After `turn_timeout_sec` the turn is
  stopped.
- **AION restart.** Running turns are interrupted and the user receives "AION
  is restarting". A process crash during a turn loses that reply: the
  question must be asked again.
- **Photos, documents and voice messages** are covered in
  [Replies, stop and attachments](#replies-stop-attachments).

## Chatting on personal bots (Phase 5) {#personal-bot-chat}

- **Listening.** At startup AION starts listening (long polling) to all
  **active** personal bots; bots that are created, reactivated or given a new
  token start (or restart) listening immediately, without a restart.
  Suspended, deleted and errored bots are not listened to. In the log:
  `N bot personali in ascolto`, `bot @x in ascolto`.
- **Cost.** Listening to a bot means keeping a `getUpdates` request open and
  waiting: no CPU and no model calls. Work only starts when a message arrives
  and goes through the **same queue** as the manager bot
  (`max_concurrent_jobs` applies to all bots together). The conversation and
  session are created at the first message; idle MCP servers are shut down by
  the core after `AION_MCP_POOL_IDLE_SEC` and recreated at the next message.
- **Configuration.** The agent answers with the bot's profile and project,
  re-read on every message: a change from `/mybots` applies from the next
  message. Conversations belong to the owning AION user, with
  `metadata.telegram_bot = <username>`, and appear in the chat-ui sidebar.
- **Bot commands.** `/start`, `/help`, `/new`, `/stop`, `/status` (profile
  and project), `/project` (changes the bot's project, like `/mybots`).
- **Access.** Only the owner, with the Telegram account linked to the same
  AION user that created the bot (shared assistants: see
  [Personal and shared assistants](#personal-and-shared)). Telegram itself
  already restricts access to the owner (`setManagedBotAccessSettings`).
- **Errors.** If Telegram rejects the token (401), the bot goes into error
  state, stops listening, and the owner is notified on the manager bot.
- **Single instance.** Each token has a single consumer per process. Two AION
  instances on the same database get 409 from Telegram (`conflitto 409` in
  the log) and interfere with each other: run only one.

## Replies, stop and attachments (Phase 7) {#replies-stop-attachments}

- **Rich format** (`sendRichMessage`, Bot API 10.x): the agent's Markdown is
  sent as is (GitHub-style Markdown): **real tables**, code with language,
  headings, lists. As in the chat-ui, with `show_reasoning=1` the reply starts
  with "💭 Reasoning" (collapsible) and ends with "🔧 Tools used". While the
  model is reasoning, the preview shows "💭 Thinking…". Preview in private
  chats with `sendRichMessageDraft`, in groups with an edited rich message.
- **Automatic HTML fallback.** If Telegram refuses the rich format for a bot
  (log: `messaggi rich non disponibili`), that bot switches to the previous
  HTML format until restart. A text Telegram cannot parse, or a reply over
  ~30,000 characters, uses HTML (split into several messages) for that reply
  only.
- **Stop button.** In private chats, the animated preview shows Telegram's
  native stop button (`can_stop`): pressing it sends the
  `stopped_message_generation` update and AION interrupts the turn, like
  `/stop` (the part already written stays, with "⏹️ Reply interrupted"). In
  groups, use `/stop`.
- **Attachments.** Documents and photos sent to the assistant are downloaded,
  saved in the conversation's `uploads/` like chat-ui uploads (Word conversion
  and automatic indexing) and attached to the question. With a caption, the
  question starts right away. **Without a caption** (Telegram on Android sends
  documents without letting you write one) the bot confirms "📎 Received …,
  now tell me what you want me to do" and attaches the files to the **next
  message** from the same person (within 15 minutes; `/new` discards them; an
  AION restart forgets them). Several files sent in a row accumulate; photo
  albums are collected together with their caption. Limit: 20 MB per file
  (Telegram's limit for bots; above it, the bot warns). In groups, only if the
  attachment is addressed to the bot (reply to one of its messages, or caption
  with `/ask@bot_name`).
- **Voice messages.** The Bot API offers no transcription (Telegram Premium's
  transcription only happens in the user's app): the bot asks the user to type
  the question.
- **Confirmation for dangerous tools** (item 7.5 of the plan): not
  implemented. It needs an approval mechanism in the AION core (today
  `src/security/approval_manager.py` is an unused stub).

---

## Administration (Phase 8) {#administration}

**admin-ui → Telegram** (`/telegram`, *Operations* group):

- **Assistants.** All bots of the installation (never the tokens): name,
  username, status, mode, listening or not, owner (AION user and Telegram
  account), profile, project, last use. Actions: **Suspend / Reactivate**
  (the owner gets a notice on the manager), **Delete** (revokes the token;
  confirm by typing the username) and **Reassign**. Without an active gateway,
  deletion disables the bot in AION but cannot revoke the token: the page
  says so.
- **Reassign** is for when a bot is transferred to another Telegram account
  in @BotFather: AION suspends it and records the new account; if that
  account has linked AION, the admin confirms and the bot moves to that AION
  user, becomes active again, and the new owner is notified.
- **Quotas.** For each user with Telegram linked (or with assistants) you can
  set a maximum number of assistants different from `max_bots_per_user`;
  empty = default value. `0` prevents creating any.
- **Log.** The channel's latest operations (`tg_audit`): links, creations,
  configuration and mode changes, suspensions, deletions, token rotations,
  reassignments, quotas.
- **Channel policy** (admin-ui → Telegram → **Policies** → Personal
  assistants): `allowed_profiles` / `allowed_projects`, chosen from two
  checkbox lists. It is a strict allowlist: only the selected profiles and
  projects appear in `/newbot`, `/mybots`, `/profile`, `/project`; with an
  empty list nothing is allowed, and profiles/projects created later must be
  enabled explicitly. If an assistant already uses a profile or project that
  is not allowed, every message is refused with "not available on Telegram
  (administrator policy)". The panel warns if no profile is allowed or if the
  suggested profile (`default_profile`) is not among the allowed ones.
- **Telegram chats are regular AION sessions.** They appear in the chat-ui
  sidebar (with the Telegram icon) and can be continued from there, like
  WhatsApp ones; see [Chatting with the agent](#chatting-with-the-agent).

## Assistant lifecycle (Phase 6) {#lifecycle}

- **Telegram account unlinked** (`/unlink` or chat-ui → Settings →
  Telegram): active assistants are suspended (reason "Telegram account
  unlinked") and stop listening; the unlink message lists them. When the user
  **re-links the same account**, they become active again by themselves. With
  a different Telegram account they stay suspended: for Telegram, the owner is
  still the account that created them. Assistants suspended manually or for
  quota are not touched.
- **AION user deleted** (admin-ui → Users): before the deletion, AION stops
  listening to the user's assistants, **revokes their tokens** and removes
  link, sessions, codes and pending requests. With the gateway off, the bots
  are still disabled in AION, but the tokens cannot be revoked (log:
  `eliminato senza revoca del token`).
- **🔑 Regenerate token** (`/mybots` → assistant): new token via
  `replaceManagedBotToken`, stored encrypted, listening restarted once; the
  old token stops working.
- **Periodic check** every `reconcile_interval_min` minutes, for each
  assistant that is not deleted:
  - updates name and username if they changed on Telegram;
  - an assistant in error that answers again becomes active (the owner is
    notified);
  - token rejected: if the manager obtains a new token (an unnotified change)
    it stores it and restarts; if Telegram no longer knows the bot (deleted in
    @BotFather) it marks it deleted and notifies the owner;
  - network errors: nothing changes, it retries on the next round.

## Webhook mode {#webhook-mode}

With **Update delivery = Webhook** (`delivery_mode=webhook`, admin-ui →
Telegram → **Connection**) every bot of the channel (the manager and each
active personal assistant) registers on Telegram (`setWebhook`) the URL

```
<public API URL>/v1/channels/telegram/webhook/<bot id>
```

and Telegram sends updates there with a `POST`. The public URL is the same one
used for the WhatsApp callback (`AION_OAUTH_REDIRECT_BASE_URL` /
`AION_PUBLIC_API_URL`); behind Caddy it is
`https://<domain>/api/v1/channels/telegram/webhook/<bot id>`. Telegram only
accepts **HTTPS** on ports 443, 80, 88 or 8443 and a host reachable from the
Internet (no `localhost`).

- **Authentication**: each webhook has a `secret_token` derived from the bot
  token (HMAC, nothing to store); Telegram sends it back in the
  `X-Telegram-Bot-Api-Secret-Token` header and the endpoint
  (`src/api/v1/telegram_webhook.py`) rejects requests without it with 401.
- **Immediate response**: the endpoint answers 200 as soon as it accepts the
  update and the turn runs in the background, so Telegram does not retry
  during long turns. Duplicate updates (`update_id` already seen) are ignored.
  If the bot is not listening yet (gateway restarting) it answers 503 and
  Telegram retries.
- **Automatic registration**: the webhook is registered every time the
  gateway starts (including after a save in admin-ui), so it follows a
  changing URL by itself, such as the test tunnel's. An assistant that is
  suspended, deleted or given a new token loses its webhook; when AION shuts
  down, webhooks stay and Telegram queues updates until restart. When
  switching back to `polling`, the pollers remove the webhook at startup.
- **Trade-off**: unlike polling, an update still being processed when AION
  stops is not redelivered (it was already acknowledged with the 200). For
  production, polling remains the more robust choice.
- **Diagnostics**: the Status box in admin-ui → Telegram shows the mode, the
  URL AION registers, any problem (public URL missing or not HTTPS,
  `setWebhook` refused) and what Telegram reports (`getWebhookInfo`:
  registered URL, pending updates, last delivery error).

### Local testing with the tunnel

`scripts/whatsapp-tunnel.sh` opens a Cloudflare quick tunnel
(`https://<random>.trycloudflare.com`) to Caddy and restarts the stack with
the public URLs pointing at the tunnel; it works for Telegram too.

1. Run `scripts/whatsapp-tunnel.sh` (with `DOMAIN=:80` in `.env`);
2. admin-ui → Telegram → Connection → **Update delivery = Webhook** → Save;
3. in the Status box, the webhook URL must be the tunnel's, and "Pending
   updates" must drop to 0 after a message to the bot.

The tunnel URL changes every time the script starts: the backend is recreated
and registers the new webhook by itself, with no manual steps. Once the
tunnel is closed, switch back to `polling` (or run the script again),
otherwise Telegram piles up updates on an unreachable URL.

## Encryption key rotation {#key-rotation}

The channel configuration and the bot tokens are encrypted with
`AION_CREDENTIAL_ENCRYPTION_KEY` (the same key as the per-user MCP
credentials). Changing the key makes the saved values **unreadable**: the
channel restarts disabled until the configuration is saved again from
admin-ui → Telegram (manager token included), and the bots go into error
("token cannot be decrypted"). Recommended procedure:

1. New key: `openssl rand -hex 32`, set in `.env` (not in admin-ui, where it
   is masked).
2. Restart AION, then re-enter the configuration in admin-ui → Telegram and
   save.
3. Bots in error recover by themselves at the periodic check if the manager
   can obtain the token again (`getManagedBotToken`, which stores it encrypted
   with the new key); otherwise the owner uses `/mybots` → **🔑 Regenerate
   token** or **Retry configuration**.
4. Per-user MCP credentials encrypted with the old key must be re-entered by
   the users.

## Guaranteed behaviour {#guaranteed-behaviour}

- **AION startup does not depend on Telegram.** The connection happens in the
  background; network or proxy errors are retried with backoff (up to 60 s).
- **Token rejected (401).** The gateway stops with an error in the logs,
  while AION keeps working.
- **No update lost on stop.** The offset acknowledged to Telegram never goes
  past an update still being processed; at shutdown, handlers are given the
  grace period and only completed work is acknowledged. On restart,
  unacknowledged updates are redelivered (at most one duplicate, never a
  loss).
- **Messages sent while AION is down** stay queued on Telegram (up to 24 h)
  and are processed on restart.
- **Tokens never appear in the logs**, not even inside Bot API URLs in
  exceptions.
- **409 conflict** (two instances polling the same token): logged and
  retried. Do not run two AION instances with the same token.

## Troubleshooting {#troubleshooting}

| Symptom | Likely cause | What to do |
|---|---|---|
| No `telegram:` lines in the logs | channel not enabled in admin-ui → Telegram | Enable it and save: the gateway starts without a restart |
| `configurazione salvata non decifrabile` in the logs (saved configuration cannot be decrypted) | `AION_CREDENTIAL_ENCRYPTION_KEY` changed or missing | Restore the key, or reconfigure and save from admin-ui → Telegram |
| `token rifiutato da Telegram (401)` for the manager | wrong or revoked manager token | admin-ui → Telegram → Connection → **Test token**, paste the new one |
| `can_manage_bots=False` | Bot Management Mode off | @BotFather Mini App → bot → Mode Settings → Bot Management Mode |
| `/newbot` says the encryption key is missing | `AION_CREDENTIAL_ENCRYPTION_KEY` missing in production | Set it in `.env` and restart |
| `conflitto 409` in the logs | two AION instances on the same token | Keep only one |
| The bot in a group does not answer mentions | Telegram privacy mode | Use `/ask@bot_name` or make the bot a group administrator (only relevant when groups are enabled) |
| The assistant leaves a group right after being added | groups are disabled (default), the assistant is personal, or it was added by someone other than the creator | With groups disabled this is expected; otherwise make it shared (`/mybots`) and have the creator add it |
| "not available on Telegram (policy…)" | profile/project not allowed by the channel policy | admin-ui → Telegram → Policies → tick the profile/project in the allowed lists |
| Assistant "suspended: owner changed" | bot transferred to another account in @BotFather | admin-ui → Telegram → **Reassign** (the new account must have linked AION) |
| `messaggi rich non disponibili` | the bot does not support rich messages | No action: HTML is used; set `rich_messages=0` to force it |
| The docs site build fails on this file | `<word>` outside a code block (MDX) | Put it in backticks |

---

## Manual test checklists {#manual-test-checklists}

These checklists were written phase by phase during development. They are
listed from the most recent to the oldest; some early-phase steps describe
behaviour that later phases changed (marked below).

### Phase 8 — administration

1. admin-ui → **Telegram**: all assistants appear with owner, mode, status
   and last use.
2. **Suspend** an assistant: it stops answering and the owner gets the
   notice; **Reactivate**: it comes back.
3. **Delete** (typing the username): it disappears from the list (visible
   with "Show deleted").
4. Quotas: set `0` for a user and try `/newbot` with that account: it is
   refused; clear the quota and try again.
5. Log: the operations you just did appear.
6. admin-ui → Telegram → Policies: untick a profile in the allowed profiles
   and save: it disappears from `/newbot`, and an assistant that uses it
   answers "not available on Telegram".
7. Open a Telegram chat in the chat-ui and write a message: the agent answers
   in the same conversation.
8. admin-ui → Settings: `AION_CREDENTIAL_ENCRYPTION_KEY` is no longer
   readable.

### Phase 7 — replies, stop, attachments

1. Ask an assistant "make me a table with 3 cities and their population": a
   real table arrives; at the end, the collapsible sections (tools, and
   reasoning if the model reasons).
2. Ask a long question and press the stop button on the preview: the reply
   stops with "⏹️ Reply interrupted".
3. Send a PDF with the caption "summarise it": the agent reads it; in the
   chat-ui (sidebar) the chat shows the attachment. A later question about the
   PDF, without sending it again, works (historical uploads).
4. Ask for a file ("export the data to CSV"): it arrives as a document on
   Telegram and is in the chat-ui session. With more than
   `max_outbound_files` files, "📁 N more files are available on AION"
   arrives.
5. Send a photo without a caption: the agent describes it.
6. Send a file over 20 MB: the bot warns about the limit.
7. Send a voice message: the bot asks you to type the question.
8. In a group: reply to an assistant message with a photo and a caption: it
   answers quoting it (only with groups enabled).
9. With `rich_messages=0`, replies go back to HTML.

### Shared assistants

1. `/newbot` → name → **👥 Shared** → profile → create. The "ready" message
   states the mode.
2. A colleague with Telegram linked to **their** AION user writes to the
   assistant privately: it answers with the colleague's permissions; in the
   colleague's chat-ui, the chat appears in the sidebar.
3. An unlinked Telegram account writes to the assistant: it is invited to
   link.
4. The colleague tries `/project`: "Only the creator…".
5. **With groups disabled (default)**: add the assistant to a group; it
   writes "AION assistants are not available in groups yet" and leaves.
   Steps 5b–8 only apply with `GROUPS_ENABLED = True`.
   - 5b. The creator adds the assistant to a group: welcome message. Another
     member who tries to add it to their own group: the assistant writes
     "Only the creator…" and leaves.
6. In the group: "hi everyone" → no answer; `/ask@bot_name question` or a
   reply to one of its messages → an answer that quotes the question. Make the
   bot an administrator: "Now I also answer when you mention me" arrives and
   `@bot_name question` works too.
7. A second member asks "and what about …?" replying to the assistant: the
   answer takes the other member's previous question into account.
8. `/mybots` → assistant → **🔒 Make personal**: in the group, at the next
   mention, the assistant leaves.

### Phase 6 — lifecycle

1. `/unlink` on the manager: the message lists the suspended assistants;
   writing to an assistant gets no answer.
2. Re-link from the chat-ui (same Telegram account): the link message says
   "Assistants active again" and the assistant answers again.
3. Unlink again from the chat-ui: on Telegram, the notice with the suspended
   assistants arrives.
4. `/mybots` → assistant → **🔑 Regenerate token**: the assistant keeps
   answering; the log has a single `bot @... in ascolto` after the rotation.
5. Rename the assistant in @BotFather; with `reconcile_interval_min=1`,
   within a minute `/mybots` shows the new name.
6. Delete an assistant in @BotFather: at the next check, "no longer exists on
   Telegram" arrives and it disappears from `/mybots`.
7. Create a test user with an assistant, then delete the user from admin-ui →
   Users: the assistant stops answering and the log shows
   `utente ... eliminato, 1 assistenti revocati`.

### Manager without chat

1. Rebuild backend and chat-ui (`manager_chat` absent or `0`).
2. On the manager, the command menu no longer has `/new`, `/profile`,
   `/project`, `/stop`; `/help` shows "Personal assistants" and "Account".
3. Write "hi" to the manager: no agent answer, but "💬 assistant name"
   buttons that open your assistants (or the `/newbot` suggestion if you have
   none).
4. `/mybots`: next to each active assistant there is "💬 Open".
5. `/newbot` → the default profile appears first with ⭐.
6. chat-ui → Settings → Telegram: "Your assistants" box with status,
   profile, project and "Open"; Telegram chats show the assistant (`@...`) or
   "management bot".

### Phase 5 — personal bot chat

1. Rebuild the backend; in the log: `1 bot personali in ascolto` and
   `bot @aonasabot in ascolto`.
2. Open `@aonasabot`: `/start` answers with name, profile and project.
3. Write a question: the agent answers with the bot's profile (tools visible
   as on the manager).
4. `/status` shows the configuration; `/project` changes the project and
   `/mybots` on the manager reflects it.
5. From the manager, `/mybots` → change profile → the next question on the bot
   uses the new profile.
6. `/mybots` → Suspend → the bot no longer answers; Reactivate → it answers
   again, without a restart.
7. Question on the manager and on the personal bot almost at the same time:
   the second shows "⏳ Queued".
8. chat-ui: the personal bot's chats appear in the sidebar with the Telegram
   icon and can be continued from there.
9. Restart the backend: the personal bot starts listening again by itself.

### Phase 4 — personal bot creation

1. Rebuild the backend; in the log: `bot manager @... can_manage_bots=True`.
2. On the manager, `/help`: `/newbot`, `/mybots`, `/cancel` appear.
3. `/newbot` → type a name → choose a profile → (project) → **✅ Create the
   bot**.
4. Press **🤖 Create the bot** under the input field and confirm in Telegram.
5. Within a few seconds "✅ @..._bot is ready" arrives with profile and
   project; the keyboard disappears.
6. Open the new bot: the menu has `/new`, `/project`, `/stop`, `/status`,
   `/help` and the AION description.
7. `/mybots` → the bot is 🟢 active; try Profile, Project,
   Suspend/Reactivate.
8. `/newbot` → type "hi" as the name → `/cancel`: no agent answer during the
   procedure.
9. Delete the bot from `/mybots`: it disappears from the list; optionally
   delete it in @BotFather.
10. Database: `SELECT id, username, status, length(token_enc) FROM tg_bots;` —
    the token is not readable.

### Phase 3 — chatting with the agent (manager chat)

Prerequisite: `docker compose up -d --build backend chat-ui`; Telegram account
already linked (Phase 2). These steps exercise chat on the manager bot, which
today requires `manager_chat=1`.

1. [ ] In the backend logs: `gateway avviato`, no migration errors
       (`t1s2e3s030`).
2. [ ] Tapping `/` in the bot, the menu shows new, profile, project, stop,
       start, help, me, unlink, whoami.
3. [ ] Write a long question (e.g. "explain in 10 points how a relational
       database works"): "Thinking…"/"typing…" appears, the text grows
       progressively, then the final formatted message remains.
4. [ ] Ask a follow-up ("and the second point in detail?"): the answer takes
       the previous one into account.
5. [ ] chat-ui: the conversation is in the sidebar with the Telegram icon and
       the title of the first question. Open it during a long answer: the
       streaming shows live. Write a message from the chat-ui: it answers in
       the same conversation, and the next question from Telegram takes it
       into account.
6. [ ] A question that needs a tool (e.g. web search): the "🔧 …" line
       appears while it is used.
7. [ ] `/stop` during a long answer: "⏹️ Stopping…" and the answer closes
       with "Reply interrupted".
8. [ ] Two quick messages one after the other: the second gets "⏳ Queued"
       and is answered after the first.
9. [ ] `/profile` → buttons with the allowed profiles (✓ on the current one)
       → choose another → the next answer uses that profile. `/project` →
       same, including "No project".
10. [ ] `/new` → "New conversation"; the next question does not remember the
        context; the chat-ui sidebar now has two chats.
11. [ ] Send a photo or a voice message. Originally (Phase 3) both got "For
        now I can only answer text messages"; since Phase 7, photos are
        handled as attachments and voice messages get a request to type the
        question.
12. [ ] Restart the backend during an answer: "AION is restarting: reply
        interrupted" arrives.

### Phase 2 — account linking

Prerequisite: rebuild backend and chat-ui
(`docker compose up -d --build backend chat-ui`).

1. [ ] In the backend logs: `gateway avviato` and `can_manage_bots=True`, no
       migration errors.
2. [ ] From the phone, **before linking**: `ciao` → "This Telegram account is
       not linked to AION…"; `/whoami` works; `/me` → the same "not linked"
       message.
3. [ ] chat-ui → Settings: there is a **Telegram** entry with status "Not
       linked".
4. [ ] **Link Telegram** → the QR code, "Open in Telegram" and the expiry
       time appear.
5. [ ] Scan the QR code (or open the link) from the phone → **Start** → the
       bot answers "✅ Account linked to AION user …"; within a few seconds the
       page shows "Linked" with @username and dates.
6. [ ] From the phone: `/me` shows your AION user; `ciao` → "Your account is
       linked…".
7. [ ] Open the same link again → "This link has already been used".
8. [ ] chat-ui → **Unlink** → confirm → the bot writes "unlinked from AION
       from the chat-ui"; `ciao` again gets "not linked".
9. [ ] Re-link, then `/unlink` from the phone → the page, once reloaded, goes
       back to "Not linked".
10. [ ] Generate a link and let it expire: the page shows "The link has
        expired…"; opening it from the phone → "Linking link expired".
11. [ ] (If you have a second Telegram account) link your user with account
        A, then open a new link with account B: B becomes the linked one and A
        goes back to "not linked".

### Phase 1 — gateway

Prerequisites: items 1–5 and 7 of § 1 of the plan (manager bot created,
token saved in admin-ui → Telegram).

1. [ ] With the channel not enabled, AION starts as before: no
       `aion.telegram` lines in the logs.
2. [ ] Once enabled and saved from admin-ui → Telegram (without restarting
       AION), `gateway avviato` and the `can_manage_bots=…` line appear.
3. [ ] From the phone: `/start` gets the greeting in under 2 s.
4. [ ] `/whoami` returns your user id: note it down (prerequisite 6 of the
       plan).
5. [ ] `/help` shows the list; the client's command menu (`/` key) contains
       start, help, whoami.
6. [ ] Free text in a private chat gets "For now I only answer commands…"
       (Phase 1 behaviour; today the manager answers with the assistant
       buttons, see "Manager without chat").
7. [ ] Stop AION (Ctrl+C): in the logs, `offset confermato allo shutdown` (if
       there were updates) and `gateway fermato`.
8. [ ] With AION stopped, send `/whoami` and a text; restart AION: both get
       an answer.
9. [ ] Restart AION again without writing anything: no duplicate answer.
10. [ ] Wrong token saved in admin-ui → Telegram: AION starts anyway and logs
        `rifiutato da Telegram (401)`.
