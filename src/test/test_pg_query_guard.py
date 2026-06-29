from src.runtime.pg_query_guard import (
    is_postgres_query_tool,
    postgres_query_timeout_sec,
)


def test_is_postgres_query_tool():
    assert is_postgres_query_tool("toolbox-postgres", "query")
    assert not is_postgres_query_tool("memory", "query")


def test_postgres_timeout_sec():
    assert postgres_query_timeout_sec("toolbox-postgres", "query") == 60.0
