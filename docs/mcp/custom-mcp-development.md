---
sidebar_position: 21
title: Develop a custom MCP server
description: Step-by-step guide for developers - write an MCP server in Python, describe it with aion-mcp.yaml, test it locally, package it and publish new versions.
---

# Develop a custom MCP server

This guide is for the **developers** who build a custom MCP server to connect AION to a company system. At the end you will have a folder with `server.py` and `aion-mcp.yaml`, zipped and ready for an administrator to upload. You need basic Python knowledge; no knowledge of AION's code is required. How the administrator imports and manages the server is described in [Custom MCP servers](./custom-mcp-servers.md).

:::tip The same guide is in the product
In the admin panel, **MCP Hub → Upload MCP → Developer guide** shows these steps with templates you can copy or download.
:::

## What you are building

An **MCP server** (Model Context Protocol) is a program that exposes **tools**: Python functions the AI agent can call. AION starts your server, reads the list of tools with their descriptions, and the agent decides when to call them based on the user's request.

Current constraints:

- **Python** only;
- communication over **stdio** (standard input/output), the simplest MCP transport;
- the server runs in an **isolated container**: no access to AION's data or secrets, read-only files (only `/tmp` is writable), network **closed by default**.

## 1. Prepare the project folder

```text
my-crm-server/
├── server.py            # the server code (required)
├── aion-mcp.yaml        # the manifest: the server's identity card (required for zip uploads)
├── requirements.txt     # optional: external libraries, one per line
├── crm_client/          # optional: other Python modules
└── data/                # optional: data files (JSON, CSV…)
```

## 2. Write `server.py`

