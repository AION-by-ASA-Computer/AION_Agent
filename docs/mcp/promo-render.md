---
title: Promo Render MCP
sidebar_position: 12
description: React/HTML promotional graphics exported to PNG with chat-ui styling.
---

# Promo Render MCP

Server `promo_render` turns session **React/HTML canvases** into **PNG** files for social and ads, using Playwright and design tokens aligned with **chat-ui**.

## Setup (once per host)

**Important:** PNG export uses the **MCP server Python** (`promo_render`), not the per-chat session sandbox venv. Installing Playwright only inside a session does **not** fix `promo_check_environment`.

### Automatic (recommended)

`./scripts/setup-aion-env.sh` and `./scripts/upgrade-aion.sh` (with `--prepare-runtime` on upgrade locale) invoke [`runtime_extras_setup.py`](../../scripts/runtime_extras_setup.py), which:

- Appends `AION_PROMO_CAPTURE_ENABLED=1` to `.env` if missing
- Runs `./scripts/setup_promo_playwright.sh` unless `--skip-promo-playwright`

```bash
./scripts/setup-aion-env.sh
# oppure dopo un pull
./scripts/upgrade-aion.sh
```

Dettagli policy filesystem + flag: [Policy filesystem ed export promo PNG](../configuration/filesystem-policy-and-promo.md).

### Manual

From the AION_Agent repo root:

```bash
./scripts/setup_promo_playwright.sh
```

Or manually (use the same `python` that runs the AION backend / `mcp_servers/promo_render/.venv/bin/python` if present):

```bash
python3 -m pip install "playwright>=1.49.0"
python3 -m playwright install chromium
```

Then in chat: `promo_check_environment` must return `"ok": true` with the chromium path in `detail`.

Optional: `AION_PROMO_CAPTURE_ENABLED=0` disables capture.

### Troubleshooting

| Symptom | Cause | Fix |
|---------|--------|-----|
| `ok: false`, `pip install playwright` | Playwright missing in **MCP** Python | Run `setup_promo_playwright.sh` |
| Capture fails after check OK | Chromium binaries missing | `python -m playwright install chromium` with MCP python |
| Works in sandbox script, not in promo | Two different venvs | Ignore session venv for promo |

## Tools

| Tool | Description |
|------|-------------|
| `promo_list_canvas_presets` | Instagram 4:5 = `instagram_portrait` (1080×1350) |
| `promo_get_component_catalog` | Bento CSS classes (`.promo-tile--*`) |
| `promo_get_style_guide` | PREMIUM_STYLE + `aion-promo-theme.css` |
| `promo_scaffold_react_post` | `layout_style=bento_red` (production) or `minimal` |
| `promo_capture_to_png` | PNG export (`wait_ms` ≥ 2000 for fonts) |
| `promo_check_environment` | MCP Python + Chromium (not sandbox venv) |

## Common issues

| Symptom | Cause | Fix |
|---------|--------|-----|
| Two conflicting posts | `promo_scaffold` called twice + extra `sandbox_write` | Use `promo_scaffold_social_pack` once |
| Square/LinkedIn ugly | `instagram_square` used `react_post.html` placeholder | Now uses `bento_square_red` / `bento_linkedin_red` |
| Cyan post, no logo | Agent invented palette | Red only; default `logo_url` + `product_image_url` in scaffold |
| Blue/violet centered UI | Agent ignored bento + red tokens | `layout_style=bento_red`, load `promo_visual_system` |
| `workspace/workspace/promo/...` | Double `workspace/` in artifact path | Fixed in path normalizer; use `filename: promo/x.html` only |
| Playwright false after sandbox pip | Wrong Python env | `./scripts/setup_promo_playwright.sh` |
| Blank/wrong fonts in PNG | `networkidle` + slow CDN | Capture uses `load` + `document.fonts` wait |
| Ugly generic layout | Shipped `minimal` scaffold | Default is `bento_portrait_red.html` |

## Profiles

| Slug | Role |
|------|------|
| **`graphic_designer`** | Dedicated profile — promo workflow only (recommended) |
| `aion_std` | Also includes `promo_render` + `promotional_graphics` |

Select **Graphic Designer** in chat-ui profile picker, or pass `profile: "graphic_designer"` on `/chat`.

## Download

PNG path example: `workspace/promo/my_campaign/output.png`  
`GET /sessions/{session_id}/download?relative_path=workspace/promo/my_campaign/output.png`
