# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## 1.0.0 (2026-06-29)


### Documentation

* add disclaimer section to README highlighting active development and liability limitations ([8f594c7](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/8f594c7f41f8cd0f72b3c60029311514ddbb12a5))
* add screenshots section to README for Chat and Admin UI visuals. ([f1e691a](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/f1e691af978e93d4e2b427a0e72ff2db182f30ed))
* add screenshots section to README for Chat and Admin UI visuals. ([a0b95b2](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/a0b95b25da668ca948142cf23a7cc879c40c83c6))
* enhance README by centering screenshots for Chat and Admin UI sections ([2a658b5](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/2a658b5fa555973272e86cde20528ff599464330))
* README with badges and Docker-first quick start; restore gitleaks-action. ([2b88a1c](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/2b88a1c20e2dcbe26233ba5a1b9dd2ae43c29568))
* update branch protection policy to branch ruleset policy. ([91af524](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/91af52430792c5cfc815cb7063dbf54faa357475))

## [Unreleased]

### Added

- `TurnContext` builder extracted from `AgentPipeline.run_stream` with unit tests
- `StreamLoop` v2 streaming path behind `AION_STREAM_LOOP_V2` / `settings.stream_loop_v2`
- TypeScript `PlanEditor` as default plan dock UI (legacy editor behind env flag)
- Central `AionSettings` with startup validation for `AION_API_URL`
- Open-source community files: LICENSE (Apache-2.0), CONTRIBUTING, SECURITY, CODE_OF_CONDUCT
- CI check preventing tracked runtime files under `data/`
- Integration smoke tests for `/v1/chat/stream` with fake LLM
- Release automation: release-please, GHCR image publish, `docker-compose.ghcr.yml`

### Changed

- Plan Mode: tool-first flow, unified plan dock, task descriptions in execution UI
- README rewritten in English; Italian moved to `README.it.md`

### Fixed

- Legacy stream loop indentation regression in `agent_pipeline.py`
- JSON recovery patch uses Haystack-scoped proxy (thread-safe, no global `json.loads` mutation)
