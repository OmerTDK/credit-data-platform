# ADR-0010: Security CI layer (bandit + pip-audit + gitleaks)

**Status:** Accepted
**Date:** 2026-06-14
**Phase:** 5

---

## Context

The repo is destined to be public. Before that, every PR should be checked for
the three cheapest, highest-signal classes of security defect:

1. **Insecure Python patterns** (SAST) — e.g. shell injection, unsafe
   deserialization, hardcoded SQL string construction.
2. **Known-vulnerable dependencies** (CVE scan) — a transitive dep with a
   published advisory.
3. **Leaked secrets** — an API key or token committed to history.

None of these were enforced through Phase 4. This is also a *portfolio-wide*
pattern: the same job should drop into every repo as the reference implementation.

---

## Decision: a reusable `security` job on every PR

Add a dedicated `security` job to the GitHub Actions CI workflow, running in
parallel with the existing `lint-test` job on every `pull_request`:

- **bandit** (`uv run bandit -r src -c pyproject.toml`) — Python SAST over the
  source tree. Configured in `pyproject.toml` (`[tool.bandit]`, excluding
  `tests/` which legitimately uses asserts and crafted SQL strings).
- **pip-audit** (`uv run pip-audit`) — audits the locked dependency set against
  the Python advisory database. The local first-party package is skipped (not on
  PyPI), which is expected and not a failure.
- **gitleaks** (`gitleaks/gitleaks-action@v3` with `fetch-depth: 0`) — full-
  history secret scan. No `GITLEAKS_LICENSE` is needed because this is a personal-
  account repository; the action is free for personal accounts.

`make security` runs the two pip-installable scanners (bandit + pip-audit)
locally; gitleaks is a Go binary that runs in the CI job via the official action.

One real finding surfaced and was fixed properly rather than blanket-suppressed:
bandit flagged `B608` (hardcoded SQL) in the referential-integrity check. The
interpolated relation name comes from a fixed module-level allowlist
(`LOAN_FACT_RELATIONS`), never user input. The fix adds a runtime guard that
raises on any value outside the allowlist *before* any SQL is built, then a
targeted `# nosec B608` with the justification — so the scan stays strict
everywhere else.

---

## Alternatives considered

**Semgrep / CodeQL instead of bandit.** Heavier and slower; CodeQL is excellent
but overkill for a small first-party `src/` tree. bandit is fast, Python-native,
and pip-installable, so it also runs locally via `make security`.

**safety instead of pip-audit.** pip-audit is maintained by PyPA, reads the same
locked environment `uv` produces, and has a cleaner licensing story.

**trufflehog instead of gitleaks.** Both are solid; gitleaks has a well-supported
GitHub Action, is free for personal accounts, and needs no extra configuration.

**Fold security into the existing `lint-test` job.** Rejected — a separate job
runs in parallel (faster signal) and is trivially copy-pasteable into other
portfolio repos as the reference pattern.

---

## Consequences

**Easier:** every PR is scanned for SAST issues, dependency CVEs, and leaked
secrets; the job is a drop-in reference for the rest of the portfolio; bandit and
pip-audit also run locally in one command.

**Harder / committed to:** three more tools to keep current (bandit/pip-audit
pinned in dev deps, the gitleaks action pinned at `v3`); new real findings will
fail the PR — which is the point; pip-audit failures may originate from a
transitive dependency we do not own, requiring a pin bump or a documented
ignore.
