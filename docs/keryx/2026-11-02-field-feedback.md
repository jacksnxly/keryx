# field-feedback — keryx 1.4.0: proof first, never idle, back to the preferred executor, UI against its master, prices on their own

2026-11-02 · keryx run `field-feedback`

## Proof
- Acceptance check: the locked tests `ReportLeadsWithProof` (2), `UsageLimitsAreRememberedAcrossSessions` (4) and, after the review, `LimitsNeverBreakARun` (3) in `skills/keryx/tests/test_keryx.py`. On the base (0c2c6c1) the first six failed: the draft put Proof after What changed (`167 not less than 48`), had no `## Now` (`substring not found`), and `record_limit` / `limited_runners` did not exist; the three later ones failed at c99a170 for the reasons the review named (`import of fcntl halted`, `FileExistsError` out of `status`, a live limit erased: `{}`). All 9 pass at the head.
- Fresh review of the whole branch: `.keryx/runs/field-feedback/review/dbc0f8b34ffa..cc201267e3a5.findings.md`: P0 0 · P1 0 · P2 1 · P3 2 — the P2 and one P3 fixed with a failing test each, one P3 deferred.
- Re-review of the fixes: `.keryx/runs/field-feedback/review/cc201267e3a5..414059d4fed7.findings.md`: P0 0 · P1 0 · P2 1 · P3 1 — the P2 is the stale-record rule (a ruling), its early-lift consequence now documented; the P3 is the deferred minor.
- QA (`.keryx/runs/field-feedback/qa/QA.md`, kept where the run ran): a real GLM round at GLM's real weekly limit was stopped, recorded, and left out of `keryx.py executors` until 2026-11-04T03:24:16Z, with `--after cli` giving the subagent; the report draft of a real finished run opens with Proof and closes with Now.
- Mutation probes: 7 on the first round and 5 on the fixes, all caught.
- Suites at the head: adapter 174 tests OK on this Mac (Python 3.14) and in Linux python:3.12-slim with git and procps, as CI's runner has them (the base ran 171; +3 from the fix round); benchmark 123 passed, 3 skipped (Linux 3.12); field recorder 33 passed.

## What changed
- Reports lead with their proof and close with **Live / Waiting on you / Next**: `keryx.py report` drafts Proof first and a last `## Now` section that `finish` waits for; every message that ends a turn follows the same shape (SKILL.md §4, finish.md).
- keryx never ends a turn idle while work is in flight: a background watch wakes it, and a `waiting` row in the run log says what it waits on and until when; under granted autonomy a report is not a stopping point (SKILL.md §4).
- A usage limit is remembered for every session on the machine (`limits.json` beside the config): `keryx.py executors` leaves that runner out, says until when, and lists it first again after the reset; recording never breaks a command, keryx still loads without `fcntl` (Windows), and a stale limit never erases a live one (execute.md).
- UI work against a design master is accepted screen by screen, master and build side by side; without a master, 2–3 directions as screenshots first (intake.md, check.md).
- A price, credit cost or billing rule is asked on its own with a worked customer example, even when the owner delegated everything else (SKILL.md §3).
- Branch `release/1.4.0`, merged into main and pushed; version 1.4.0, CHANGELOG entry.

## Open
- Not verified: the skill-text rules in a live run of another session (idle waits, UI parity, prices) — they take effect from the next run; a limit file written by two sessions at the same moment (the lock path has no test).
- Deferred: minor (deferred): keryx's credential check flags a run of 32+ letters, so a long test class name (`UsageLimitsAreRememberedAcrossSessions`) kept the acceptance check and one row out of this draft.
- Deferred: minor (deferred): a resetsAt not in the strict UTC format is recorded and then ignored by every reader

## Rulings
- Ruling: row 3 is withdrawn — the overview becomes its own run, runs-overview, local only — owner 2026-11-02 — withdrawn
- Ruling: this run ships only the fixes — report proof-first + Live/Waiting on you/Next block, never idle while waiting (a 'waiting' log row), back to the preferred executor once its usage limit resets, UI screenshot parity, pricing asked separately; merged to main and pushed — owner 2026-11-02: 'i would only approve the fixes to go live' — scope: fixes only
- Ruling: the executor for this run is the Cursor CLI (grok-4.7-xhigh), not GLM — GLM preflight: weekly limit until 2026-11-04 03:24Z (printed 11:24 UTC+8); the ladder is glm, cli, subagent — cli
- Ruling: the locked step in test_the_executors_command_… that recorded a 2000-01-01 limit over glm's 2099 one to simulate a passed reset now moves glm's recorded until into the past in limits.json — it encoded a test shortcut, not a design, and contradicts finding 3 (a stale limit never erases a live one) — the executor reported BLOCKED: the brief claimed the earlier locks were compatible; they were not — the coordinator's plan defect — lock changed

## Run
- 0h 59m wall clock, 3 executor rounds (2 FIX)

## Now
- Live: keryx 1.4.0 on main, in every session on this Mac; pushed to GitHub
- Waiting on you: nothing for this run (a tag or GitHub release only on your go)
- Next: the next keryx runs use it; the local overview (run runs-overview) waits for the owner's verdict
