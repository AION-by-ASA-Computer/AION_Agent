## Summary

<!-- What changed and why? Link issues if applicable. -->

## Type of change

- [ ] Bug fix
- [ ] Feature
- [ ] Documentation
- [ ] CI / tooling
- [ ] Breaking change (describe in Notes)

## Test plan

- [ ] `./scripts/run_ci_tests.sh` (or `python -m pytest src/test/...` for affected modules)
- [ ] `uv run ruff check --config ruff.toml src/` (lint — same as CI)
- [ ] `uv run ruff format --check --config ruff.toml src/` (formatting — CI fails if this is skipped)
- [ ] Auto-fix formatting if needed: `uv run ruff format --config ruff.toml src/`
- [ ] `python scripts/check_data_git_tracking.py`
- [ ] Frontend build if UI touched (`cd <package> && pnpm build`)
- [ ] Manual smoke test:

## Security / OSS checklist

- [ ] No secrets, `.env`, or internal IPs in the diff
- [ ] No new tracked files under `data/` (except whitelisted fixtures)

## Notes

<!-- Breaking changes, migrations, follow-ups -->
