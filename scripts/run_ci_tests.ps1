# Curated pytest modules for CI (no live LLM, no external services).
$ErrorActionPreference = 'Stop'

$ROOT = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $ROOT

$MODULES = @(
    "src/test/test_api_endpoints.py"
    "src/test/test_session_env.py"
    "src/test/test_session_sandbox_escape.py"
    "src/test/test_mcp_catalog_install.py"
    "src/test/test_data_git_tracking.py"
    "src/test/test_api_contract_routes.py"
    "src/test/test_api_contract_responses.py"
    "src/test/test_sse_contract.py"
    "src/test/test_openapi_contract.py"
)

Write-Host "==> CI pytest modules: $($MODULES.Count)"
uv run python -m pytest $MODULES -v --tb=short $args
