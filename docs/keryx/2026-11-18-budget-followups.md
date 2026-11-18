# budget-followups: three follow-ups of the executor budget

2026-11-18 · keryx run `budget-followups`

## Proof
- Acceptance check:
  `cd skills/keryx && HOME=$(mktemp -d) python3 -m unittest discover -s tests -p test_budget_followups.py` — on main
  7be023e: 6 of 7 fail (the budget-off guard passes).
- Fresh review: `.keryx/runs/budget-followups/review/7be023e25478..6dae105b9bbd.findings.md`: P0 0 · P1 0 · P2 1 · P3 1
- QA: `.keryx/runs/budget-followups/qa/QA.md` (kept where the run ran, not committed)
- CI parity on the final head: adapter 462 OK (empty HOME), bench 124 passed / 2 skipped, field 33 passed; the owner's real limits.json unchanged.
- The review's P2 (no reservation without an estimate) fixed with a test that failed first.

## What changed
- `executors --mode "TESTS-ONLY then IMPLEMENT"` reads the first mode word.
- A metered login with no estimate and under 25 % left ranks after the other unknowns.
- Rounds that overlapped another round on the same login carry `overlap: true` and teach no estimate; every metered round reserves, even before an estimate exists.
- Subagent rounds record their cost (minutes, mode, size) when `mark` closes them.
- Merged to local main (2e0b932); nothing pushed.

## Open
- Use of the same ChatGPT account outside keryx is still invisible to the overlap mark.
- minor (deferred): `mark` on a non-subagent round before `wait` records it writes cost.json without tokens.
- Deferred: minor (deferred): mark on a non-subagent round before wait records it writes cost.json without tokens

## Rulings
- Ruling: the three follow-ups run as one run — they touch the same chooser and ledger functions, and three runs would triple the plan, review and merge overhead — skill: follow-ups start as their own run; grouped by shared code — if wrong: a larger diff to review

## Run
- 0h 13m wall clock, 1 executor rounds (0 FIX)

## Now
- Live: on local main; the budget is on for this Mac.
- Waiting on you: the release decision (1.9.0).
- Next: release on the owner's go.
