# Security Policy

## About this project

This is a **personal portfolio project** demonstrating analytics engineering on a fully synthetic loan book. It is not a production service. No real customer data, credentials, or personally identifiable information exists in this repository.

## Reporting a vulnerability

If you discover a security issue, please report it by one of:

- **Email:** omer@cloover.co
- **GitHub Issue:** Open an issue on this repository

There is no bug bounty program. Reports will be acknowledged within a reasonable timeframe.

## Automated security scanning

The following scanners run on every pull request via GitHub Actions:

| Scanner | Scope | Purpose |
|---------|-------|---------|
| **bandit** | Python source (`src/`) | Static analysis for common Python security issues |
| **pip-audit** | Python dependencies | Known CVE detection in installed packages |
| **gitleaks** | Full git history | Secret and credential scanning |

Run locally with `make security` (bandit + pip-audit).

## Supported versions

Only the latest commit on the `main` branch is maintained. There are no backported security fixes to older commits or tags.
