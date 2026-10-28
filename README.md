# keryx

[![test](https://github.com/jacksnxly/keryx/actions/workflows/test.yml/badge.svg)](https://github.com/jacksnxly/keryx/actions/workflows/test.yml)

keryx is one workflow for software work done by a coding agent: fixing a bug or a red CI job, building a feature from a spec, or reviewing and fixing a branch. A strong model plans, checks and reviews; a cheaper executor writes the code; nothing counts as done until a check that failed before the work now passes.

It is a [Claude Code](https://code.claude.com/docs) plugin. It needs nothing else: without any other tool, a Sonnet subagent writes the code. Cursor and a GLM Coding Plan can be added as cheaper executors.

## Install

```bash
claude plugin marketplace add jacksnxly/keryx
claude plugin install keryx@keryx
```

Inside a session the same works as `/plugin marketplace add jacksnxly/keryx` and `/plugin install keryx@keryx`. Requirements: Claude Code, git, Python 3.11 or later.

## Use

Ask for the work and say keryx, or call it directly:

```
/keryx:keryx fix the failing checkout test
/keryx:keryx build the export button from docs/spec/export.md
/keryx:keryx review and fix this branch
/keryx:keryx review this PR, findings only
```

keryx remembers the choices you make that will come up again (your executor order, how far it may go, a repository's traps) in `~/.config/keryx/memory.md` and, per repository, in `.git/cursor-loop/memory.md`. It never stores a secret; edit or delete either file at any time.

The first time it needs an executor, keryx runs a short setup: it shows which executors it found on this machine and asks which to use, in which order. The answer is saved in `~/.config/keryx/config.json`; say "keryx setup" to change it.

| Executor | What you need |
|---|---|
| `subagent` | Nothing: the plugin's `keryx:executor` agent on Sonnet. Always available. It runs with your session's environment, without MCP tools, and cannot push from its worktree. |
| `cli` | The [Cursor CLI](https://cursor.com/cli), logged in (`agent login`). |
| `glm` | A GLM Coding Plan key in `$GLM_API_KEY` or `~/.config/glm/coding-plan.key`. |
| `cloud` | A Cursor API key and the repository on GitHub. |

When an executor fails (an error, a stop, a dispatch that never starts), keryx moves the same work to the next one in your order, and writes the code itself after the last.

## How a run goes

1. **Size the work.** S is done inline; M gets a plan, an executor and one review; L is split into slices that run in parallel.
2. **Intake.** keryx reads what it can, asks only what it cannot find, one question at a time, and asks once how far it may go: commit, push, open a PR, merge, deploy.
3. **An acceptance check that fails first.** Who accepts the work and what they look at becomes a command, a test or a comparison, run on the base before anything is built.
4. **Plan and locked tests.** Decisions and exact tests, no implementation code. The tests are locked: an executor that changes one fails the check.
5. **Execute.** Tests first, shown to fail for the stated reason, then the code.
6. **Check.** Mechanical first (locked tests intact, diff inside its bounds, architecture gates untouched, no assistant attribution), then QA on the real surface and mutation probes that break the change on purpose.
7. **One fresh review** of the whole branch, each finding checked before it is acted on.
8. **Finish** within the autonomy, with a short report: what changed, the proof, what is open, and every ruling made on your behalf.

Every decision is logged as it is made (`<git-common-dir>/cursor-loop/<slug>/decisions.tsv`), so a run can be picked up after a context reset.

## What is in the repository

- `skills/keryx/` — the workflow (`SKILL.md`, `references/`) and the executor adapter (`scripts/cursor.py`).
- `skills/evidence/` — the always-on rule: get the evidence that could prove a claim wrong before making it.
- `agents/executor.md` — the Sonnet executor agent.
- `bench/` — a replay benchmark that compares workflow versions on recorded tasks.
- `field/` — reads a real run's transcript and run log into one record: time, tokens, questions, executor runs.

## Tests

```bash
(cd skills/keryx && python3 -m unittest discover -s tests)
(cd field && python3 -m pytest -q)
(cd bench && uv venv .venv && uv pip install --python .venv/bin/python -r requirements.txt && .venv/bin/pytest -q)
```

No test calls a model. Live benchmark runs need `KERYX_LIVE=1`.

## History

Up to v0.6.2 this repository held a release-notes generator; it is still available at the [`v0.6.2` tag](https://github.com/jacksnxly/keryx/tree/v0.6.2). See `CHANGELOG.md` for keryx 1.0.

## Security and contributing

Report vulnerabilities privately (see `SECURITY.md`). How to propose changes: `CONTRIBUTING.md`.

## License

MIT, see `LICENSE`.
