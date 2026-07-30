#!/usr/bin/env python3
"""
Fail CI if proprietary office skill packages appear under config_std/ (must stay local only).

Checks both git-tracked paths and on-disk trees under config_std/skills/.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STD_SKILLS = ROOT / "config_std" / "skills"
MANIFEST = ROOT / "config_proprietary" / "manifest.yaml"

_PROPRIETARY_MARKERS = (
    "© 2025 Anthropic, PBC. All rights reserved.",
    "license: Proprietary",
)


def _load_slugs() -> tuple[str, ...]:
    if not MANIFEST.is_file():
        return ("docx", "pdf", "pptx", "xlsx")
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(MANIFEST.read_text(encoding="utf-8")) or {}
        skills = data.get("skills") or []
        return tuple(str(s).strip() for s in skills if str(s).strip())
    except Exception:
        return ("docx", "pdf", "pptx", "xlsx")


def _git_tracked_under_config_std() -> list[str]:
    proc = subprocess.run(
        ["git", "ls-files", "config_std/skills"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def main() -> int:
    slugs = _load_slugs()
    errors: list[str] = []

    for slug in slugs:
        pkg = STD_SKILLS / slug
        if pkg.is_dir():
            errors.append(f"on-disk package: {pkg.relative_to(ROOT)}")

    for rel in _git_tracked_under_config_std():
        parts = Path(rel).parts
        if len(parts) >= 3 and parts[2] in slugs:
            errors.append(f"git-tracked: {rel}")
        if rel.endswith("LICENSE.txt"):
            try:
                text = (ROOT / rel).read_text(encoding="utf-8", errors="replace")
                if _PROPRIETARY_MARKERS[0] in text:
                    errors.append(f"Anthropic proprietary LICENSE in git: {rel}")
            except OSError:
                pass

    for path in STD_SKILLS.rglob("LICENSE.txt"):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if _PROPRIETARY_MARKERS[0] in text:
            rel = path.relative_to(ROOT)
            errors.append(f"Anthropic proprietary LICENSE on disk: {rel}")

    for path in STD_SKILLS.rglob("SKILL.md"):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")[:500]
        except OSError:
            continue
        if _PROPRIETARY_MARKERS[1] in text:
            rel = path.relative_to(ROOT)
            errors.append(f"Proprietary skill frontmatter: {rel}")

    if errors:
        print("ERROR: proprietary / licensed office skills must not live under config_std/", file=sys.stderr)
        print("Move them to config_proprietary/skills/ (gitignored) and sync to config/.", file=sys.stderr)
        for line in sorted(set(errors)):
            print(f"  - {line}", file=sys.stderr)
        return 1

    print("OK: config_std/skills has no proprietary office packages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
