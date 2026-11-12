# Changelog

## 1.8.0 — 2026-11-12

- **An optional research agent.** `keryx.py setup --research codex` saves `"research": {"agent": "codex"}` in `config.json` (`--research none` removes it; `"model"` and `"effort"` are optional). Ground truth then hands outside research — official docs, versions, how a library or API behaves — to `keryx.py research --slug <slug> "<question>"`, which runs `codex exec` with the owner's own Codex login, read-only, with live web search, and without the owner's Codex config, execpolicy rules, plugins, apps and memories (in a probe, the owner's config loaded a production connector). The answer is printed with its sources, credentials masked, saved as `<state>/research/NN.md` (each call claims its number before the agent runs, so parallel sessions never share one) and logged as a `ground-truth` row. Nothing is set by default: the command then exits 3 and the session researches as before; a failed run exits 1 and says so.

## 1.7.3 — 2026-11-12

- **One status block for a session that drives several runs.** `keryx.py progress --slug <run> --slug <other run> …` prints one row with a bar per run (`| **smart-search** | 2 of 6 · ▶▶▶▶ … · Part 1 |`) above Live, Waiting and Next, and lists the open questions of those runs under it, each with its run's name. Without `--slug` it prints the three rows for a session with no run (`--waiting` says what waits). Seen in the field: a session with two runs ran `progress` for each and then typed a three-row table by hand, 14 times, so its block had no bar. The command also reminds on stderr to paste the block as printed.
- `progress` says on stderr when a run's log went on (five rows or more) while its steps were never ticked, since the bar shows only what was ticked: a field run declared ten steps and stayed at "1 of 10".

## 1.7.2 — 2026-11-12

- **The status block is a table again, built to stay one.** A terminal draws a Markdown table as a grid only while no cell needs more than about four lines: a 97-character cell held at 50 columns, a 164-character one came out as stacked "Header: value" records at 60. So every cell of the block stays within 96 shown characters: `keryx.py progress` refuses a `--live` or `--next` text longer than that, a long plan folds its finished steps into a count (`8 done → **[Part I]** → Part J → 2 more`), and the open decisions are listed under the table, never inside it. The labels are single words (`Step`, `Plan`, `Live`, `Waiting`, `Next`), which cannot wrap when the table is squeezed. Checked in the terminal at 50, 60, 80, 100 and 120 columns. `--full` stays a numbered list.
- **A session's status block shows only its own run's questions.** Since 1.7.0 it showed every open question of the repository, so each parallel session repeated one run's questions: in the field one run asked ten, four sessions showed them, and the owner answered once and then told three more sessions "already answered". **Waiting** is now the questions of the run named by `--slug` and of the slices it names; `keryx.py inbox` and `inbox --all` remain the one list across runs.

## 1.7.1 — 2026-11-12

- **The status block is a list, not a table.** In a terminal, a Markdown table is drawn as a grid, as stacked "Header: value" records or as raw pipes, by the terminal's width: at 60 columns the block of 1.7.0 repeated its step and bar as field names on every row, and at 80 and 120 columns its labels were squeezed and wrapped. `keryx.py progress` now prints a bold line with the step, the bar as a code span, and **Plan**, **Live**, **Waiting on you** and **Next** as list items, with each open question and its options as a nested list; `--full` prints the plan as a numbered list. Checked in the terminal at 50, 60, 80 and 120 columns.
- Open questions are listed oldest first, in the status block and in `inbox`, so a question keeps its number from one message to the next: the order used to follow the file system's folder listing, which differs between macOS and Linux.

## 1.7.0 — 2026-11-12

From five days of field data after 1.6.0 (162 run folders in 11 repositories, 329 executor rounds, 273 owner prompts): inside a run keryx rarely stalled, but the owner was still the scheduler between runs — about 50 prompts were a "go", 15 a "what's next?", 14 a "post merge cleanup" — and limits, review loops and a `finish` with one shape cost rounds.

- **Standing grants** (`keryx.py grants`, `keryx.py grant <action> allow|ask [--repo] --source "<the owner's words>"`): one file on the machine, `grants.json` beside the config, says per repository whether `push`, `pr`, `merge`, `deploy-staging`, `deploy-production`, `production-data` and `branch-delete` need the owner, and how far `followups` may start on their own (`none`, `safe`, `all`). `recall` prints it. The skill named a grants file before; none existed.
- **The owner's inbox** (`keryx.py ask`, `answer`, `inbox [--all]`): a question for the owner is a row with its options, the recommended one first, and what it blocks; `inbox --all` lists the open ones across every repository under the config's `roots`. Every "Waiting on you" line repeats them in full.
- **Follow-ups**: a run logs each follow-up it recommends as a `next` row marked `safe`, `risk` or `price`; `finish` and `inbox` print `start` or `ask` for each by the `followups` grant, and a started follow-up runs as its own run with its own intake. A price always asks.
- **`keryx.py cleanup --slug <slug>`** removes the executor worktrees and branches of a run and its slices that are merged into the target (a squash merge counts) and hold no uncommitted work, under the `branch-delete` grant; without the grant, or with `--dry-run`, it prints what it would remove. It never removes a worktree whose own checkout sits on an unmerged commit, a branch checked out elsewhere, a worktree outside `.worktrees/`, or anything of a run with a round still running.
- **`finish` knows more than one shape.** It reads the size from the log's `size` row: a size S run finishes on its finish row (and has no executor rounds). `--qa-only` finishes a run that only tested, `--umbrella` one whose slices each printed FINISHED; neither when the run has executor rounds that wrote code, and never a hotfix. A repository that keeps no run reports (`keryx.py repo --report local`) has them in `<state>/REPORT.md`. An M or L run needs its QA file (`<state>/qa/QA.md`, or its run's for a slice), or a ruling `Ruling: no QA file — <why>`. A run without a size row finishes as before, with a note.
- **At most three review rounds**: `review-brief` refuses a fourth unless `--extra "<why>"` logs the reason. Rounds 4 to 9 of three field runs found no P0 or P1 in 13 rounds.
- **QA is a brief mode** (`Mode: QA`): an executor works through a case list on the real surface and reports each case as expected or different; the coordinator judges. Four such sessions found 10 confirmed defects in a run that had printed FINISHED.
- **Limits before a round**: `create` and `followup` refuse a runner that is at its usage limit, before a worktree or a round folder exists, and name the next rung (`--ignore-limit` for a limit that lifted early). An optional cap, `"maxParallel": {"<runner>": N}` in `config.json`, refuses a round past N running ones.
- **A provider's 429 is retried**: `wait` opens the next round with the same brief after two minutes and again after four (`--rate-wait`, `--rate-retries`), and records the limit only when the last retry also hits it.
- **The CI-parity command** per repository (`keryx.py repo --ci "<command>"`, printed by `recall`): a done-when command of every plan, run on the final head before the first push.
- **Run-log rows a program can read**: the phase is one word (a sentence in its place is refused; `ground truth` and `ground` become `ground-truth`; an unknown word is kept with a note), and a `size` row takes `S`, `M` or `L`.
- Fixes: a `followup` whose brief file is missing no longer leaves an empty round folder that breaks every later command; a locked block that ends in a comma is found; `locked`, `gates`, `review-brief` and `finish` on a slice read the run's locks, gate list, plan and QA file; `report` writes into the checkout that holds the shipped head (`--into <path>` names one).
- **The plan and the place in it**: a run declares its steps once (`keryx.py steps`), ticks them as they start and end (`keryx.py step`), and `keryx.py progress --slug <slug> --live … --next …` prints the status block that closes every message: a table with the step the run is on, a bar with one segment per step, the plan with the current step marked, what is live, the owner's open questions straight from the inbox, and what is next. `--full` prints the whole plan as a table. No emoji; the same table reads in a terminal and in the apps.
- The owner's commands (`grant`, `repo --ci`, `repo --report`, `ask`, `answer`, `cleanup`, and `answer` or `next` rows through `log`) refuse to run inside a Cursor, GLM or provider round (`KERYX_EXECUTOR=1` in its environment).
- Briefs are written with the file tool, never through a shell heredoc: an unquoted one ran the commands a brief quoted.

