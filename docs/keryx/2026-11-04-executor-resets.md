# executor-resets: an opt-in executor order that uses up first the plan that resets soonest

2026-11-04 · keryx run `executor-resets`

## Proof
- Acceptance check:
  `cd skills/keryx && python3 -m unittest tests.test_executor_resets` — on the base (0371401): `FAILED (failures=2, errors=9)` of 12
  (no `next_reset`, no `ordered_ladder`, no `setup --order/--reset`); the one passing test guards that the mode is off by default.
  Live: with the owner's config set to `"order": "resets"` and Cursor resetting 2026-11-06 (monthly), GLM 2026-11-11T03:24:16Z
  (weekly), `keryx.py executors` prints `cli` first today; on the base it prints `glm` first.
- Fresh review: `.keryx/runs/executor-resets/review/57f7f8982316..20254dac1229.findings.md`: P0 0 · P1 0 · P2 0 · P3 2
- Second finder: `.keryx/runs/executor-resets/review/57f7f8982316..20254dac1229.security.findings.md`: P0 0 · P1 0 · P2 1 · P3 2
- Now: the acceptance check passes 12/12; with the review tests (locks 02–04) 22 reset tests, and the full adapter suite 196 tests OK on Python 3.14 and on 3.12 (CI's version), on the shipped head 20254da.
- QA on a copy of the owner's real `config.json` (`.keryx/runs/executor-resets/qa.sh`): off → glm, cli, subagent as before; on with the owner's dates → cli, glm, subagent, and stderr `order: resets, soonest first: cli resets 2026-11-06T00:00:00Z, glm resets 2026-11-11T03:24:16Z, subagent no reset`; Cursor at its limit → glm first; `--after cli` → glm; a new ladder keeps the mode; `--order ladder` keeps the dates; a bad value is refused and the file is unchanged; a hand-broken order names the file.
- Mutation probes: 14 of 14 caught (ladder mode sorting, month-end clamp, a saved date counted back, other keys dropped, tie order, a reset at this second, a limited runner kept, setup on a new machine, the mode off refusing dates, the broken file lost or moved early, a refused setup writing, setup checking less than keryx reads). A first pass misread two because Python reused stale bytecode for same-size edits; rerun with `-B`.
- Reviews (risk: Opus + security pass each, each finding checked against the code first): 0371401..6906ba8 Opus P2 1 (setup on a new machine saved a ladder nobody chose), security P3 2 → fixed; 6906ba8..57f7f89 Opus P3 2 and a recovery trap (the off switch refused while a bad date stopped the reset order), security P2 1 · P3 2 → fixed or ruled; 57f7f89..20254da as above: nothing blocking.

## What changed
- `keryx.py executors` can now order your executors by when their plans reset: with `"order": "resets"` in `~/.config/keryx/config.json` it lists first the one whose quota lapses soonest (Cursor before GLM until 2026-11-06, then GLM, Cursor again in the last days before its next reset). Executors without a date follow in your saved order; one at its usage limit is still skipped. Off by default.
- Turn it on: `keryx.py setup --order resets --reset cli=2026-11-06/month --reset glm=2026-11-11T03:24:16Z/week`; off: `--order ladder` (the dates stay). keryx rolls each date forward by its period and never asks a provider for usage.
- `setup` keeps every other key in the file, saves only what keryx can read back, refuses an order or a date on a machine with no ladder yet, and keeps a config that is not valid JSON as `config.json.broken` when a new ladder replaces it.
- Where: `skills/keryx/scripts/keryx.py`, four test files `skills/keryx/tests/test_executor_resets*.py`, README, `references/execute.md`, SKILL.md step 4; merged into main as 5d2ce45; released as 1.5.0.

## Open
- Not verified live: a real executor round chosen by the reset order; the next keryx round on this Mac is the first.
- Deferred: minor (deferred): bench test_the_repo_names_no_external_skill_pack scans ignored run state too; locally it flags the Cursor executor's chat store under .keryx/runs/executor-resets/cursor-config (never committed); tracked files and this branch have no hit; CI has no .keryx
- Deferred: minor (deferred): --after re-derives the reset order on each call, so a reset passing during a round can skip one rung (e.g. 11-06 00:30Z: --after cli -> subagent); a lifted limit already does the same in ladder mode
- Deferred: minor (deferred): an unreadable config.json (OSError) gives a traceback in setup, as load_config already does in 1.4.0
- Deferred: minor (deferred): a hand-written non-object resets with order ladder makes every setup write refuse, and --reset cannot repair it; only a hand edit does
- Deferred: minor (deferred): with the mode off, one bad reset entry makes setup's print show no reset lines and say nothing about the bad one
- Deferred: minor (deferred): config.json.broken — a second broken config replaces the first kept copy; the rename comes before the write with no rollback (a failed write leaves only .broken); a symlinked config becomes a regular file. Security delta review graded the first P2; each needs a config broken twice, a failed disk write, or a symlink

## Rulings
- Ruling: autonomy = up to the release (merge to main, push, tag, GitHub release) — the owner asked for the release in the request — the owner said 'implement this and release it as release and new feature' — release on green CI
- Ruling: executor cli (Cursor CLI, grok-4.7-xhigh), not glm first — Cursor's quota lapses on 11-06, GLM's on 11-11: the rule this run builds — keryx.py executors still lists glm first (the bug); preflight cli all ok — dispatch cli
- Ruling: the coordinator fixed it inline behind lock 02 (88e1ae4 test failed for the stated reason, aabc15f fix) — keryx size S for a 3-line change; a FIX round costs ~25 min — one branch of next_reset; test first — fixed inline
- Ruling (replaces the plan's review focus 'invalid JSON when setup runs: must refuse, never overwrite'): setup --executors replaces a config.json that is not valid JSON, as 1.4.0 did; order or reset alone still refuses it — security delta review P2 is this choice — it is the only setup repair path for a file keryx cannot read; cost if wrong: hand-written keys in an already broken file are lost — kept
- Ruling (replaces row 24): the coordinator fixed the review findings inline behind lock 04 (renewed) — a new file needs --executors; a non-JSON file is replaced by a new ladder and kept as config.json.broken; setup saves any result load_config can read, so bad dates are ignored while the order is ladder, refused when turning it on, and the off switch always works — small, test-first changes (c53e1f9, f2d46de, 784c7a2 each failed for the stated reason); an off switch refused when needed is worse than an ignored bad date — lock renewed

## Run
- About 1 h 40 min wall clock (18:06–19:45 UTC), 1 executor round (Cursor CLI), review fixes by the coordinator, 3 review rounds (risk: Opus + security pass each)

## Now
- Live: keryx 1.5.0 is released (GitHub release keryx 1.5.0, tag v1.5.0 on 35125be, CI green; 1.4.0 tagged and released on 0371401) and installed on this Mac; the owner's config has the reset order on, and `keryx.py executors` lists cli, glm, subagent.
- Waiting on you: nothing. Sessions already open keep 1.4.0 until they restart; their `keryx.py executors` ignores the new keys, and a 1.4.0 `setup --executors` would drop the reset order.
- Next: the next keryx round takes Cursor; GLM leads from 2026-11-06 when Cursor's month restarts.
