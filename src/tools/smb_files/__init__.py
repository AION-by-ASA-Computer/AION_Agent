"""Core logic of the ``smb_files`` MCP connector (Windows file shares over SMB).

The package is deliberately free of any MCP dependency so it can be unit-tested
on its own; the thin FastMCP server (``mcp_servers_std/smb_files/server.py``)
and the admin API only call into it.  Every file operation runs with the
*end user's* Windows credentials, so NTFS ACLs and Windows audit logs apply.
"""