## 1.6.0 — 2026-11-07

- **Provider executors**: a provider declared in `config.json` (`"providers": {name: {"runner": "codex", "baseUrl": …, "keyFile": …, "model": …}}`) runs as a keryx executor through `codex exec`, under its own name: `create --runner <name>` works like any local runner (`.worktrees/<name>-<slug>`, branch `<name>/<slug>`), takes part in the ladder, the reset order and usage limits, and `followup` resumes its thread. The key is read from `keyFile` (a `key` field is refused) and reaches the executor only as `$KERYX_CODEX_API_KEY`, in a `CODEX_HOME` keryx writes per run (`.keryx/codex/<slug>/`) with the provider's endpoint, no login and no MCP servers; it is never printed or written anywhere a run keeps. `preflight --runner <name>` checks the Codex CLI, the key file's mode and one probe run. An HTTP 402 from the provider is read as an allowance that resets on the first of the next month; a 429 as a ten-minute rate limit.
- A Codex provider round has full access on this machine (it can read the provider's key file and the run records under `.keryx/`, unlike the glm runner's read rules). gh gets a placeholder token so gh commands fail; no git credentials over HTTPS and git over SSH off; pushes go nowhere. The guards stop mistakes, not a determined executor that runs with your user's rights (keychain, SSH keys).
- The `description` frontmatter of both skills is quoted, so strict YAML parsers read it (it contains a colon plus space).

