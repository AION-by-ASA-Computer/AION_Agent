# Security Policy

## Supported versions

Security fixes are applied to the latest release on the `main` branch. Older tags may not receive backports unless noted in release notes.

## Reporting a vulnerability

**Do not open a public GitHub issue for security-sensitive reports.**

Please email security reports to the maintainers at ASA Computer via the contact channel listed on [https://aion-asa.com](https://aion-asa.com), or open a **private** security advisory on GitHub.

Include:

- Description of the issue and impact
- Steps to reproduce
- Affected versions or commit SHA
- Suggested fix (if any)

We aim to acknowledge reports within a few business days.

## Scope notes

AION Agent ships with **password auth** for chat and admin surfaces, **JWT** session tokens, and optional **multi-tenant** Docker deployment. Default development credentials (`admin` / `admin`) must be changed before any production exposure.

Before publishing or deploying:

- Set strong secrets (`AION_CHAT_AUTH_SECRET`, `AION_ADMIN_*`, database URLs)
- Run secret scanning (`gitleaks`, `trufflehog`) on your fork
- Do not commit `.env`, `data/`, or session sandboxes
