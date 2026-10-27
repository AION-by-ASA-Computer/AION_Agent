"""Shared pytest plugins for src/test."""

pytest_plugins = ["src.test.mcp_oauth_test_helpers"]


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "integration: test con processi o servizi reali (node, rete)"
    )