## 1.5.0 — 2026-11-04

- **Reset order** (opt-in): with `"order": "resets"` in `config.json`, `keryx.py executors` lists first the executor whose plan resets soonest, so a quota that lapses at its reset is used up before one that keeps. Executors without a reset date follow in the saved order, a runner at its usage limit is still left out, and stderr says which reset put each one where. Turn it on with `keryx.py setup --order resets --reset cli=2026-11-06/month --reset glm=2026-11-11T03:24:16Z/week`; each date rolls forward by its period (`month`, `week`, or none for once), and `--order ladder` turns it off while keeping the dates. keryx never asks a provider for usage: the dates are the owner's. Seen in the field: every round of a day went to GLM, which resets on the 11th, while Cursor's quota was due to lapse on the 6th.
- With the reset order off (the default, or `"order": "ladder"`), nothing changes: saved dates are ignored, even malformed ones.
- `keryx.py setup` keeps every other setting in `config.json`, including keys it does not know, and saves only what keryx can read back: a bad value is refused and nothing is written, while `--order ladder` turns the reset order off even when a hand-edited date is broken. An order or a reset date is saved only next to a ladder someone chose, so on a new machine it needs `--executors` in the same call, and the first-use setup question still comes. A `config.json` that is not valid JSON is still replaced by a new ladder, as in 1.4.0, and now kept beside it as `config.json.broken`.

## 1.4.0 — 2026-11-02

From a week of field data (71 runs): the owner's most common check-in was "where are we, what's next?", the second was a nudge after keryx stopped while it waited, and most false "done"s were UI builds that missed their design master.

- Reports lead with their proof and close with **Live / Waiting on you / Next**. `keryx.py report` drafts the Proof section first and a last `## Now` section, which `finish` waits for like any placeholder; every message that ends a turn follows the same shape.
- keryx no longer ends a turn idle while work is in flight: a background watch wakes the run (`keryx.py wait`, `gh run watch`, `gh pr checks --watch`, a polling script), and a `waiting` row in the run log says what it waits on and until when. Under granted autonomy a report is not a stopping point.
- A usage limit is remembered for every session on the machine (`limits.json` beside the config): `keryx.py executors` leaves the limited runner out, says until when, and lists it first again once the reset has passed, so a run returns to the preferred executor without being told.
- UI work against a design master is accepted screen by screen, master and build side by side in the QA file; UI without a master shows 2–3 directions as screenshots before it is built.
- A price, credit cost or billing rule the owner has not set is asked on its own, with a worked customer example, even when the owner delegated every other decision.

## 1.3.0 — 2026-10-29