Use [FastMCP](https://gofastmcp.com/). Every function decorated with `@mcp.tool()` becomes a tool. Its **docstring is the description the AI model reads** to decide when to use the tool, so write it carefully: say what the tool does, what the parameters mean and what it returns.

```python
"""Example AION custom MCP server."""

import os

from fastmcp import FastMCP

mcp = FastMCP("Example server")


@mcp.tool()
def search_customer(name: str) -> str:
    """Search a customer by name in the company CRM."""
    # Read credentials inside the tool, never at import time:
    # AION checks the tool list before any credential is configured.
    api_key = os.environ.get("CRM_API_KEY")
    if not api_key:
        return "The CRM API key is not configured yet: ask an AION administrator."
    base_url = os.environ.get("CRM_BASE_URL", "")
    return f"Searching '{name}' on {base_url}"


if __name__ == "__main__":
    mcp.run()
```

### Rules

| Rule | Why |
|---|---|
| End the file with `mcp.run()`. | AION starts the server with `python -u server.py` and talks to it over stdio. |
| Read credentials with `os.environ` **inside the tools**, never at startup. | AION test-starts the server and lists its tools **before** any credential is configured. A server that fails without credentials fails verification. |
| Never use `print()`; use the `logging` module. | Standard output is the MCP channel: anything printed there breaks the protocol. |
| Open data files with `Path(__file__).parent / "data" / "file.json"`. | The working directory is not guaranteed to be your folder. |
| Don't name files or folders like Python modules (`json/`, `email/`, `token.py`…). | They would hide the real library and break imports. |
| Return clear text (or simple JSON) and readable error messages. | The agent reads the result and explains it to the user. |

### Libraries

You can use **any library**: list it in `requirements.txt` (or `pyproject.toml`) and AION installs it during the verification, in an isolated build container. Packages distributed as **wheels** are accepted — nearly all of PyPI. Packages that must be compiled from source are refused unless the administrator allows them. For databases prefer drivers with wheels, such as `pymssql` (SQL Server) or `psycopg` (PostgreSQL).

## 3. Fill in `aion-mcp.yaml`

The manifest tells AION who the server is and what it needs. Start from this template (also downloadable from the Developer guide in the admin panel):

```yaml
# aion-mcp.yaml - manifest of an AION custom MCP server.
# Put it next to server.py, at the root of the folder you zip and upload.

aion_mcp: 1                  # format version: do not change

slug: example_server         # technical id (lowercase, digits, _). Never change it after the first upload
name: Example server         # name shown in admin-ui and chat-ui
description: Looks up customers in the company CRM
version: 1.0.0               # bump at every release: AION keeps previous versions for rollback

runtime: python              # only python is supported for now
entrypoint: server.py        # file AION starts (default server.py)

# Secrets: only names and rules here. Values are entered in AION and stored encrypted.
# mode: none      -> no credentials
#       org_shared -> one value for the whole company, set by the admin
#       per_user   -> each user enters their own in "My integrations"
credentials:
  mode: org_shared
  fields:
    - key: CRM_API_KEY       # environment variable read by your code
      label: CRM API key     # label shown in the form
      secret: true           # masked and stored encrypted
      required: true

# Non-secret configuration, the same for everyone (the admin can change it later).
# Never put secrets here: this file is stored in clear.
env:
  CRM_BASE_URL: https://crm.example.local

# Network (optional). Closed by default: the server reaches only the addresses
# listed here (host name, IP or subnet, optional ports and port ranges). Everything
# else, AION included, is blocked. Leave it out for a server that needs no network.
# network:
#   - crm.example.local:443
#   - 10.20.0.0/24:5432
```

### Field reference

| Field | Required | Meaning |
|---|---|---|
| `aion_mcp` | yes | Format version, always `1`. |
| `slug` | yes | Technical id: lowercase letters, digits, `_`. **Never change it**: it is how AION recognizes new versions of the same server. |
| `name` | yes | Display name (max 80 characters). |
| `description` | yes | What the server is for (max 500 characters). |
| `version` | yes | Version of this release, e.g. `1.2.0`. Increase it at every upload. |
| `runtime` | no | `python` (the only value supported today). |
| `entrypoint` | no | File to start, default `server.py`. |
| `credentials.mode` | no | `none` (default), `org_shared` (one value for everyone, entered by the administrator) or `per_user` (each user enters their own in **Integrations**). |
| `credentials.fields[]` | no | One entry per secret: `key` (environment variable), `label`, `secret` (default `true`), `required` (default `true`), optional `description`. |
| `env` | no | Non-secret configuration values passed as environment variables. Stored in clear: **never put secrets here**. |
| `network` | no | Addresses the server may reach (see below). Without it, the server has no network. |

**Every environment variable your code reads must be declared** in `env` or in `credentials`. The variables check shown at upload lists the ones you forgot: undeclared variables are empty at run time.

### Network addresses

```yaml
network:
  - crm.company.local:443              # host name and port
  - as400.company.local:446,8470-8476  # ports and port ranges
  - 10.20.0.0/24:5432                  # IP or subnet
  - api.example.com                    # every port of that host
```

No wildcards (`*.company.local`), at most 50 entries. Everything else is blocked, AION and DNS included. The administrator reviews the list and can change it. If an internal application uses a certificate issued by your company's CA, ask the administrator to load the company CA in AION: the server then trusts it automatically through the standard variables (`SSL_CERT_FILE`, `REQUESTS_CA_BUNDLE`), with no code changes.

## 4. Test on your PC

Run the server with the FastMCP inspector: a web page opens where you can call each tool and see the answers. Set the environment variables by hand to simulate the credentials and the `env` values.

```bash
pip install fastmcp -r requirements.txt
export CRM_API_KEY="test-key" CRM_BASE_URL="https://crm.example.local"
fastmcp dev server.py
```

Check that the server **also starts without credentials** and lists its tools: that is exactly what AION verifies.

## 5. Zip and hand over

Zip the folder (files at the root of the zip or inside a single folder both work) and give the zip to an AION administrator, who uploads it in **MCP Hub → Upload MCP**. AION then:

1. checks the package and the manifest, and lists variables used by the code but not declared;
2. installs the libraries and **test-starts the server in the isolated container**, showing the tools it found or the error with the server log;
3. after activation, asks the administrator for credentials and network addresses.

Default limits: 20 MB per upload, 500 files per zip, 5 minutes to install dependencies, 90 seconds for the test start.

## 6. Publish a new version

Change the code, **increase `version`** in `aion-mcp.yaml` and hand over a new zip with the **same `slug`**. AION archives the previous version (for rollback) and keeps the credentials and the values changed by the administrator.

## Troubleshooting the verification

| Message or symptom | Likely cause | Fix |
|---|---|---|
| Missing module / `ImportError` | Library not in `requirements.txt`, or a local file shadows a library. | Add the library; rename files such as `json.py`. |
| Library cannot be installed | The package has no wheel for Linux/Python of the container. | Use an alternative with wheels, or ask the administrator to allow source builds. |
| Server exits at startup | Credentials read at import time, or `print()` on stdout. | Read credentials inside tools; use `logging`. |
| Timeout during the test start | Slow work at import time (connections, large downloads). | Connect lazily, inside the tools. |
| Tool works locally but cannot connect in AION | Destination not in `network:`, or company certificate not loaded. | Add the address; ask the administrator to load the company CA. |
| Variable always empty | Not declared in `env` or `credentials`. | Declare it in the manifest. |

## Related pages

- [Custom MCP servers](./custom-mcp-servers.md) — import, configuration and security, for administrators.
- [Credentials and isolation](./user-isolation-and-credentials.md) — shared vs per-user credentials.
- [MCP specification](https://modelcontextprotocol.io/) and [FastMCP documentation](https://gofastmcp.com/).
