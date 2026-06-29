"""Cron expression validation and next-run computation."""
from datetime import datetime, timezone

import pytest

from src.runtime.cron_expression import (
    compute_next_run_at,
    default_timezone,
    validate_cron_expression,
    validate_session_mode,
)


def test_validate_cron_expression_accepts_standard_five_field():
    assert validate_cron_expression("0 9 * * *", "UTC") == "0 9 * * *"


def test_validate_cron_expression_rejects_empty():
    with pytest.raises(ValueError, match="required"):
        validate_cron_expression("", "UTC")


def test_validate_cron_expression_rejects_bad_timezone():
    with pytest.raises(ValueError, match="timezone"):
        validate_cron_expression("0 9 * * *", "Not/A/Zone")


def test_compute_next_run_at_returns_utc_aware():
    nxt = compute_next_run_at("0 9 * * *", "Europe/Rome")
    assert nxt.tzinfo == timezone.utc
    assert nxt > datetime.now(timezone.utc)


def test_validate_session_mode_fixed_and_new():
    assert validate_session_mode("fixed") == "fixed"
    assert validate_session_mode("NEW") == "new"
    with pytest.raises(ValueError):
        validate_session_mode("rolling")


def test_default_timezone_from_env(monkeypatch):
    monkeypatch.setenv("AION_CRON_DEFAULT_TIMEZONE", "Europe/Rome")
    assert default_timezone() == "Europe/Rome"
