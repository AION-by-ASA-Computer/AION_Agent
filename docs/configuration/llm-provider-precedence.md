---
sidebar_position: 8
title: LLM provider and API key precedence
description: Which endpoint, model and API key every AI feature (chat, Deep Research, memory extraction, probes) uses, and how to check them.
---

# LLM provider and API key precedence

Every AI feature resolves **URL, model and API key together**, from one source,
through `resolve_llm_credentials()` in `src/runtime/llm_adapter.py`:

1. **Default LLM provider in the DB** (admin-ui → LLM providers): the row with
   `is_default=1`, else the first enabled row of the tenant. Its API key is the
   one saved in the admin panel (stored encrypted, decrypted with
   `AION_CREDENTIAL_ENCRYPTION_KEY`). Only when that row has no key is
   `AION_LLM_API_KEY` used.
2. **`.env` only** (no provider row): `AION_API_URL`, `AION_MODEL`,
   `AION_LLM_API_KEY`.

A provider explicitly selected in the chat (`llm_provider_name`) uses that
provider's own URL, model and key.

| Feature | Code path |
| :--- | :--- |
| Chat agent (default generator) | `src/main.py` → `_finish_get_agent_build` |
| Deep Research job | `src/research/llm_bridge.py` |
| LTM / memory extraction | `src/memory/llm_extract.py` |
| PII capabilities probe | `src/runtime/llm_probe.py` |
| Opik telemetry test calls | `src/observability/opik_telemetry.py` |
| MCP enricher, wizard, marketplace analyzer | `resolve_llm_credentials()` callers |

:::warning Key-scoped routers
With a router that scopes API keys per model (the AION router answers
`404 Model '<id>' is not allowed for this API key`), the provider's **model**
must be one the saved key is allowed to call (for example `auto` to let the
router pick the machine). Before this fix the chat sent `AION_LLM_API_KEY`
together with the DB provider's URL/model, so the chat and the Deep Research
used different keys and only one of them worked.
:::

## Checking the configuration in Docker

List the models the saved key may use without printing the key:

```bash
docker compose exec -T backend python -c "import sqlite3,httpx; from src.runtime.credential_store import decrypt_value; b,m,e=sqlite3.connect('data/aion.db').execute('select api_base_url,model_name,api_key_encrypted from llm_providers where enabled=1 order by is_default desc').fetchone(); r=httpx.get(b+'/models',headers={'Authorization':'Bearer '+decrypt_value(e)},timeout=30); print('model:',m,'| allowed:',[x['id'] for x in r.json().get('data',[])])"
```

The configured model must appear in `allowed`. A Deep Research job whose key
or model is rejected now ends immediately with status `error` and the router's
reason (see [Deep Research](../integrations/deep-research.md#troubleshooting)).
