---
sidebar_position: 6
title: Office files and legacy Word (.doc)
description: Auto-conversion of Word 97–2003 binaries on upload via LibreOffice on the API host.
---

# Office files and legacy Word (.doc)

## Why conversion on the API host?

Legacy **`.doc`** files (Word 97–2003, OLE binary) are **not** OpenXML ZIP archives. Tools that work on `.docx` — `unpack.py`, `docx2txt`, docx-js — **cannot** read them.

**Design choice:** convert once at **upload time on the API process** (same host as FastAPI), not in the session sandbox:

| Approach | Problem |
|----------|---------|
| Sandbox `soffice.py` | LibreOffice is not installed in the sandbox; agent must discover conversion and often fails |
| `docx2txt` / `unpack` on `.doc` | Wrong format — expects ZIP/OpenXML |
| User manual re-save | Poor UX for chat uploads |

Production Docker images ship **`libreoffice-writer-nogui`** in `docker/Dockerfile.backend`. Local dev on macOS: `brew install --cask libreoffice`.

Conversion runs in **`src/tools/office_convert.py`**, triggered from **`src/api/session_uploads.py`** and **`src/api/v1/files.py`** via **`apply_legacy_word_conversion()`**.

---

## Upload flow

```mermaid
flowchart LR
    UI[chat-ui upload] --> API[POST /sessions/.../upload]
    API --> Save[save_upload uploads/]
    Save --> Conv{legacy .doc?}
    Conv -->|no| Done[return meta]
    Conv -->|yes| LO[soffice --convert-to docx]
    LO --> Out[derived/converted/name.docx]
    Out --> Manifest[derived/converted/upload.json]
    Manifest --> Done
```

1. File is stored under `uploads/<uuid>_<name>` (plus stable alias `uploads/<original_name>`).
2. If extension/MIME indicates legacy Word, **`soffice`** converts to **`derived/converted/<stem>.docx`**.
3. Response JSON and chat **`attachments`** / **`turn_attachments`** include:
   - `legacy_word: true`
   - `conversion_status`: `ok` | `unavailable` | `failed`
   - `converted_docx_path`: e.g. `derived/converted/report.docx` (when `ok`)
4. **`AgentPipeline._format_attachments_block`** injects a prompt block telling the agent to use **only** the `.docx` path (never unpack the binary `.doc`).

Misnamed files (`.doc` extension but ZIP/OpenXML payload) are **copied** to `.docx` without LibreOffice.

---

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `AION_OFFICE_AUTO_CONVERT_LEGACY_WORD` | `1` | Enable auto-conversion on upload |
| `AION_SOFFICE_PATH` | *(auto)* | Explicit path to `soffice` if not on `PATH` |
| `AION_OFFICE_CONVERT_TIMEOUT_SEC` | `90` | Max seconds per conversion |

**macOS dev example:**

```bash
AION_SOFFICE_PATH=/Applications/LibreOffice.app/Contents/MacOS/soffice
```

**Ubuntu / Docker:** `soffice` is on `PATH` after `libreoffice-writer-nogui` is installed.

---

## Agent workflow

1. User uploads `report.doc`.
2. Agent sees in the attachments block: **`derived/converted/report.docx`**.
3. `skill_view("docx")` → unpack/edit/pack on the **`.docx`** path only.
4. Deliver corrected file from `workspace/` or `uploads/` after pack.

Do **not** run `scripts/office/soffice.py --convert-to docx` in the sandbox for uploads — conversion is already done (or failed with a clear `conversion_status`).

See also [Skills and system prompt](./skills-and-prompts.md) (`docx` skill) and [Filesystem policy](./filesystem-policy-and-promo.md) (allowlisted `python` for office scripts on **`.docx`** only).

---

## MCP registry merge (new builtins)

`config/mcp_registry.yaml` is **never overwritten** by `sync_config.py --force` (local marketplace servers stay intact). New std servers (e.g. `geocoding`) are merged with:

```bash
python scripts/merge_mcp_registry_from_std.py
```

This runs automatically from:

- `scripts/dev-api.sh`
- `scripts/setup_core.py` (after `sync_mcp_servers.py`)
- `docker/backend-entrypoint.sh` (with `AION_SYNC_ON_BOOT=1`)

Use `--dry-run` to list slugs that would be added.

---

## Troubleshooting

### `conversion_status: unavailable`

LibreOffice not found on the **API host** (not the sandbox).

- **Docker:** rebuild backend image (`docker compose build backend`) so `libreoffice-writer-nogui` is present.
- **macOS dev:** `brew install --cask libreoffice` and optionally set `AION_SOFFICE_PATH`.
- **Re-upload** the `.doc` after fixing the host (or send a new chat message — retry runs if manifest was `unavailable`).

### Agent still calls `soffice` in sandbox

Reload profile/skill or restart backend after upgrading; proprietary `docx` skill documents API-side conversion. Ensure `converted_docx_path` is present in `turn_attachments` (chat-ui passes upload response fields).

### New MCP missing in Admin → Profiles

Run `python scripts/merge_mcp_registry_from_std.py` and restart the API.

---

## Related source files

| File | Role |
|------|------|
| `src/tools/office_convert.py` | LibreOffice conversion logic |
| `src/tools/office_auto_convert.py` | Async wrapper + manifest persistence |
| `src/agent_pipeline.py` | Attachments block hints for legacy Word |
| `docker/Dockerfile.backend` | `libreoffice-writer-nogui` package |
| `scripts/merge_mcp_registry_from_std.py` | Merge new MCP slugs from `config_std` |
