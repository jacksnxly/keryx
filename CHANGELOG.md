# Changelog

## 1.0.1 — 2026-10-28

- Linux: list processes with POSIX `ps` options, so leftover executor processes and test daemons are found and stopped (the BSD-style options listed nothing under procps).
- A benchmark test no longer depends on `~/.claude/projects` existing.

## 1.0.0 — 2026-10-28

keryx is now an agent workflow for software work, published as a Claude Code plugin. It replaces the release-notes generator this repository held up to v0.6.2 (still available at the `v0.6.2` tag).

- One loop for bugs, CI repair, features and PR review: an acceptance check that fails before the work, a plan with locked tests, an executor that writes tests first, a mechanical check, QA on the real surface (scripted and exploratory, with kept evidence), mutation probes, one fresh review, and a finish within the autonomy the owner gave.
- Executors set up once per machine: a Sonnet subagent that ships with the plugin (always available), the Cursor CLI, a GLM Coding Plan or a Cursor Cloud Agent; the next one takes over on any error, and usage limits are reported with their reset time.
- Architecture gates (guard tests, import contracts, dependency rules, CI config) flagged when an executor changes them.
- A domain-driven design lens wherever a change touches a business rule, owned data or an integration.
- Review: a written bar for findings with P0–P3 and confidence, production-reach and spec questions, two finders for risky diffs, a findings-only mode.
- keryx memory for the owner's recurring choices and a repository's traps (never secrets).
- `field/`: turn a real run into one record (time, tokens, questions, executor runs); `bench/`: a replay benchmark for workflow changes.
