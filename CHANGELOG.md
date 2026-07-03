# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.0](https://github.com/AION-by-ASA-Computer/AION_Agent/compare/v1.0.0...v1.1.0) (2026-07-03)


### Features

* abilitazione profili pannello admin per singolo utente ([e3f3f58](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/e3f3f58b731075c746711c01c1122d4fe008b491))
* add availability checks for Opik telemetry and improve dynamic LLM configuration resolution ([cf5bfbc](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/cf5bfbcb128f011362cdb3a323cd37d1c82a5d0a))
* add LLM token configuration to setup, update debug flags, and adjust default prompt debug behavior ([4c08832](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/4c08832b2ac06bbaf1ce433ca6849e1e19638c2a))
* add llm_provider_name support to chat metadata and overhaul dashboard UI with real-time monitoring and analytics. ([cf95e85](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/cf95e85235980ebe180b5543917c5a0da7a03f28))
* add llm_provider_name support to chat metadata and overhaul dashboard UI with real-time monitoring and analytics. ([4557698](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/4557698611ce797c7c2c97d93d6222cc76fbb981))
* add normalize_litellm_provider function and update LiteLLMChatGenerator ([fbe939d](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/fbe939d708806a0f5ccbdd8f46923ebba1cb52e2))
* add normalize_litellm_provider function and update LiteLLMChatGeneratorWrapper to use it ([6aec389](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/6aec3898c988dae3aa056234b459df8fadf1d500))
* add OCR disabled UI state, normalize LiteLLM vLLM provider mapping, and update gitignore for plugin bytecode ([154615e](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/154615e5b7cf50de8b963730df32331dc39e6212))
* add OCR mode support and enhance probing functionality in FirstSetupPage ([e2c8668](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/e2c8668957d8d30889c722f8dc34270067343ad1))
* add OCR toggle, update default thinking token budget, and initialize project documentation ([9fa3aae](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/9fa3aaecef8ef15d997c2c2a8ed0d2e121444db7))
* add policy editor UI with YAML parsing support and implement in-process environment reloading for settings updates ([fa3889b](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/fa3889b49f3da54c4e2059eb3ccfe2e61e3c21ff))
* add policy editor UI with YAML parsing support and implement in-process environment reloading for settings updates ([d70777d](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/d70777dada92b076f32cdbad7980593e5d0deaec))
* add support for excluding specific message IDs during STM window ([174ce21](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/174ce211ee64a52a3a3a7c28a339a2a22c8fbe18))
* add support for excluding specific message IDs during STM window retrieval and context compression ([57904f4](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/57904f49f8b651a5d8bcfe39bc0711370b4ca924))
* add support for filesystem policy mounting in container runtime ([c81a9be](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/c81a9be5e3e52c2ebd4ca216070e8eba645a61f1))
* aggiunta possibilità di disabilitare (nullo, minimo, completo) … ([5a06a5f](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/5a06a5ff2b9e2b52e4c78f256482ccdab667a206))
* aggiunta possibilità di disabilitare (nullo, minimo, completo) la visualizzazione delle chiamate tool/MCP ([1a38cd8](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/1a38cd83f8b43d4b8b0a930438fff643e9ac23f6))
* enhance error handling in LLM streaming and context management ([13964fd](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/13964fd6b4c894362d7e81eab139ef9a22f3091a))
* enhance LLM probing and model management in FirstSetupPage ([9981dc6](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/9981dc66f22988b67448abd6674ddc66111c7f37))
* enhance LLM provider probing and connection management ([b94aa48](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/b94aa48a35a718d1245ae400799a1f1b7f2b16ea))
* implement first-setup flow, add OCR settings configuration, and introduce filesystem policy management API ([be4f3f7](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/bc4f3f77b1962bbba3bf44d3ca1290ef91fe2e1d))
* implement LLM provider probing functionality ([ef6d9ea](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/ef6d9eaf1b6392afbef1f4ea205e4e1df3ebc297))
* implement model selection UI with i18n support, update OCR configuration to require model input, and improve security by adding autocomplete attributes to API key fields. ([227f57c](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/227f57c46756eb03c2f17bbef98428fe837107e1))
* implement model selection UI with i18n support, update OCR configuration to require model input, and improve security by adding autocomplete attributes to API key fields. ([d5e27ef](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/d5e27efc8655f7cd2584baad78f1f2fbdd08eadf))
* improve LLM provider settings and cache management ([ade4662](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/ade4662bca677b689dc0fc8a1bae23a2bbd4f0fc))
* tutorial setup ([46c74b3](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/46c74b3e8fb9887c31a5ac72b814cde6f1fc5f81))
* user profile management ([94796ab](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/94796ab289b7dc80a60be5df5769d3f1aa7858c5))


