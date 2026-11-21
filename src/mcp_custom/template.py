"""Starter snippets for customer-built MCP servers, shown in the admin-ui guide.

The "How to prepare your MCP server" guide (admin-ui, MCP Hub -> Upload MCP ->
Guide) displays these texts and lets the admin copy them or download the
manifest as ``aion-mcp.yaml``. Keeping them here makes the backend the single
source of truth: ``src/test/test_mcp_custom.py`` checks that the manifest template
is valid against the real parser, so the guide can never show an outdated format.

Served by ``GET /admin/mcp-custom/guide-template``.
"""

from __future__ import annotations

from typing import Dict

# aion-mcp.yaml template: every field commented, valid as is (see the test).
MANIFEST_TEMPLATE = """# aion-mcp.yaml - manifest of an AION custom MCP server.
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
"""

# Minimal server.py following the developer contract (stdio, credentials read
# inside the tools so the server starts without them, nothing printed to stdout).
SERVER_TEMPLATE = '''"""Example AION custom MCP server."""

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
'''


def guide_templates() -> Dict[str, str]:
    """Texts shown by the admin-ui guide (manifest + minimal server)."""
    return {"aion_mcp_yaml": MANIFEST_TEMPLATE, "server_py": SERVER_TEMPLATE}
