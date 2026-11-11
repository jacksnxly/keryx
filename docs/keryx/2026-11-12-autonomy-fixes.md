# autonomy-fixes: the 13 field fixes after 1.6.0, in keryx.py and the skill text

2026-11-12 · keryx run `autonomy-fixes`

## Proof
- Acceptance check:
  `cd skills/keryx && python3 -m unittest discover -s tests -p 'test_field_*.py'` — on the base (8708643): 49 tests, 45 failures and 2 errors (the commands, flags and helpers do not exist); the 2 that pass are guards that must stay true (`test_a_changed_row_is_still_a_change`, `test_the_third_round_and_a_repeat_of_its_range_are_free`).
  The owner accepts by using keryx for 3 days on this Mac.
- Fresh review: `.keryx/runs/autonomy-fixes/review/87086436e321..0de35ff93f6e.findings.md`: P0 0 · P1 0 · P2 2 · P3 3
- Second finder: `.keryx/runs/autonomy-fixes/review/87086436e321..0de35ff93f6e.security.findings.md`: P0 0 · P1 1 · P2 2 · P3 2
- QA: `.keryx/runs/autonomy-fixes/qa/QA.md` (kept where the run ran, not committed)
- On the final code (89af7c1): the field tests `Ran 105 tests … OK`; the whole adapter suite `Ran 334 tests … OK` on Linux (Python 3.12, from a git archive export without `.git`, the way CI runs it) and on macOS; the field recorder 33 passed. The benchmark suite was not run: nothing under `bench/` changed.
- Two fresh reviews, two finders each. The first (on 45a4651) confirmed one P1 — `cleanup` removed a worktree parked on an unmerged commit — plus that an executor could write the grants file and that `--qa-only` and `--umbrella` skipped the review for runs that wrote code: 9 fixes, 12 tests red first. The second (on 0de35ff, counted above) confirmed no P0 or P1; its 5 confirmed findings were fixed with 8 tests red first; the security finder's P1 was graded P2 (it needs a misbehaving executor).
- Mutation probes: 16 guards broken on purpose in a scratch worktree (every `cleanup` guard, the QA gate, the hotfix shortcut, the size row, the inbox filter, the review cap, the limit check, the executor guard); 16 caught, 0 survived.
- QA on the real surface (agent exploration: the new script on this Mac's limits and on the run folders of 11 repositories, before anything was live): a round on the limited GLM plan was refused and the next rung named; `inbox --all` read every repository in 1.7 s; `cleanup --dry-run` on real finished runs listed 44 merged executor branches of 71 and kept the branches of runs in flight; `finish` on a copy of a real size S run printed FINISHED. QA found 6 defects (Q1 to Q6) and drafting this report found a seventh (it landed in a scratch worktree); each was fixed behind a test that failed first.

## What changed
On this Mac from the local merge into `main` (not pushed, not released; the version is still 1.6.0). `CHANGELOG.md` (Unreleased) has the full list; for the owner:
- **You see the plan and the place in it.** Every message ends with one table: the step the run is on, a bar with one segment per step, the plan, what is live, what waits on you, what is next. `keryx.py progress --slug <slug> --full` prints the whole plan.
- **One inbox.** `keryx.py inbox --all` lists every open question across your repositories, with its options, the recommended one first, and what it blocks.
- **Fewer "go"s.** What you granted is one file (`keryx.py grants`): sessions merge and release where you allowed it, start the follow-ups they recommended when those are off the risk and price list, and remove merged executor branches themselves (`keryx.py cleanup`).
- **Fewer lost rounds.** A round is not started on an executor that is at its limit; a provider's 429 is retried after 2 and 4 minutes.
- **`finish` fits the run.** Size S, QA-only and umbrella runs can print FINISHED; an M or L run needs its QA file; a fourth review round needs a reason.
- New commands: `grants`, `grant`, `ask`, `answer`, `inbox`, `steps`, `step`, `progress`, `repo`, `cleanup`. All code is in `skills/keryx/scripts/keryx.py`, the rules in `skills/keryx/SKILL.md` and `references/`.

## Open
- The rate-limit retry ran only in scripted tests: no real provider 429 was provoked.
- `cleanup` removed real branches and worktrees only in temporary repositories before the merge; on the owner's repositories only `--dry-run` and the no-grant path ran.
- The parallel cap ships switched off: 5 of the 9 field 429s hit while no other keryx round ran on that provider, so a cap would not have stopped them.
- Sessions that were already running keep the old skill text and now call the new script. Two things they could do before now refuse: starting a round on an executor at its limit, and a sentence typed as the log phase. An M or L run that logged its size needs a QA file, or a ruling, to print FINISHED.
- The executor guard (`KERYX_EXECUTOR=1`) stops mistakes, not a determined executor; a subagent executor and a cloud agent do not carry it.
- The manager lane was not told: this run found no command for it from this repository.
- The Mistral Vibe allowance ran out in round 09 (HTTP 402); keryx leaves that executor out until 2026-12-01.
- Deferred: minor (deferred): repository grants are keyed by the checkout's folder name, so two checkouts of the same name share them; an inbox follow-up's start/ask comes from the row's own safe/risk label
- Deferred: minor (deferred): git worktree remove deletes ignored files (build output, local env copies) with the worktree; maxParallel is checked without a lock, so two rounds started at the same moment can both pass

## Rulings
- Ruling: unknown log phases are written with a note, not refused; only a phase that is a sentence is refused — about 30 sessions run under the old skill text for the 3-day trial and must not start failing — cost if wrong: logs stay loosely spelled outside the phases the tools read
- Ruling: the QA-file gate applies to runs with a size row M or L; a run without a size row finishes as before, with a note — in-flight runs and 60 existing finish tests have no size row — cost if wrong: a new run that never logs its size dodges the gate; the note names the command
- Ruling: the lower-confidence items (a watchdog outside the session, an executor-quality record) stay out of this run — the analysis rated their evidence thin; the owner approved the 13 numbered items — cost if wrong: one more run after the trial
- Ruling: the rate retry waits 2 then 4 minutes (not 10 and 10), and no parallel cap is set in the owner's config — after 4 of the 9 field 429s the provider answered again within 11 minutes; 5 of 9 hit with no other keryx round on that provider — cost if wrong: a longer outage costs 6 minutes before the next rung; the cap stays an option
- Ruling: tests/test_keryx.py gets an isolated machine config at import (KERYX_CONFIG to a temp path), the one change to an existing test file — create now reads limits.json, so an existing dry-run test fails on any machine where glm is at its limit (this Mac, until 11-14) — cost if wrong: none for CI, which has no config
- Ruling (replaces the plan's decision 3 wording): a slice inherits the plan, locks and gate list only from a run that names it; the locked adapter test is amended (one method replaced, one line added) — the second review named real separate runs that share a prefix (register-entries-rust-fix2..7, radius-fix) — cost if wrong: a slice the plan does not name must carry its own locks, as before 1.6

## Run
- 2h 49m wall clock, 10 executor rounds (6 FIX)

## Now
- Live: the field fixes on the local `main` of this Mac, in use by every keryx session from the merge on; nothing pushed, tagged or released.
- Waiting on you: your verdict after the 3-day trial (keep, or what to steer before the release).
- Next: the release (version bump, tag, push) on your go; the two deferred minors and the watchdog outside the session as their own runs.
