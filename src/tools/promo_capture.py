"""
HTML/React promotional canvas → PNG via Playwright (session workspace).
"""
from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..session_workspace import safe_resolve, session_root

_ASSETS_DIR = Path(__file__).resolve().parents[2] / "mcp_servers_std" / "promo_render" / "assets"
_TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "mcp_servers_std" / "promo_render" / "templates"

CANVAS_PRESETS: Dict[str, Dict[str, int]] = {
    "instagram_square": {"width": 1080, "height": 1080, "padding": 48},
    "instagram_portrait": {"width": 1080, "height": 1350, "padding": 48},
    "instagram_story": {"width": 1080, "height": 1920, "padding": 56},
    "linkedin_post": {"width": 1200, "height": 627, "padding": 40},
    "twitter_post": {"width": 1600, "height": 900, "padding": 48},
    "facebook_cover": {"width": 1640, "height": 856, "padding": 48},
    "youtube_thumbnail": {"width": 1280, "height": 720, "padding": 40},
}


def _capture_enabled() -> bool:
    return os.environ.get("AION_PROMO_CAPTURE_ENABLED", "1").lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _capture_timeout_ms() -> int:
    raw = (os.environ.get("AION_PROMO_CAPTURE_TIMEOUT_MS") or "90000").strip()
    try:
        return max(5000, int(raw))
    except ValueError:
        return 90000


def list_canvas_presets() -> List[Dict[str, Any]]:
    return [
        {"id": k, **v, "aspect": f"{v['width']}×{v['height']}"}
        for k, v in CANVAS_PRESETS.items()
    ]


def read_component_catalog() -> str:
    path = _ASSETS_DIR / "COMPONENT_CATALOG.md"
    if path.is_file():
        return path.read_text(encoding="utf-8")
    return "COMPONENT_CATALOG.md missing — use classes from aion-promo-theme.css (.promo-bento--portrait, .promo-tile--*, etc.)."


def read_style_guide(theme: str = "dark") -> str:
    css_path = _ASSETS_DIR / "aion-promo-theme.css"
    premium_path = _ASSETS_DIR / "PREMIUM_STYLE.md"
    css = css_path.read_text(encoding="utf-8") if css_path.is_file() else ""
    premium = (
        premium_path.read_text(encoding="utf-8") if premium_path.is_file() else ""
    )
    theme_note = (
        "Default: AION Agent premium dark + red (#e11614). "
        "Read PREMIUM_STYLE.md and build a bento grid — do not ship the generic scaffold layout."
        if theme.strip().lower() != "light"
        else "Override tokens for light mode if requested."
    )
    return (
        "## AION promotional style\n\n"
        f"{theme_note}\n\n"
        "- Font: **Space Grotesk** (+ Geist Mono labels) from Google Fonts.\n"
        "- Layout: `#promo-root` exact canvas pixels; **bento grid** (see premium guide).\n"
        "- Classes: `.promo-badge`, `.promo-cta`, `.promo-card`, `.promo-stat-value`, "
        "`.promo-ambient`, `.promo-grid`, `.promo-headline`.\n"
        "- Canvas presets: `instagram_portrait` = 1080×1350 (4:5 feed, recommended vertical).\n"
        "- No scroll; 2× device scale for PNG.\n\n"
        "### Premium layout guide (mandatory for AION Agent)\n\n"
        f"{premium}\n\n"
        "### Bundled CSS\n\n"
        f"```css\n{css}\n```\n"
    )


def _slug(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9_-]+", "_", (name or "promo").strip().lower())
    return s[:64] or "promo"


def _pick_template(canvas_preset: str, layout_style: str) -> str:
    style = (layout_style or "").strip().lower()
    if style in ("minimal", "legacy"):
        return "react_post.html"
    if style in ("bento_red", "bento", "premium", ""):
        mapping = {
            "instagram_portrait": "bento_portrait_red.html",
            "instagram_square": "bento_square_red.html",
            "linkedin_post": "bento_linkedin_red.html",
        }
        if canvas_preset in mapping:
            return mapping[canvas_preset]
    return "react_post.html"


def _logo_block(logo_url: str) -> str:
    url = (logo_url or "").strip()
    if url:
        safe = url.replace('"', "%22")
        return f'<img className="promo-logo-img" src="{safe}" alt="AION" />'
    return (
        '<div className="promo-logo-wordmark">AION</div>'
        '<div className="promo-logo-rule" />'
        '<div className="promo-logo-sub">AGENT</div>'
    )


def _feature_chips_block(chips_csv: str) -> str:
    labels = [c.strip() for c in (chips_csv or "").split("·") if c.strip()]
    if not labels:
        labels = ["Profili", "MCP", "Skill"]
    parts = [f'<span className="promo-feature-chip">{lb}</span>' for lb in labels[:4]]
    return "\n              ".join(parts)