- A hotfix lane. Urgency is a second axis next to size: when the owner says hotfix, urgent or prod is down (or calls `/keryx:hotfix`), or keryx finds live harm and the owner agrees, the session's own model fixes it at once, with no plan file and no executor round: it sees the harm itself, tries the fastest safe action first (a revert, a flag, a rollback), otherwise ships the smallest change behind a regression test that fails first, and gets one fast fresh review (`keryx.py review-brief --hotfix`: the diff only, P0 and P1 only, on the strongest model). Never for work that is merely small or quick.
- The lasting fix is enforced: a hotfix run logs a `followup` row naming its follow-up run, and `keryx.py finish` refuses until that run has a log (or a ruling says the hotfix is the lasting fix). The report names the follow-up.

## 1.2.2 — 2026-10-29

- An executor round leaves `git status` clean. `.worktrees/`, where each executor's worktree lives, now ignores itself as `.keryx/` does, so it no longer shows as untracked in a repository whose `.gitignore` does not name it, and no longer makes a submodule look modified in its superproject. A `.worktrees/` an older keryx left is ignored from the next round on.

## 1.2.1 — 2026-10-29

- A subagent round no longer breaks a bare repository or a submodule. The round blocks pushes through a per-worktree setting, and turning that on made git apply the shared `core.bare` and `core.worktree` to every worktree: in a bare repository `git status` failed in all of them, and a submodule's linked worktree pointed at the wrong folder. keryx now moves those two settings to the main worktree's own config, as git's documentation says, and repairs a repository 1.2.0 left broken on its next subagent round.
- The drafted report needs less hand repair: it copies the whole acceptance check, counts the executor rounds of an L run's slices (`<slug>-<name>`, named in its plan or log; a later run it does not name is pointed out, not counted), shows both finders' counts for a risk-list review, lists only the rulings that still stand (`Ruling (replaces row <N>): …`, with `keryx.py log` now printing each row's number), and lists as deferred only rows labelled `(deferred)`. `finish` shows each ruling's reason rather than its evidence.
- The report names no local path at all: besides the checkout and home folder, any other path on this machine (a scratch folder, a sibling such as `<checkout>.git`, a checkout reached through a symlink, a path after `file://`, a flag or a colon) becomes a placeholder to rewrite, the system's programs and devices such as `/usr/bin/env` and `/dev/null` excepted, which `finish` refuses until it is gone. Folder names with non-ASCII letters are no longer garbled.
- A GLM executor's permission rules now refuse it every run and the repository's memory; its own Claude Code config moved to `.keryx/glm/<slug>/` to allow that. The Cursor CLI's rules refuse it QA evidence, reproductions and the memory. These are permission rules, not a sandbox: they cover the file tools and commands such as `cat`, not a script that opens a file itself.
- keryx and the field recorder find a submodule's checkout from its linked worktrees after the settings move, and a GLM run's config folder no longer needs a repository around the current directory.
- Checked outside bypass mode: in acceptEdits mode a session writes `.keryx/` and is refused `.git`; from a linked worktree it needs `--add-dir`. Codex's workspace-write sandbox lets keryx write `.keryx/` (it refuses `.git`, including commits).

## 1.2.0 — 2026-10-29

- Every run's files now live in `.keryx/runs/<slug>/` in the repository's main checkout: the plan, the run log, locked tests, executor rounds, the review and QA evidence. The folder ignores itself, so it stays out of `git status`. They used to live in `.git/cursor-loop/`, where Claude Code prompts for every write an agent makes (and denies it in dontAsk mode), because `.git` is a protected path. Runs started before 1.2 finish where they started.
- Each finished run leaves a short report in the repository. `keryx.py report` drafts `docs/keryx/<date>-<slug>.md` from the run, the coordinator fills it in and commits it with the change, and `finish` refuses until it is there (`--findings-only` for a review that changes nothing). Screenshots, executor logs and the plan stay in `.keryx/`.
- The repository's memory moves to `.keryx/memory.md` with the first new note; until then the old file is still read.
- keryx's own names throughout: the adapter is `scripts/keryx.py` (`scripts/cursor.py` still works in this release), the fetched head is `refs/keryx/<slug>`, and errors start with `keryx:`.
- A GLM executor may not read a run's QA evidence or reproductions in `.keryx/`, since they can show real people.
- keryx finds the main checkout in a submodule (and its worktrees), in a repository with a separate git dir (from its own checkout) and in a bare repository's worktrees, which keep `.keryx/` in the bare repository's folder; `finish` finds the report from any folder of the repository.
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
