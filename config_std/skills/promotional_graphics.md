---
name: promotional_graphics
description: >-
  Create premium AION promotional PNGs (social, ads) via promo_render MCP: bento-grid
  dark+red layout, Space Grotesk, stat chips — not generic AI scaffold. Triggers: promo
  graphic, Instagram portrait 1080x1350, LinkedIn, AION Agent marketing, PNG export,
  ThinkStation PGX, social creative, graphic designer profile.
tags: [design, marketing, react, png, promo, social, aion-agent]
status: verified
source: curated
version: 3
---

# Promotional graphics (premium AION → PNG)

Deliver **finished PNG** files. Visual target: **editorial enterprise tech** (NUANCE-style bento grid), translated to **AION red** — not the default blue Inter scaffold.

---

## Playwright: why `promo_check_environment` fails after sandbox install

| Environment | Used for |
|-------------|----------|
| **Session sandbox `.venv`** | `sandbox_run_python_file`, pip in chat |
| **MCP `promo_render` Python** | `promo_capture_to_png`, `promo_check_environment` |

Installing Playwright only in the session venv **does not** enable PNG export.

**Fix (run once on the machine that hosts AION Agent):**

```bash
cd /path/to/AION_Agent
./scripts/setup_promo_playwright.sh
```

Or manually (use the Python path returned in `promo_check_environment` `detail` when `ok: false`):

```bash
python3 -m pip install playwright
python3 -m playwright install chromium
```

If `mcp_servers/promo_render/.venv` exists, use that venv’s `python` instead of system `python3`.

After setup, `promo_check_environment` must return `"ok": true` before capture.

**Fallback without Playwright:** deliver `workspace/promo/<project>/index.html` and tell the user to open it in Chrome → screenshot, or run the setup script.

---

## Mandatory workflow

1. Load **`promo_visual_system`** + this skill + **`promo_get_component_catalog()`** + **`promo_get_style_guide(theme="dark")`**.
2. **`promo_check_environment`** — if false, run setup above; do not loop on sandbox pip.
3. **`promo_list_canvas_presets`** — pick format:
   - **Instagram feed vertical:** `instagram_portrait` → **1080×1350** (4:5, recommended over 1:1)
   - Square: `instagram_square` → 1080×1080
   - Story/Reels: `instagram_story` → 1080×1920
4. **Formats:**
   - Instagram **1:1** + LinkedIn → **`promo_scaffold_social_pack`** (creates `...-instagram` and `...-linkedin` folders; never two scaffolds on same name).
   - Single format only → `promo_scaffold_react_post` once with `layout_style="bento_red"`.
   - Tune **copy/stats/logo URLs only**; keep bento classes. Logo + PGX image URLs are mandatory defaults.
5. **Design pass** (required):
   - Use `.promo-bento--portrait` tiles from catalog; crystal hero + red accent bar
   - Copy from user brief; Italian B2B tone; max ~30 words visible
   - Assets: `https://aion-asa.com/images/logo_aion_white.svg`, site images for PGX/agent
6. **One refinement pass** max (spacing, hierarchy, safe zone).
7. **`promo_capture_to_png`** with preset width/height → `output.png` at `device_scale_factor: 2`.
8. Report download path: `workspace/promo/<project>/output.png`.

---

## AION Agent content blocks (example brief)

Use as **stat chips**, not long bullets:

| Chip | Label |
|------|--------|
| 120 tok/s | LLM on-prem |
| ∞ | Agents |
| 10 | Users |
| PGX | Lenovo ThinkStation |

**Headline examples:** `AI on-prem. All-in-one.` · `Operational sovereignty.` · `AI that never leaves your network.`

**One-liner:** MCP, custom tools, documents, automation, app/portal integration.

---

## Layout rules (non-negotiable)

- `#promo-root` = exact canvas pixels; **no scroll**.
- Add `.promo-ambient` layer + `.promo-grid` with `grid-template-columns/areas`.
- Logo top-left via `<img src="./assets/logo.svg" class="promo-logo" />` (download SVG first).
- **No** default `.promo-gradient-hero` full-card-only layout for final export.
- **No** blue accent; use `#e11614` / `#dc2626`.
- Keep key content in center safe zone for Instagram 3:4 grid crop.

---

## Canvas presets

| id | Size | Use |
|----|------|-----|
| `instagram_portrait` | 1080×1350 | **Default vertical feed** |
| `instagram_square` | 1080×1080 | Square feed |
| `instagram_story` | 1080×1920 | Story/Reels |
| `linkedin_post` | 1200×627 | LinkedIn |
| `twitter_post` | 1600×900 | X |
| `youtube_thumbnail` | 1280×720 | Thumbnail |

---

## MCP tools

| Tool | Purpose |
|------|---------|
| `promo_get_component_catalog` | Bento CSS class reference |
| `promo_get_style_guide` | Red tokens + PREMIUM_STYLE.md |
| `promo_scaffold_social_pack` | Instagram 1:1 + LinkedIn in one call |
| `promo_scaffold_react_post` | Single format `bento_red` |
| `promo_capture_to_png` | PNG export |
| `promo_check_environment` | MCP Python + Chromium |

---

## Anti-patterns

- **Two scaffolds** on the same `project_name` (second overwrites first) — use `promo_scaffold_social_pack`.
- Extra `sandbox_write_workspace_file` HTML (`aion_social.html`) duplicating promo — one source: `workspace/promo/<project>/index.html`.
- **Cyan/teal/violet** accents — AION Agent = red `#e11614` only.
- `sandbox_install_python_packages(playwright)` — does **not** fix MCP capture.
- Shipping `layout_style=minimal` for square/linkedin (falls back to ugly placeholder).
- Ignoring `promo_visual_system` / component catalog.
- Installing Playwright only in session sandbox.
- Paragraph lists instead of stat chips.
- Wrong capture dimensions vs CSS canvas.
- Stopping at HTML without `promo_capture_to_png` when environment is OK.