def _product_block(product_image_url: str) -> str:
    url = (product_image_url or "").strip()
    if url:
        safe = url.replace('"', "%22")
        return f'<img className="promo-product-img" src="{safe}" alt="" />'
    return (
        '<div className="promo-stat-value" style={{ fontSize: "1.1rem" }}>ThinkStation PGX</div>'
        '<div className="promo-stat-label">Hardware on-prem</div>'
    )


def scaffold_react_post(
    session_id: str,
    *,
    project_name: str = "promo",
    canvas_preset: str = "instagram_portrait",
    layout_style: str = "bento_red",
    title: str = "Promotional post",
    headline: str = "Your headline",
    headline_line1: str = "L'AGENTE AI",
    headline_line2: str = "PROGETTATO PER",
    headline_line3: str = "L'AZIENDA.",
    subheadline: str = "Elabora documenti, scrivi codice e automatizza i processi",
    badge: str = "ON-PREMISE · ZERO DATA LEAK",
    cta: str = "Learn more",
    footer_label: str = "Brand",
    footer_value: str = "AION",
    footer_url: str = "aion-asa.com",
    stat1_value: str = "120",
    stat1_label: str = "tok/s LLM",
    stat2_value: str = "∞",
    stat2_label: str = "Agenti",
    trust_line: str = "LLM, MCP, documenti — tutto in casa.",
    logo_url: str = "https://aion-asa.com/images/logo_aion_white.svg",
    product_image_url: str = "https://aion-asa.com/images/aionagent/pgx.webp",
    stat3_value: str = "100%",
    stat3_label: str = "On-premise",
    feature_chips: str = "Profili · MCP · Skill",
) -> Dict[str, Any]:
    preset = CANVAS_PRESETS.get(canvas_preset) or CANVAS_PRESETS["instagram_square"]
    slug = _slug(project_name)
    rel_dir = f"workspace/promo/{slug}"
    root = session_root(session_id)
    out_dir = root / rel_dir.replace("/", os.sep)
    out_dir.mkdir(parents=True, exist_ok=True)
    overwritten = (out_dir / "index.html").is_file()

    tpl_name = _pick_template(canvas_preset, layout_style)
    tpl_path = _TEMPLATES_DIR / tpl_name
    if not tpl_path.is_file():
        return {"ok": False, "error": f"Template missing: {tpl_path}"}

    html = tpl_path.read_text(encoding="utf-8")
    replacements = {
        "{{TITLE}}": title,
        "{{WIDTH}}": str(preset["width"]),
        "{{HEIGHT}}": str(preset["height"]),
        "{{PADDING}}": str(preset.get("padding", 48)),
        "{{BADGE}}": badge,
        "{{HEADLINE}}": headline,
        "{{HEADLINE_LINE1}}": headline_line1,
        "{{HEADLINE_LINE2}}": headline_line2,
        "{{HEADLINE_LINE3}}": headline_line3,
        "{{SUBHEADLINE}}": subheadline,
        "{{CTA}}": cta,
        "{{FOOTER_LABEL}}": footer_label,
        "{{FOOTER_VALUE}}": footer_value,
        "{{FOOTER_URL}}": footer_url,
        "{{STAT1_VALUE}}": stat1_value,
        "{{STAT1_LABEL}}": stat1_label,
        "{{STAT2_VALUE}}": stat2_value,
        "{{STAT2_LABEL}}": stat2_label,
        "{{TRUST_LINE}}": trust_line,
        "{{LOGO_BLOCK}}": _logo_block(logo_url),
        "{{PRODUCT_BLOCK}}": _product_block(product_image_url),
        "{{STAT3_VALUE}}": stat3_value,
        "{{STAT3_LABEL}}": stat3_label,
        "{{FEATURE_CHIPS_BLOCK}}": _feature_chips_block(feature_chips),
    }
    for k, v in replacements.items():
        html = html.replace(k, v)

    (out_dir / "index.html").write_text(html, encoding="utf-8")
    css_src = _ASSETS_DIR / "aion-promo-theme.css"
    if css_src.is_file():
        shutil.copy2(css_src, out_dir / "aion-promo-theme.css")

    html_rel = f"{rel_dir}/index.html"
    png_rel = f"{rel_dir}/output.png"
    return {
        "ok": True,
        "project": slug,
        "canvas_preset": canvas_preset,
        "layout_style": layout_style or "bento_red",
        "template": tpl_name,
        "width": preset["width"],
        "height": preset["height"],
        "html_relative_path": html_rel,
        "output_relative_path": png_rel,
        "overwritten_previous": overwritten,
        "message": (
            f"Scaffold ({tpl_name}) under {rel_dir}/. Customize copy only; keep bento classes. "
            f"Then promo_capture_to_png with width={preset['width']} height={preset['height']}. "
            "Do NOT call scaffold again on the same project_name with a different preset — use promo_scaffold_social_pack."
        ),
    }


