---
sidebar_position: 4
title: Web search and page fetch
description: Native tools web_search and web_fetch_page (Tavily, Brave, SearXNG, Scrapling), AION_* variables and profile enablement.
---

# Web search and page fetch

AION can expose two Haystack **in-process** (non-MCP) tools, defined in the registry `config/native_tool_registry.yaml` (and optional overlay `config/native_tool_registry.local.yaml`):

- **`web_search`**: querying of one or more providers (Tavily, Brave Search API, SearXNG) with deterministic fallback.
- **`web_fetch_page`**: download of the text content of a single URL (preference [Scrapling](https://github.com/D4Vinci/Scrapling) `Fetcher`, optional stealth, fallback `httpx`).

## Enablement by profile

In the profile YAML (e.g. `config/profiles/research_docs.yaml`):

```yaml
native_tool_groups:
  - web_research
skills:
  - web_research_protocol   # recommended: citations and responsible use
```

`native_tool_groups` is **separate** from `mcp_servers`: it lists only bundles defined in `native_tool_registry.yaml` (merge with `native_tool_registry.local.yaml` if present).

## Environment variables (`.env`)

| Variable | Role |
|-----------|--------|
| `AION_NATIVE_TOOL_REGISTRY_PATH` | YAML registry path (default `config/native_tool_registry.yaml`) |
| `AION_NATIVE_TOOL_REGISTRY_LOCAL_PATH` | Optional overlay |
| `AION_WEB_SEARCH_TAVILY_ENABLED` | `1` to use Tavily |
| `AION_WEB_SEARCH_BRAVE_ENABLED` | `1` to use Brave |
| `AION_WEB_SEARCH_SEARXNG_ENABLED` | `1` to use SearXNG |
| `AION_TAVILY_API_KEY` | Tavily API key |
| `AION_BRAVE_SEARCH_API_KEY` | Brave key (`X-Subscription-Token`) |
| `AION_SEARXNG_BASE_URL` | Instance base URL (e.g. `https://search.example.org`, without trailing slash) |
| `AION_WEB_SEARCH_DEFAULT_PROVIDER` | `tavily`, `brave` or `searxng` |
| `AION_WEB_SEARCH_FALLBACK_ORDER` | CSV of fallback providers |
| `AION_WEB_SEARCH_MAX_RESULTS` | Results limit (1–20) |
| `AION_WEB_SEARCH_TIMEOUT_SEC` | Search HTTP timeout |
| `AION_WEB_FETCH_TIMEOUT_SEC` | Page fetch timeout |
| `AION_WEB_FETCH_MAX_BYTES` / `AION_WEB_FETCH_MAX_CHARS` | Response size limits |
| `AION_WEB_FETCH_ALLOWLIST_REGEX` | If not empty, only URLs matching the regex |
| `AION_SCRAPLING_STEALTH_ENABLED` | `1` to attempt `StealthyFetcher` when `prefer_stealth=true` |
| `AION_TAVILY_SEARCH_DEPTH` | `basic`, `advanced`, `fast`, `ultra-fast` |

Complete values and comments: [`.env.example`](../../.env.example) in the root of the repository.

## Allowlist organizational and user filter (chat)

| Variable | Role |
|-----------|--------|
| `AION_WEB_SEARCH_ALLOWED_HOSTS` | CSV of hosts allowed by the organization (e.g. `docs.python.org,github.com,*.wikipedia.org`). Normalization: lowercase; `www.` prefix ignored in matching. |
| `AION_WEB_SEARCH_ENFORCE_GLOBAL_ALLOWLIST` | If `1` and the previous list is **non-empty**, every `web_search` and `web_fetch_page` is limited to those domains. The client can send `web_search_restrict_hosts` (array) to further **restrict**; if a user host is not within the org allowlist → JSON error `host_not_in_org_allowlist` without network calls. If the user does not send hosts, only the org ceiling applies. |
| `AION_WEB_SEARCH_REQUIRE_CLIENT_OPT_IN` | If `1`, web search is considered **disabled** until the client explicitly sends `web_search_enabled: true` (POST `/chat` or `/v1/chat/stream`). |

**Effective merge (backend):** calculated per request via `contextvars` set in `AgentPipeline.run_stream` starting from the JSON body (`web_search_enabled`, `web_search_restrict_hosts`, max 20 hosts).

**Providers:** with a non-empty effective list, **Tavily** receives `include_domains` only for entries without wildcards (the other patterns remain covered by the URL post-filter). **Brave** and **SearXNG** do not expose a reliable native equivalent: a **post-filter** is applied to the results, as for Tavily, after the response.

## `web_fetch_page` and filter priority

Order applied on the requested URL:

1. `http://` / `https://` scheme
2. Effective host allowlist (org + user as above), if not empty
3. `AION_WEB_FETCH_ALLOWLIST_REGEX`, if not empty (match on the full URL)

All steps must be satisfied.

In **Admin → Settings**, the **Web search** section allows setting toggles, keys, **organizational host allowlist** (`AION_WEB_SEARCH_ALLOWED_HOSTS`), **enforce**, and **client opt-in** without manual editing of the file. Sensitive keys are **masked** on read (`GET /admin/settings`); on save, they are not overwritten if the sent value is the placeholder `***`.

In the **chat-ui**, **+** menu → **Web search** (switch) and **Controlled WEB search…** (host modal) send `web_search_enabled` and `web_search_restrict_hosts` on each POST `/chat`; the state can be persisted in the browser-side `localStorage`.

After modifications to the `.env`, it is recommended to **restart the API backend**.

## SearXNG

The instance must have the output `format=json` enabled (see [SearXNG API documentation](https://docs.searxng.org/dev/search_api)).

## Scrapling and Docker

`pip install "scrapling[fetchers]"` enables the advanced HTTP fetcher; stealth mode requires a browser and heavily increases image size and resources. In production, HTTP/httpx is recommended, and stealth only if necessary.

## Setup and upgrade scripts

- `./scripts/setup-aion-env.sh` (wizard): optional **Web search** block after OCR.
- `./scripts/upgrade-aion.sh`: append of missing keys via `upgrade_core.py` (`_ensure_web_search_env_keys`), visible with `--dry-run`.

## Legal notes

Respect ToS of providers and target sites; the tool does not replace human judgment on what is lawful to scrape in a given context.