### Bug Fixes

* ci workflow and codeowners. Updated contribution and branch protection policies ([fd48578](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/fd485789acd9d0d4a1f63899e3a905e3775d71e9))
* **ci:** activate .venv-ci before uv pip install in Docker job ([85b022d](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/85b022d8d915186bf8bccd4a19c7b6da27e8b6c0))
* **ci:** drop flaky GHA cache from release image builds ([7f4b75f](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/7f4b75fa59781b12a0b16563bca6261800e58f57))
* **ci:** drop flaky GHA cache from release image builds ([2b42946](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/2b4294674eb65f53d8b707a20b887971815df347))
* **ci:** enable GHCR image publish on release ([c78be3e](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/c78ba3ef9f0046474c9bb64f126f6e4709406b35))
* **ci:** enable GHCR image publish on release ([b624838](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/b62483861cad23c3f0656ac476d6151cb8e243e4))
* **ci:** grant OSV scheduled job permissions for reusable workflow ([319965e](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/319965e6ceae3252662d09d6281e379ddfc76dff))
* **ci:** publish GHCR images for amd64 and arm64 ([a8d2a7d](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/a8d2a7d6a3c67dde71770d4f730a455da8fd3e22))
* **ci:** publish GHCR images for amd64 and arm64 ([4cbf306](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/4cbf3064c1b652b60b2411e833d36f104d9bc5d3))
* **ci:** repair OpenSSF Scorecard workflow and supply-chain checks ([b78bb87](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/b78bb87447a7965283f2c7b0be33c15015675e17))
* **ci:** repair OpenSSF Scorecard workflow on main ([ed20861](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/ed208611a47111022c9d52e22a8b680d125723ec))
* cron bug and multi-file upload ([64cfd66](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/64cfd66eb46b470aacee931abc4b215e3124da1a))
* cron bug and multi-file upload ([72678ff](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/72678ffc0074c95c235c78644afec03d80ab080f))
* document upload bug ([f93afa6](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/f93afa65064618f5f86f626b53d0defc1ede6888))
* document upload bug ([467d984](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/467d984be72e444309d6d590ec16765a27fd2ab7))
* format ruff ([682867f](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/682867f0164e7f00b8e1af31c34c71e44779118c))
* **fuzz:** bundle-friendly imports for ClusterFuzzLite PyInstaller ([a40d0e8](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/a40d0e835acc940078af3db3ac501cb73f62a6ad))
* **fuzz:** load api_key module without FastAPI package init ([7e0d173](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/7e0d173343ff61eb82079f9a7aab62dc9ceba20c))
* **fuzz:** use atheris.instrument_imports per official API ([4fde156](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/4fde156799eba106c675ad267c6db14dda41d98f))
* initial setup not checking for real connections and env misalignment between local and docker ([768d886](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/768d88623da63056252567e01a9300e6d4c91914))
* linting errors ([d054dd2](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/d054dd23438f1667f3d47ae92aa7fa12499786a9))
* ocr and policy ([1df5d1c](https://github.com/AION-by-ASA-Computer/AION_Agent/commit/1df5d1c44864612ce0a73ec799f3b0c629141975))
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
