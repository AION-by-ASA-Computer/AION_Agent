"""
MCP promo_render: React/HTML promotional canvases → PNG (AION bento red).
Requires AION_CHAT_SESSION_ID. Uses Playwright headless Chromium.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from fastmcp import FastMCP

from src.tools.promo_capture import (
    CANVAS_PRESETS,
    capture_html_to_png,
    check_playwright_ready,
    list_canvas_presets,
    read_component_catalog,
    read_style_guide,
    scaffold_react_post,
    scaffold_social_pack,
)

mcp = FastMCP("AION Promo Render")


def _sid() -> str:
    s = os.environ.get("AION_CHAT_SESSION_ID", "").strip()
    if not s:
        raise RuntimeError("AION_CHAT_SESSION_ID not set")
    return s


@mcp.tool()
def promo_list_canvas_presets() -> str:
    """
    List social/ad canvas sizes (width×height). Instagram 4:5 = instagram_portrait (1080×1350).
    """
    return json.dumps(list_canvas_presets(), ensure_ascii=False, indent=2)


@mcp.tool()
def promo_get_component_catalog() -> str:
    """
    CSS class catalog for bento/red promo layouts (.promo-bento--portrait, tiles, typography).
    Call before editing index.html — prevents generic blue scaffold output.
    """
    return read_component_catalog()


@mcp.tool()
def promo_get_style_guide(theme: str = "dark") -> str:
    """PREMIUM_STYLE.md + bundled aion-promo-theme.css (crimson bento, not chat-ui blue)."""
    return read_style_guide(theme=theme)


@mcp.tool()
def promo_scaffold_social_pack(
    base_name: str = "aion-agent",
    headline_line1: str = "L'AI AZIENDALE",
    headline_line2: str = "SENZA LIMITI",
    headline_line3: str = "ON-PREM.",
    subheadline: str = "Profili su misura, skill custom, strumenti via MCP — tutto nella tua rete.",
    badge: str = "ON-PREMISE · ZERO DATA LEAK",
    footer_url: str = "aion-asa.com",
    stat1_value: str = "120",
    stat1_label: str = "tok/s PGX",
    stat2_value: str = "∞",
    stat2_label: str = "Utenti",
    stat3_value: str = "100%",
    stat3_label: str = "On-premise",
    feature_chips: str = "Profili · MCP · Skill · Plan Mode",
    logo_url: str = "https://aion-asa.com/images/logo_aion_white.svg",
    product_image_url: str = "https://aion-asa.com/images/aionagent/pgx.webp",
) -> str:
    """
    Create TWO projects at once (no overwrite): workspace/promo/<base>-instagram (1080×1080)
    and workspace/promo/<base>-linkedin (1200×627). Use this when the user asks for Instagram + LinkedIn.
    """
    result = scaffold_social_pack(
        _sid(),
        base_name=base_name,
        headline_line1=headline_line1,
        headline_line2=headline_line2,
        headline_line3=headline_line3,
        subheadline=subheadline,
        badge=badge,
        footer_url=footer_url,
        stat1_value=stat1_value,
        stat1_label=stat1_label,
        stat2_value=stat2_value,
        stat2_label=stat2_label,
        stat3_value=stat3_value,
        stat3_label=stat3_label,
        feature_chips=feature_chips,
        logo_url=logo_url,
        product_image_url=product_image_url,
    )
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
def promo_scaffold_react_post(
    project_name: str = "promo",
    canvas_preset: str = "instagram_square",
    layout_style: str = "bento_red",
    title: str = "Promotional post",
    headline_line1: str = "L'AI AZIENDALE",
    headline_line2: str = "SENZA LIMITI",
    headline_line3: str = "ON-PREM.",
    subheadline: str = "Profili su misura, skill custom, strumenti via MCP — tutto nella tua rete.",
    badge: str = "ON-PREMISE · ZERO DATA LEAK",
    footer_url: str = "aion-asa.com",
    stat1_value: str = "120",
    stat1_label: str = "tok/s PGX",
    stat2_value: str = "∞",
    stat2_label: str = "Utenti",
    stat3_value: str = "100%",
    stat3_label: str = "On-premise",
    feature_chips: str = "Profili · MCP · Skill",
    trust_line: str = "LLM, MCP, documenti — tutto in casa.",
    logo_url: str = "https://aion-asa.com/images/logo_aion_white.svg",
    product_image_url: str = "https://aion-asa.com/images/aionagent/pgx.webp",
) -> str:
    """
    ONE format only. For Instagram + LinkedIn together use promo_scaffold_social_pack (never call this twice on the same project_name).
    canvas_preset: instagram_square (1:1) | instagram_portrait (4:5) | linkedin_post (1200×627).
    Colors: AION red only — never cyan/teal/violet.
    """
    if canvas_preset not in CANVAS_PRESETS:
        return json.dumps(
            {
                "ok": False,
                "error": f"Unknown canvas_preset. Valid: {list(CANVAS_PRESETS.keys())}",
            },
            ensure_ascii=False,
        )
    result = scaffold_react_post(
        _sid(),
        project_name=project_name,
        canvas_preset=canvas_preset,
        layout_style=layout_style,
        title=title,
        headline_line1=headline_line1,
        headline_line2=headline_line2,
        headline_line3=headline_line3,
        subheadline=subheadline,
        badge=badge,
        footer_url=footer_url,
        stat1_value=stat1_value,
        stat1_label=stat1_label,
        stat2_value=stat2_value,
        stat2_label=stat2_label,
        trust_line=trust_line,
        logo_url=logo_url,
        product_image_url=product_image_url,
    )
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
def promo_capture_to_png(
    html_relative_path: str = "workspace/promo/promo/index.html",
    output_relative_path: str = "workspace/promo/promo/output.png",
    width: int = 1080,
    height: int = 1350,
    device_scale_factor: float = 2.0,
    wait_ms: int = 2000,
) -> str:
    """
    Screenshot #promo-root to PNG. Match width/height to canvas_preset (portrait: 1080×1350).
    wait_ms: 2000+ recommended when loading Google Fonts / external images.
    """
    result = capture_html_to_png(
        _sid(),
        html_relative_path=html_relative_path,
        output_relative_path=output_relative_path,
        width=width,
        height=height,
        device_scale_factor=device_scale_factor,
        wait_ms=wait_ms,
    )
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
def promo_check_environment() -> str:
    """Verify Playwright/Chromium on MCP Python (not session sandbox venv)."""
    ok, detail = check_playwright_ready()
    return json.dumps({"ok": ok, "detail": detail}, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    mcp.run(transport="stdio")
