# Changelog

## 1.2.0 — 2026-10-29

- Every run's files now live in `.keryx/runs/<slug>/` in the repository's main checkout: the plan, the run log, locked tests, executor rounds, the review and QA evidence. The folder ignores itself, so it stays out of `git status`. They used to live in `.git/cursor-loop/`, where Claude Code prompts for every write an agent makes (and denies it in dontAsk mode), because `.git` is a protected path. Runs started before 1.2 finish where they started.
- Each finished run leaves a short report in the repository. `keryx.py report` drafts `docs/keryx/<date>-<slug>.md` from the run, the coordinator fills it in and commits it with the change, and `finish` refuses until it is there (`--findings-only` for a review that changes nothing). Screenshots, executor logs and the plan stay in `.keryx/`.
- The repository's memory moves to `.keryx/memory.md` with the first new note; until then the old file is still read.
- keryx's own names throughout: the adapter is `scripts/keryx.py` (`scripts/cursor.py` still works in this release), the fetched head is `refs/keryx/<slug>`, and errors start with `keryx:`.
- A GLM executor may not read `.keryx/`, since QA screenshots can show real people.
- The field recorder and the benchmark read executor logs in both places.

## 1.1.0 — 2026-10-28

- `cursor.py review-brief` writes the fresh reviewer's brief from a file that ships with keryx (`skills/keryx/prompts/reviewer.md`): the bar for a finding, P0–P3 and confidence, the reach and spec questions, the plan, the repository's rule files, where the reviewed commit is checked out, and the exact shape of the findings file. `--risk` adds a second brief with a security pass. The coordinator dispatches what the command prints instead of retyping the rules; a field run that retyped them lost the reach question and the grades.
- `cursor.py finish` decides when a run is finished. It refuses, and says what is missing, until the run log has a finish row and a well-formed fresh review covers the shipped commit (both finders for a risky diff); then it prints the report's facts: time, review counts, what shipped, rulings, deferred minors, executor rounds and the QA file. Three field runs in a row had ended without a finish row.

## 1.0.2 — 2026-10-28

- Usage-limit reports also recognise GLM's weekly/monthly message (code 1310); 1.0.1 knew only the 5-hour one (1308).
- A project site at https://jacksnxly.github.io/keryx/, a plugin icon, a social preview image and clearer descriptions for search.

## 1.0.1 — 2026-10-28

- Linux: list processes with POSIX `ps` options at unlimited width (`-ww`), so leftover executor processes and test daemons are found and stopped (the BSD-style options listed nothing under procps, and piped output was cut at 80 columns).
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