def scaffold_social_pack(
    session_id: str,
    *,
    base_name: str = "aion-agent",
    layout_style: str = "bento_red",
    **copy_kwargs: Any,
) -> Dict[str, Any]:
    """Create instagram_square + linkedin_post in separate folders (no overwrite)."""
    variants = []
    for preset, suffix in (
        ("instagram_square", "instagram"),
        ("linkedin_post", "linkedin"),
    ):
        one = scaffold_react_post(
            session_id,
            project_name=f"{base_name}-{suffix}",
            canvas_preset=preset,
            layout_style=layout_style,
            **copy_kwargs,
        )
        one["variant"] = suffix
        variants.append(one)
    ok = all(v.get("ok") for v in variants)
    return {
        "ok": ok,
        "variants": variants,
        "hint": "Capture each: workspace/promo/<base>-instagram/output.png and ...-linkedin/output.png",
    }


def _normalize_rel(session_id: str, rel: str) -> str:
    from src.runtime.mcp_tool_args import normalize_workspace_relative_path

    p = normalize_workspace_relative_path(rel.strip())
    top = p.split("/", 1)[0] if "/" in p else p
    if top not in ("workspace", "uploads", "derived"):
        raise ValueError("Path must be under workspace/, uploads/, or derived/")
    safe_resolve(session_id, p)
    return p


def capture_html_to_png(
    session_id: str,
    *,
    html_relative_path: str,
    output_relative_path: str,
    width: Optional[int] = None,
    height: Optional[int] = None,
    device_scale_factor: float = 2.0,
    wait_ms: int = 1200,
) -> Dict[str, Any]:
    if not _capture_enabled():
        return {
            "ok": False,
            "error": "Promo capture disabled (AION_PROMO_CAPTURE_ENABLED=0).",
        }

    try:
        html_rel = _normalize_rel(session_id, html_relative_path)
        out_rel = _normalize_rel(session_id, output_relative_path)
    except Exception as e:
        return {"ok": False, "error": str(e)}

    html_path = safe_resolve(session_id, html_rel)
    if not html_path.is_file():
        return {"ok": False, "error": f"HTML not found: {html_rel}"}

    out_path = safe_resolve(session_id, out_rel, must_exist=False)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    vw = width or 1080
    vh = height or 1080
    dsf = max(1.0, min(float(device_scale_factor), 3.0))
    wait_ms = max(0, min(int(wait_ms), 15000))

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {
            "ok": False,
            "error": (
                "playwright not installed. Run: pip install playwright && "
                "playwright install chromium"
            ),
        }

    file_url = html_path.resolve().as_uri()
    timeout = _capture_timeout_ms()

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={"width": int(vw), "height": int(vh)},
                device_scale_factor=dsf,
            )
            page = context.new_page()
            page.goto(file_url, wait_until="load", timeout=timeout)
            try:
                page.wait_for_function(
                    "() => document.fonts && document.fonts.status === 'loaded'",
                    timeout=min(15000, timeout),
                )
            except Exception:
                pass
            page.wait_for_timeout(wait_ms)
            try:
                page.wait_for_selector("#promo-root", timeout=10000)
            except Exception:
                pass
            page.locator("#promo-root").screenshot(
                path=str(out_path),
                type="png",
            )
            context.close()
            browser.close()
    except Exception as e:
        return {"ok": False, "error": f"Capture failed: {e}"}

    return {
        "ok": True,
        "html_relative_path": html_rel,
        "output_relative_path": out_rel,
        "width": vw,
        "height": vh,
        "device_scale_factor": dsf,
        "download_hint": (
            f"Download: GET /sessions/{session_id}/download?relative_path={out_rel}"
        ),
    }


def check_playwright_ready() -> Tuple[bool, str]:
    import sys

    py = sys.executable
    try:
        import playwright  # noqa: F401
    except ImportError:
        return False, (
            f"playwright not installed in MCP Python ({py}). "
            f"Run: {py} -m pip install playwright && "
            f"{py} -m playwright install chromium. "
            "Important: the session sandbox .venv is NOT used by promo_render — "
            "install in the server/MCP interpreter or mcp_servers/promo_render/.venv."
        )
    if os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        return True, f"playwright OK ({py}); PLAYWRIGHT_BROWSERS_PATH set"
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            exe = p.chromium.executable_path
            if exe and Path(exe).is_file():
                return True, f"ready — {py} — chromium: {exe}"
    except Exception as e:
        return False, (
            f"browsers missing for {py}. Run: {py} -m playwright install chromium — {e}"
        )
    return False, f"Run: {py} -m playwright install chromium"
