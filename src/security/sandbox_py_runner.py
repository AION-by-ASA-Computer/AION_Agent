"""
Bootstrap entry for confined session Python scripts (legacy alias).

Prefer ``python -m src.security.sandbox_subprocess_entry --python <script>``.
"""

from __future__ import annotations

from .sandbox_subprocess_entry import main

if __name__ == "__main__":
    raise SystemExit(main())
