"""Customer-built MCP servers uploaded from admin-ui (v0: Python only).

A customer's development team writes its own MCP server, packages it as a single
``.py`` file or a ``.zip`` with an optional ``aion-mcp.yaml`` manifest, and an
admin uploads it from the MCP Hub. This package turns that upload into a regular
AION MCP server:

- ``settings``: feature flags and limits read from the environment.
- ``paths``: where custom servers live (``mcp_servers/custom/<slug>/``) and which
  slugs are reserved.
- ``manifest``: the ``aion-mcp.yaml`` contract (strict pydantic model).
- ``package``: upload validation and extraction into a staging area, plus the
  static checks shown to the admin (env vars used by the code, shadowed modules,
  antivirus notes).
- ``install``: activation (atomic swap, registry entry, DB policy sync, audit),
  discard and removal.
- ``integration``: credential mode/schema taken from the manifest by the
  existing discovery and sync code.
- ``runtime``: spawn policy applied to every custom server process (env rebuilt
  from scratch, credentials read only from the encrypted store, kill switch,
  sandbox requirement).

Design and roadmap: ``custom-mcp-servers-plan.md`` and
``docs/mcp/custom-mcp-servers.md``.
"""
