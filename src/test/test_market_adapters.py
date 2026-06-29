from src.marketplaces.market_adapters import (
    npx_invoke_args,
    parse_github_owner_repo,
)


def test_parse_github_owner_repo_from_url():
    item = {"url": "https://github.com/taazkareem/clickup-mcp-server", "id": "x"}
    assert parse_github_owner_repo(item) == ("taazkareem", "clickup-mcp-server")


def test_parse_github_owner_repo_from_glama_id():
    item = {"id": "glama:Foo/Bar-Baz", "url": ""}
    assert parse_github_owner_repo(item) == ("foo", "bar-baz")


def test_npx_invoke_args_scoped_package():
    assert npx_invoke_args({"id": "npx:@example/foo-mcp"}) == [
        "-y",
        "@example/foo-mcp",
    ]


def test_npx_invoke_args_custom_list():
    item = {"id": "npx:x", "npx_args": ["-y", "@toolbox-sdk/server", "--stdio"]}
    assert npx_invoke_args(item) == ["-y", "@toolbox-sdk/server", "--stdio"]
