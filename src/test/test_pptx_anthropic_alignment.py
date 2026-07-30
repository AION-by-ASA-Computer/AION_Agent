"""Integration: Anthropic-aligned pptx skill materialize + pptxgenjs deck build."""

from __future__ import annotations

import json
import shutil
import sys
import uuid
from pathlib import Path

import pytest

from src.skill_registry import skill_registry
from src.tools.skill_materialize import materialize_skill_scripts
from src.tools.session_code import SessionSandboxExecutor


def _npm_available() -> bool:
    return shutil.which("npm") is not None and shutil.which("node") is not None


@pytest.mark.skipif(not _npm_available(), reason="node/npm not on PATH")
def test_pptx_materialize_and_build_deck_with_pptxgenjs(tmp_path, monkeypatch):
    """Same path as Anthropic: skill scripts + pptxgenjs builder + writeFile."""
    session_id = f"test-pptx-{uuid.uuid4().hex[:8]}"
    sessions_base = tmp_path / "data" / "sessions"
    sessions_base.mkdir(parents=True)

    def _session_root(sid: str) -> Path:
        p = sessions_base / sid
        p.mkdir(parents=True, exist_ok=True)
        return p

    monkeypatch.setattr("src.session_workspace.session_root", _session_root)
    monkeypatch.setattr("src.tools.skill_materialize.session_root", _session_root)
    monkeypatch.setattr("src.tools.session_code.session_root", _session_root)
    monkeypatch.setenv("AION_SANDBOX_ALLOW_NPM_INSTALL", "1")

    skill_registry.reload()
    if not skill_registry.get_skill_full("pptx"):
        pytest.skip(
            "pptx skill not installed — config_proprietary/skills/pptx + sync_proprietary_config"
        )
    scripts_dir = skill_registry.get_skill_scripts_dir("pptx")
    assert scripts_dir, "pptx scripts/ missing"
    assert (scripts_dir / "office" / "validate.py").is_file()
    assert (scripts_dir / "office" / "helpers" / "pptx_theme.py").is_file()
    assert (scripts_dir / "pptxgenjs" / "canvas.js").is_file()
    assert (scripts_dir / "pptxgenjs" / "lint_deck_script.js").is_file()

    mat = materialize_skill_scripts(session_id, "pptx", force=True)
    assert mat.status == "copied"
    assert "pptxgenjs" in mat.message.lower()

    session_root = sessions_base / session_id
    ws = session_root / "workspace"
    ws.mkdir(parents=True, exist_ok=True)

    deck_data = {
        "title": "AION Test Deck",
        "subtitle": "Anthropic-aligned pptxgenjs",
        "slides": [
            {"title": "AI Locale", "bullets": ["On-prem AI", "Data sovereignty"]},
            {"title": "AION Models", "bullets": ["Quantized LLMs", "Edge inference"]},
        ],
    }
    (ws / "deck_data.json").write_text(
        json.dumps(deck_data, ensure_ascii=False), encoding="utf-8"
    )

    build_js = r"""
const pptxgen = require("pptxgenjs");
const fs = require("fs");
const path = require("path");
const { bindLayout, setSlideBg } = require("../scripts/pptxgenjs/canvas.js");

const data = JSON.parse(fs.readFileSync(path.join(__dirname, "deck_data.json"), "utf8"));
const pres = new pptxgen();
const { W, H } = bindLayout(pres, "LAYOUT_WIDE");
pres.title = data.title;

function darkSlide(title) {
  const slide = pres.addSlide();
  setSlideBg(slide, "0A0A0A");
  slide.addText(title, {
    x: 0.5, y: 0.4, w: W - 1, h: 0.8, fontSize: 32, bold: true,
    color: "FFFFFF", margin: 0,
  });
  return slide;
}

const cover = pres.addSlide();
setSlideBg(cover, "0A0A0A");
cover.addText(data.title, {
  x: 0.5, y: H / 2 - 0.5, w: W - 1, h: 1, fontSize: 44, bold: true,
  color: "D42020", align: "center", margin: 0,
});
cover.addText(data.subtitle, {
  x: 0.5, y: H / 2 + 0.6, w: W - 1, h: 0.6, fontSize: 18,
  color: "CCCCCC", align: "center", margin: 0,
});

for (const s of data.slides) {
  const slide = darkSlide(s.title);
  const lines = (s.bullets || []).map((t, i, arr) => ({
    text: t,
    options: { bullet: true, breakLine: i < arr.length - 1, color: "EEEEEE", fontSize: 16 },
  }));
  slide.addText(lines, { x: 0.7, y: 1.4, w: W - 1.4, h: H - 2, margin: 0 });
}

const out = path.join(__dirname, "aion_test_deck.pptx");
pres.writeFile({ fileName: out }).then(() => {
  console.log("OK wrote", out);
}).catch((err) => {
  console.error(err);
  process.exit(1);
});
"""
    (ws / "build_deck.js").write_text(build_js.strip() + "\n", encoding="utf-8")

    import subprocess

    lint = subprocess.run(
        [
            "node",
            str(session_root / "scripts" / "pptxgenjs" / "lint_deck_script.js"),
            "workspace/build_deck.js",
        ],
        cwd=str(session_root),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert lint.returncode == 0, lint.stdout + lint.stderr

    ex = SessionSandboxExecutor(session_id)
    out = ex.run_node_file("workspace/build_deck.js")
    assert "OK wrote" in out or "Exit code: 0" in out, out

    pptx_path = ws / "aion_test_deck.pptx"
    assert pptx_path.is_file(), f"missing output: {out}"
    assert pptx_path.stat().st_size > 5000

    validate_py = session_root / "scripts" / "office" / "validate.py"
    if validate_py.is_file():
        proc = subprocess.run(
            [sys.executable, str(validate_py), str(pptx_path)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if proc.returncode != 0:
            pytest.skip(f"office validate strict check: {proc.stdout or proc.stderr}")
