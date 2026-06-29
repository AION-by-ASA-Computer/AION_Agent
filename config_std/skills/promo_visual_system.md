---
name: promo_visual_system
description: >-
  CSS bento component library for AION promo PNGs (crimson NUANCE-style grids).
  Use with promo_render: promo_get_component_catalog, layout_style=bento_red scaffold.
  Triggers: bento layout, premium red tiles, glass crystal hero, stat chips, NUANCE style.
tags: [design, promo, css, bento, aion-red]
status: verified
source: curated
version: 1
---

# Promo visual system (bento + crimson)

**Mandatory** for Graphic Designer / AION Agent campaigns. Generic centered blue gradients are **rejected**.

## Before coding

1. `promo_get_component_catalog()` — class names and grid areas
2. `promo_get_style_guide(theme="dark")` — tokens + PREMIUM_STYLE.md
3. `promo_scaffold_react_post(..., layout_style="bento_red", canvas_preset="instagram_portrait")`

## Structure (do not simplify to one column)

```
.promo-canvas-crimson
  .promo-ambient + .promo-noise + .promo-watermark
  .promo-bento.promo-bento--portrait
    .promo-tile--brand      (logo)
    .promo-tile--badge      (ON-PREMISE pill)
    .promo-tile--accent     (thin red bar)
    .promo-tile--hero       (3-line headline + subline + .promo-glow-line)
    .promo-tile--crystal    (glass SVG — keep CrystalHero)
    .promo-tile--stat1/2    (numbers, not paragraphs)
    .promo-tile--product    (PGX / UI image)
    .promo-tile--trust      (one proof line)
    .promo-tile--footer     (.promo-url)
```

## Color law

| Use | Hex |
|-----|-----|
| Canvas top | `#080808` |
| Crimson mid | `#1c0a0a` |
| Garnet bottom | `#2d0d0d` |
| Accent | `#e11614` / `#e11d2a` |
| Glow | `#ff2222` at low opacity |

**Forbidden:** `#6366f1`, `#8b5cf6`, blue-violet CTA gradients, chat-ui blue `--accent-hsl`.

## Copy law (Italian)

- Headline: 3 lines max, last line `.line-accent`
- Subline: **one** sentence, `#ccc`, 18px equivalent (`.promo-subline`)
- Stats: `120` + `tok/s` — not bullet lists
- Badge: `ON-PREMISE · ZERO DATA LEAK` (no emoji unless user asks)

## Assets

- Logo: `../uploads/<file>` or `https://aion-asa.com/images/logo_aion_white.svg`
- Product: `https://aion-asa.com/images/aionagent/pgx.webp` → save under `./assets/`

## Export

`promo_capture_to_png` with **1080×1350** for `instagram_portrait`, `wait_ms: 2000`, `device_scale_factor: 2`.

## Quality gate (self-check before capture)

- [ ] Bento grid visible (multiple tiles, not one centered card)
- [ ] Red accent bar present
- [ ] Crystal/glass hero on the right
- [ ] No blue/purple gradients
- [ ] Text ≤ 35% of canvas area
