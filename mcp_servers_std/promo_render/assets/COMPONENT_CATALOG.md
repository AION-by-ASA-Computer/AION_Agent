# Promo component catalog (use these class names)

Do **not** invent blue/violet gradients. AION Agent campaigns = **crimson bento** below.

## Layout shells

| Class | Use |
|-------|-----|
| `#promo-root.promo-canvas-crimson` | Full-bleed crimson-black canvas |
| `.promo-bento.promo-bento--portrait` | 1080×1350 grid (4:5 Instagram) |
| `.promo-bento.promo-bento--square` | 1080×1080 grid |
| `.promo-ambient` | Radial glow + subtle grid (always include) |
| `.promo-noise` | Film grain overlay |
| `.promo-watermark` | ASCII texture footer |

## Tiles (grid areas)

| Class | Role |
|-------|------|
| `.promo-tile--brand` | Logo / wordmark top-left |
| `.promo-tile--badge` | Pill badge top-right |
| `.promo-tile--accent` | Thin red gradient bar (NUANCE-style) |
| `.promo-tile--hero` | Main headline block |
| `.promo-tile--crystal` | Glass polyhedron (use `<CrystalHero />` SVG) |
| `.promo-tile--stat1` / `--stat2` | Stat chips |
| `.promo-tile--product` | Product photo / PGX / UI mock |
| `.promo-tile--trust` | Trust line / proof |
| `.promo-tile--footer` | URL mono |

Modifiers: `.promo-tile--gradient-red`, `.promo-tile--photo` (+ `background-image` inline).

## Typography

| Class | Use |
|-------|-----|
| `.promo-headline-xl` | 3-line uppercase hero; `.line-accent` on last line |
| `.promo-subline` | One supporting sentence max |
| `.promo-glow-line` | Red accent rule under subline |
| `.promo-logo-wordmark` + `.promo-logo-rule` + `.promo-logo-sub` | Text logo block |
| `.promo-logo-img` | SVG/PNG logo |
| `.promo-stat-value` / `.promo-stat-label` | Chip numbers |
| `.promo-badge` + `.promo-badge-dot` | ON-PREMISE pill |
| `.promo-url` | Footer domain |

## Scaffold

- `promo_scaffold_react_post(..., layout_style="bento_red")` → production bento (portrait).
- `layout_style="minimal"` → legacy placeholder (avoid for final export).

## Customization rules

1. Change **copy** and **stat values** first; keep grid structure.
2. Swap `PRODUCT_BLOCK` for `<img className="promo-product-img" src="./assets/pgx.webp" />`.
3. Logo: `uploads/` → copy to `./assets/logo.svg` or use `https://aion-asa.com/images/logo_aion_white.svg`.
4. Never remove `#promo-root` or `.promo-bento--portrait` on 1080×1350 jobs.
