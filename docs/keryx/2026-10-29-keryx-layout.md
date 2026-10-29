# keryx-layout: every run's files in .keryx/, a committed run report in docs/keryx/, and keryx's own names

2026-10-29 · keryx run `keryx-layout` · released as keryx 1.2.0

## What changed
- A run's working files (plan, run log, locked tests, executor rounds, review, QA evidence) now live in `.keryx/runs/<slug>/` in the repository's main checkout, a folder that ignores itself. They used to sit in `.git/cursor-loop/`, where Claude Code prompts for every agent write (and denies it in dontAsk mode). Runs started earlier finish where they started.
- Each finished run leaves a report like this one in `docs/keryx/`, drafted by `keryx.py report` and required by `finish` (`--findings-only` for a review that changes nothing).
- The adapter is `scripts/keryx.py` (`scripts/cursor.py` still works for this release); refs are `refs/keryx/<slug>`; the repository's memory moves to `.keryx/memory.md`.
- keryx finds the main checkout in submodules, separate git dirs and bare repositories' worktrees; `finish` works from any folder.
- Branch `release/1.2.0`, merged to `main`, tag `v1.2.0`.

## Proof
- Acceptance check: the locked tests at 93c181f (adapter 102 run: 4 failures and 22 errors, each because the layout, the report or the names did not exist yet; recorder 1 failed; benchmark 4 failed) — now adapter 112 OK, recorder 31 passed, benchmark 124 passed (2 skipped), on macOS and on Linux with Python 3.12.
- Fresh reviews: four, each with two reviewers (risk list: privacy). They found 2 P1 and 10 P2 in total: 1 P1 and 9 P2 fixed, each with a test that failed first; one P1 (GLM may read most of `.keryx/`) ruled, since 1.1 exposed the same; one P2 (other absolute paths in the report) fixed for the checkout and home, the rest deferred. The last review found none above P3.
- QA: a scripted walk-through in throwaway repositories (fresh repo, linked worktree, old-layout run, report draft refused until filled in, `git status` clean, ripgrep skips `.keryx/`), kept with the run, not committed.
- Mutation probes: 27, all caught (one probe was first written too weakly and re-run).

## Open
- Not verified: a coordinator session in default permission mode writing into `.keryx/` (this machine runs in bypass mode), and Codex as host.
- Known, not fixed here: in a bare repository, `create --runner subagent` turns on `extensions.worktreeConfig`, after which `git status` fails in every worktree (it did before this release too).
- Deferred minors: the Cursor CLI and subagent executors have no read deny for QA evidence; report path stripping misses a `<checkout>.git` sibling outside home, non-ASCII names and symlinked checkouts; the draft cuts a multi-line acceptance check at its first line and counts only the coordinator slug's executor rounds; superseded rulings are listed unmarked; the recorder's copy of the main-checkout rule has no bare-repository test.

## Rulings
- The coordinator made the tests-first commit (renames, 25 mechanical test edits, locked tests); executors started from it — if wrong, a test mistake would have been caught one round later.
- Existing `finish` calls in the tests use `--findings-only`; the report gate has its own tests.
- GLM may not read a run's QA evidence or reproductions in `.keryx/`; the rest stays readable, because its own config lives there (first cut denied the whole folder; superseded).
- A bare repository keeps `.keryx/` in its own folder, so two bare repositories never share runs or memory (first cut used the parent folder; superseded).
- One-character slugs are accepted, so the run log path is validated too.
- The last fix (one regular expression) was made inline by the coordinator, test first, and reviewed like the rest.

## Run
- 1h 53m wall clock in the coordinator's log; 7 executor rounds: slice A 3 on GLM (2 of them fixes), slice B 1 on Cursor (stopped by its weekly limit) and 3 on the Sonnet subagent (2 fixes).
