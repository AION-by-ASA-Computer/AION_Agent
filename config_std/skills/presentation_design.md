# Presentation Design Protocol

## Objective
Create high-quality HTML presentations with clear narrative and modern UI.

## Default Strategy
1. Define audience, objective, key message.
2. Build 6-10 slides max (hook -> agenda -> insight -> plan -> CTA).
3. Keep one visual idea per slide.
4. Use concise bullets and strong typography hierarchy.

## UI/UX Rules
- Strong contrast and generous spacing.
- Consistent palette and typographic scale.
- Avoid dense text walls.
- Always include a closing CTA slide.

## Execution Rules (anti-loop)
- Max 1 generation pass + 1 refinement pass.
- Do not regenerate full deck repeatedly.
- If missing info, use safe defaults and proceed.

## Tool Usage (mandatory)
- Build presentation code manually: write full HTML/CSS/JS from scratch.
- Do NOT use template engines, preset builders, or precompiled slide generators.
- Follow the active `Artifact Protocol` strategy to generate the presentation HTML file.
- If needed, generate additional assets (`.css`, `.js`) as artifacts and reference them from the HTML.
- Keep one generation pass + one refinement pass maximum.

## Output
- Generate one or more HTML pages in session workspace.
- The primary deliverable must be runnable directly in browser from saved `.html` artifact.
