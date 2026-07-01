# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.0](https://github.com/AION-by-ASA-Computer/AION_Agent/compare/v1.0.0...v1.1.0) (2026-07-01)


### Features

* add availability checks for Opik telemetry and improve dynamic LLM configuration resolution ([cf5bfbc](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/cf5bfbcb128f011362cdb3a323cd37d1c82a5d0a))
* add LLM token configuration to setup, update debug flags, and adjust default prompt debug behavior ([4c08832](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/4c08832b2ac06bbaf1ce433ca6849e1e19638c2a))
* add normalize_litellm_provider function and update LiteLLMChatGenerator ([fbe939d](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/fbe939d708806a0f5ccbdd8f46923ebba1cb52e2))
* add normalize_litellm_provider function and update LiteLLMChatGeneratorWrapper to use it ([6aec389](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/6aec3898c988dae3aa056234b459df8fadf1d500))
* add support for excluding specific message IDs during STM windo… ([174ce21](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/174ce211ee64a52a3a3a7c28a339a2a22c8fbe18))
* add support for excluding specific message IDs during STM window retrieval and context compression ([57904f4](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/57904f49f8b651a5d8bcfe39bc0711370b4ca924))
* add support for filesystem policy mounting in container runtime ([c81a9be](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/c81a9be5e3e52c2ebd4ca216070e8eba645a61f1))
* implement first-setup flow, add OCR settings configuration, and introduce filesystem policy management API ([bc4f3f7](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/bc4f3f77b1962bbba3bf44d3ca1290ef91fe2e1d))
* tutorial setup ([46c74b3](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/46c74b3e8fb9887c31a5ac72b814cde6f1fc5f81))


### Bug Fixes

* ci workflow and codeowners. Updated contribution and branch protection policies ([fd48578](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/fd485789acd9d0d4a1f63899e3a905e3775d71e9))
* cron bug and multi-file upload ([64cfd66](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/64cfd66eb46b470aacee931abc4b215e3124da1a))
* cron bug and multi-file upload ([72678ff](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/72678ffc0074c95c235c78644afec03d80ab080f))
* restore actions:read on OSV PR job for reusable workflow ([e886dc8](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/e886dc8352c89394361b0efe36072071c2b1d8e9))
* restore workflow-level permissions for OSV reusable workflow ([70177ae](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/70177ae59dfb43eb2e1d5d9b6bc9d0eb18a5ebbb))

## 1.0.0 (2026-06-30)


### Bug Fixes

* correct formatting in skill discovery nudge documentation ([0907f9c](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/0907f9c12293e04e6bc6a16db10759d2994c13f5))
* correct formatting in skill discovery nudge documentation ([ea20bf3](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/ea20bf313671df369ad0c3a9bdde2884fc30503a))
* remove Anthropic-licensed skills from config_std ([f1dec12](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/f1dec12e8b685df9fa2119e2fdc3cc2e670bc128))


### Documentation

* add disclaimer section to README highlighting active development and liability limitations ([a292261](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/a292261a5faee31fe261e8aa87afe0d35387ff4a))
* add screenshots section to README for Chat and Admin UI visuals. ([4cba54e](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/4cba54eb77e32180fcd5b8d09ab0f0e65c78f963))
* enhance CONTRIBUTING.md with CI and security checks details ([f2080e7](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/f2080e7cd81957b5f55accad6704b43e6f3488a7))
* enhance README by centering screenshots for Chat and Admin UI sections ([21099bf](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/21099bfee629eed99ae3969c71b978985c37c565))
* README with badges and Docker-first quick start; restore gitleaks-action. ([f6c7f2d](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/f6c7f2d7eca71dd65f8b445d85e69de1edd7b445))
* update branch protection and CI workflow for Dependabot handling ([2787a57](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/2787a574aba6c7336b78f7ccf3472394f5ee76f8))
* update branch protection and CI workflow for Dependabot handling ([54c50d5](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/54c50d5bc69e07dea75b1a37e7ee2a56b9a2cde5))
* update branch protection documentation to include CodeQL checks ([ff78249](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/ff782499c9e955a8a2f17f1e63c45983439ae263))
* update branch protection policy to branch ruleset policy. ([f62e29f](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/f62e29f2b5cbb3176887b5f131559573e0542295))
* update branch protection rules and clarify bypass settings ([583e61f](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/583e61f187706ff3ebca2212095f51da172251ec))

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
