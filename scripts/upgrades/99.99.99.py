"""TEST ONLY (created by scripts/dev/test-self-update.sh, never commit).

Proves that `upgrade_runner.py --to local` runs unreleased upgrade scripts:
writes a marker in .env; raises while the failure trigger file exists.
"""
from pathlib import Path


def upgrade(ctx) -> None:
    if Path("/app/data/.selfupdate-test-fail").exists():
        raise RuntimeError("self-update test: simulated upgrade script failure")
    ctx.ensure_env_key("AION_SELFUPDATE_TEST_MARKER", "1")
