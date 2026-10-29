# open-items: fix what keryx 1.2.0 left open (bare and submodule worktrees, the run report, local paths, executor reads)

2026-10-29 · keryx run `open-items` · prepared as keryx 1.2.1

## What changed
- A subagent round no longer breaks a bare repository or a submodule. Its per-worktree push block made git apply the shared `core.bare` and `core.worktree` to every worktree; keryx now moves them to the main worktree's own config, as git's documentation says, and repairs a repository 1.2.0 left broken on the next round. keryx and the field recorder also look for `core.worktree` there, so a submodule's linked worktrees still find their runs.
- The drafted report needs no hand repair beyond its placeholders: the whole acceptance check with its indentation, the rounds of an L run's slices (named `<slug>-<name>` in the plan; a later run it does not name becomes a note to settle), both finders' counts, only the rulings that still stand (`Ruling (replaces row N): …`; `keryx.py log` prints each row's number and refuses a bad reference), and as deferred only rows labelled `(deferred)`. `finish` shows a ruling's reason.
- The report names no local path: besides the checkout and home, any path on this machine (scratch folders, `<checkout>.git`, symlinked checkouts, paths after `file://`, a flag or a colon) becomes a placeholder; only the system's programs and named devices (`/usr/bin/env`, `/dev/null`) stay. Non-ASCII folder names are no longer garbled.
- A GLM executor's permission rules refuse it every run and the memory (its config moved to `.keryx/glm/<slug>/`); the Cursor CLI's refuse it QA evidence, reproductions and the memory. They are permission rules, not a sandbox, and the docs now say so.
- Branch `release/1.2.1` (committed locally, not pushed).

## Proof
- Acceptance check: at db937b4 the 16 new and amended locked tests failed for the reasons above (adapter 125 run, 15 failures); at the head the adapter runs 136 tests OK, the recorder 33 passed and the benchmark 124 passed (2 skipped) on macOS, and the same suites pass on Linux with Python 3.12 from an export without `.git` (benchmark 123 passed, 3 skipped).
- Fresh reviews: four, each with two finders (risk list: privacy). The first found 1 P1 (a submodule's linked worktree lost its runs after the settings move) and 1 P2; the second and third found 2 P2 between them; the last found nothing above P3. Every confirmed P1 and P2 was fixed with a test that failed first; the P2 about permission rules was ruled (below).
- QA (`.keryx/runs/open-items/qa/QA.md`, kept where the run ran, not committed): a scripted walk-through on bare, submodule, 1.2.0-broken and ordinary repositories; 1.2.0's own report re-drafted from its real log; a live GLM round, which was refused the Read tool and `cat` on a QA file, another run's plan and the memory, read back its own large output and committed; five headless Claude Code sessions outside bypass mode; Codex's workspace-write sandbox.
- Mutation probes: 40, all caught.

## Open
- Not verified: a Cursor CLI round against its new rule (its weekly limit is reached); Codex as the coordinator of a whole run (its sandbox lets keryx write `.keryx/` but refuses `git commit`).
- Found, not fixed (older than this release): `.worktrees/` shows as untracked in `git status` of a repository whose `.gitignore` does not name it.
- Deferred minors: one GLM run can read another GLM run's transcripts in `.keryx/glm/`; a path with a space keeps its tail after the placeholder; an API route under a folder this machine has (`GET /home/…` on macOS) becomes a placeholder; a path glued to a one-letter name is hidden from that letter on; a `..` after a kept system prefix stays; `/proc/self/root/…` and `/usr/lib/node_modules/<package>` stay; a device path glued to more text (`>/dev/null&&`) or outside the named list (`/dev/fd/63`) becomes a placeholder.

## Rulings
- The coordinator made the tests-first commit and amended 1.2.0's locked tests where the decisions changed (the log prints row numbers; a sibling folder outside home is a placeholder; GLM's evidence-only deny replaced) — if wrong, an executor would have caught a test mistake one round earlier.
- The bare-repository tests drop keryx's push-blocking `GIT_CONFIG_*` variables from their environment, as GLM found an executor's shell carries them — no cost outside executors.
- GLM's and the Cursor CLI's read rules stay permission rules; OS-level isolation would also confine GLM's commits and network, so it is a new task — if wrong, a prompt-injected GLM could read QA evidence through a script it writes.
- A slice counts only when the run's plan or log names it; a later run it does not name is shown as a note, never counted or dropped silently — if wrong, the coordinator settles one note per unnamed slice.
- Path tests use fake roots that exist nowhere, since a path under a real folder now becomes a placeholder.
- GLM's path rule (not after two word characters) replaced the plan's, which contradicted its own `-I/tmp/…` test — if wrong, a one-letter relative folder becomes a placeholder.
- The second and third reviews' findings were fixed inline by the coordinator, test first, and each fix was reviewed again; only the system's programs and named devices stay in a report.

## Run
- 2h 13m wall clock, 2 executor rounds (1 FIX) on GLM (40 and 16 minutes); three small fixes inline; four two-finder reviews.
