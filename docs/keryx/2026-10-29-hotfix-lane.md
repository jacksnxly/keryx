# hotfix-lane — keryx 1.3.0: a hotfix lane with an enforced follow-up

2026-10-29 · keryx run `hotfix-lane`

## What changed
- keryx has a hotfix lane. When harm is happening now (the owner says hotfix, urgent or prod is down, calls `/keryx:hotfix`, or keryx finds live harm and the owner agrees), the session's own model fixes it at once: no plan file, no executor round, the fastest safe action first (revert, flag, rollback), otherwise the smallest change behind a regression test that fails first, one fast fresh review (`review-brief --hotfix`: the diff only, P0 and P1 only, on the strongest model), a written rollback and a production check.
- The lasting fix is enforced: a hotfix run logs `followup "<slug>-root: …"` and opens that run; `keryx.py finish` refuses until a follow-up run exists that was opened for it (its own intake, after the hotfix began), or a standing `Ruling: no follow-up — <why>` says the hotfix is the lasting fix. The report names the follow-up.
- Ordinary runs are unchanged. Branch `release/1.3.0` (committed locally, not pushed).

## Proof
- Acceptance check:
  `(cd skills/keryx && python3 -m unittest tests.test_keryx.HotfixLane)` — 8 tests. On the base (release/1.3.0 at
  788ba29) 7 fail: `--hotfix` is unknown and `skills/hotfix/SKILL.md` does not exist; `test_an_ordinary_run_needs_no_follow_up`
  passes and must keep passing. Done when all 8 pass and the whole adapter suite stays green:
  `(cd skills/keryx && python3 -m unittest discover -s tests)` (the plan said 136 + 8; the base had 139). At the head all 8 pass and the suite runs 165 tests OK.
- Fresh review: `.keryx/runs/hotfix-lane/review/83fb07aba088..628d2c5e3a96.findings.md`: P0 0 · P1 0 · P2 2 · P3 1
- Second finder: `.keryx/runs/hotfix-lane/review/83fb07aba088..628d2c5e3a96.security.findings.md`: P0 0 · P1 0 · P2 1 · P3 0
- Two more two-finder rounds on the fixes: `628d2c5e3a96..17760fe686c5` (opus P2 3; sonnet P2 1, P3 3) and `17760fe686c5..4b5e5cabc718` (opus P2 1, P3 3; sonnet P2 1, P3 2). No round found a P0 or P1. Every confirmed finding was fixed with a test that failed first; two were ruled (the lane as a field of the intake; one deferred).
- QA: `.keryx/runs/hotfix-lane/qa/QA.md` (kept where the run ran, not committed)
- Trigger eval with Claude Code's own runner (`claude plugin eval`, 7 prompts × 3 isolated runs with only the plugin loaded): the hotfix skill fired on all 9 runs of the three prompts describing harm now, and on none of the 12 runs of the four small, quick or ordinary ones.
- 18 mutation probes on the lane's rules, all caught (the survivors along the way were closed with a test each); the adapter suite runs 165 tests OK, the recorder 33 passed, the benchmark 124 passed (2 skipped).

## Open
- Not verified: a real hotfix on a real incident (none happened during the run); the trigger behaviour on models other than the eval's default.
- The follow-up gate drew findings in every review round, each on rarer log rows than the last (the last round's worst at confidence 0.4); the reviews stopped after three rounds, with every confirmed finding fixed.
- Deferred: minor (deferred): a follow-up row may name any run opened after the hotfix began, even an unrelated one; the gate does not check that the run is about this hotfix.

## Rulings
- Ruling: the coordinator writes the skill text (SKILL.md section, references/hotfix.md, skills/hotfix/SKILL.md, README, CHANGELOG); the executor writes the adapter code against locked tests — the skill text is the product and the owner's rules shape it word by word; the code is small and fully specified by its tests — if wrong: the docs get no independent author; the fresh review reads them
- Ruling: the coordinator made the tests-first commit (788ba29); round 1 is IMPLEMENT — the tests are the acceptance check and were seen failing for the stated reason on the base (7 of 8; the eighth guards ordinary runs) — if wrong: an executor would have caught a test mistake one round earlier
- Ruling: the self-reference gap is fixed inline by the coordinator, test first, outside the locked block — a one-line rule found by QA; a GLM round costs 20+ minutes; the fresh review still reads it — if wrong: no executor reads the fix before the reviewer
- Ruling: a hotfix run is marked by 'lane hotfix:' with its colon, the form the playbook prescribes, not the plan's 'lane hotfix' word match — the word match made an ordinary run whose intake mentions the lane a hotfix — if wrong: an intake that writes the lane without the colon is not treated as a hotfix (the playbook shows the colon)
- Ruling: a standing 'no follow-up' ruling waives the follow-up whatever follow-up rows exist, and one opened follow-up suffices when other rows name typos — the plan's item 4 says the ruling waives it; a mistyped row must not lock a run forever — if wrong: a ruling can waive a follow-up that was already planned; the ruling is in the report for the owner
- Ruling: evals/ (the trigger suite) and the evals/results/ ignore line are the coordinator's QA evidence, outside the executor's bounds by design — the owner asked that the lane not trigger always; the plugin eval runner is the host's own way to check it — if wrong: 98 lines of eval cases ship in the plugin folder

## Run
- 1h 09m wall clock, 1 executor rounds (0 FIX)
