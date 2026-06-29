# AION premium promo style (reference: NUANCE grid → AION red)

Use this when building social/ad canvases. Goal: **editorial fintech / enterprise tech**, not generic AI marketing.

## Visual reference (what to replicate)

- **Bento grid**: 2–4 rounded tiles on a dark canvas; asymmetric layout (one hero tile + stat chips + product visual).
- **Depth**: soft radial glow behind hero object; faint grid or noise texture; **no** full-screen purple/blue AI gradients.
- **Glass**: `backdrop-filter: blur(12px)`, border `rgba(255,255,255,0.08)`, inner highlight `inset 0 1px 0 rgba(255,255,255,0.06)`.
- **Typography**: Space Grotesk (site) or Inter fallback; **one** dominant headline, **short** subline, micro-labels in mono uppercase.
- **Stats**: large number + tiny label (e.g. `120` + `tok/s`), not paragraph bullets.
- **Logo**: top-left, modest size; never stretched.
- **Product**: one hardware or UI mock per post — not clipart.

## AION brand tokens (mandatory for Agent promos)

| Token | Value | Use |
|-------|-------|-----|
| Background | `#0a0a0b` | Canvas base |
| Surface | `#111113` | Cards |
| Accent | `#e11614` | Logo red, highlights, CTA |
| Accent soft | `#dc2626` | Secondary glow |
| Accent dark | `#991b1b` | Deep gradient stop |
| Text | `#ffffff` | Headlines |
| Muted | `#a3a3a3` | Body, labels |
| Border | `rgba(255,255,255,0.1)` | Cards |

**Do not** use chat-ui default blue accent (`hsl(224 76% 48%)`) for AION Agent campaigns unless the user explicitly asks for blue.

## Copy pattern (Italian B2B, few words)

**Hero line** (max 6 words):  
`AI on-prem. All-in-one.`

**Proof row** (3–4 stat chips, not sentences):  
`120 tok/s` · `Agenti ∞` · `10 utenti` · `ThinkStation PGX`

**Support line** (one line):  
`LLM, MCP, documenti e automazione — tutto in casa.`

**Footer**: `aion-asa.com` + logo

Avoid: "Scopri di più" alone, lorem ipsum, emoji spam, 8+ bullet lines, gradient text on everything.

## Layout recipes

### Instagram portrait (1080×1350) — default feed vertical

```
┌─────────────────────────┐
│ [logo]     badge        │
│                         │
│  HERO HEADLINE          │
│  one-line sub           │
│ ┌──────┐ ┌──────┐       │
│ │ stat │ │ stat │       │
│ └──────┘ └──────┘       │
│ ┌─────────────────┐     │
│ │ product / PGX   │     │
│ └─────────────────┘     │
│ 2 feature chips         │
│ footer URL              │
└─────────────────────────┘
```

Safe zone: keep logo and headline inside central **1012×1350** (3:4 grid preview crop).

### Instagram square (1080×1080)

Same hierarchy, fewer tiles (2 stats max).

## Assets (official)

| Asset | URL / path |
|-------|------------|
| Logo white | `https://aion-asa.com/images/logo_aion_white.svg` |
| PGX hardware | `https://aion-asa.com/images/aionagent/pgx.webp` (or copy to `workspace/promo/<project>/assets/`) |
| Agent visual | `https://aion-asa.com/images/aionagent/aionagent.webp` |

Download into `workspace/promo/<project>/assets/` before capture if offline export is required.

## Anti-patterns (reject before export)

- Inter + blue gradient hero (default scaffold look)
- Centered stack: badge → huge title → gray paragraph → blue button
- More than 40% of canvas filled with text
- `mix-blend-screen` on photos without reason
- Rounded rectangles with identical padding everywhere (no hierarchy)
- Stock "futuristic circuit" backgrounds

## Implementation checklist

1. Override `:root` in `aion-promo-theme.css` with red tokens above.
2. Load **Space Grotesk** from Google Fonts.
3. Replace `PromoPost` with CSS Grid bento (not flex column only).
4. Add `background-image` subtle grid + radial red glow at 15% opacity.
5. Inline SVG icons (shield, cpu, layers) — 1.5px stroke, no filled emoji.
6. Capture at **2×** `device_scale_factor`.
