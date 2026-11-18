# executor-budget: keryx picks the executor from what each plan has left and what the task will cost

2026-11-18 · keryx run `executor-budget`

## Proof
- Acceptance check:
  `cd skills/keryx && python3 -m unittest discover -s tests -p test_executor_budget.py` — on the base: 12 of 12 fail
  (no `parse_codex_meter`, `read_codex_meter`, `limit_from_meter`, `executor_left`, `executors_cell`, no `budget`
  command, no `setup --budget`, no Executors row). Live: with the budget on, `keryx.py budget` shows each Codex login's
  plan and what is left, read from its meter, and the status block has the Executors row.
- Fresh review: `.keryx/runs/executor-budget/review/cf7e1674e4f9..f995b5d9db99.findings.md`: P0 0 · P1 0 · P2 2 · P3 2
- Second finder: `.keryx/runs/executor-budget/review/cf7e1674e4f9..f995b5d9db99.security.findings.md`: P0 0 · P1 0 · P2 3 · P3 2
- QA, live on this Mac's two Codex logins (read-only, no credit spent): `keryx.py budget` shows each login's plan
  (`plus`, `team`), what is left, the reset, the learned IMPLEMENT-M estimate and the reset credits (3 each, soonest
  2026-11-30); the status block's Executors row matches the ChatGPT usage page; `executors --mode IMPLEMENT|FIX|TESTS-ONLY`
  ranked exactly as the coordinator had decided by hand (implement → subagent while codex-a "waits — p80 106% of 5h,
  left 17%"; tests-only → codex-a "fits — p80 1%"), explains every executor left out, and works outside a repository.
  A real round wrote `cost.json` (5 h +1 %, week +0 %, tokens) and a `costs.jsonl` line.
- Measured costs on a Plus login, gpt-6.2-sol high: an implement round of a medium slice 63–65 % of the 5 h window and
  9–10 % of the week; a tests-only round 1 %; fix rounds 2–15 %.
- Mutation probes: dropping the failed-read cache, counting unfinished rounds as samples — both caught.
- Tests: 454 adapter tests OK on the final head with an empty HOME; the owner's real `limits.json` unchanged across
  the run (checked before and after each suite).

## What changed
Opt-in with `keryx.py setup --budget on`; with it off every output is as before.
- **Meters** (`keryx.py budget`): per executor its plan, what is left, the reset, where the number comes from (a
  Codex login's own meter through `codex app-server`, a recorded limit, or nothing), the learned implement-M cost and
  the reset credits. The status block gains an **Executors** row: `codex-a 33% · codex-b 0% → 04:56 · cli 0% → 11-20`.
  A Codex limit is recorded with the meter's exact reset, not the message's guess.
- **Cost ledger**: each round's meter difference, tokens and minutes go to `cost.json` and the machine-wide
  `costs.jsonl`; `cost_estimate` fits a log-normal per executor, mode and size (median and 80th percentile).
- **Chooser** (`keryx.py executors --mode MODE --size S|M|L`): executors whose p80 fits both windows first, then by
  pressure (the burn rate needed to use the weekly window before its reset over the rate the login can reach), then
  the tightest fit; executors that do not fit wait in reset order; running rounds reserve their p80; a fresh meter
  clears a limit record it disproves; every executor gets a reason line.
- **Reset credits**: under the `reset-credits allow` grant, a Codex reset credit is spent only when the weekly window
  is used up, nothing fits and the credit expires within 3 days — under a lock, after a fresh re-check, never from an
  executor round; `keryx.py budget --spend-credit NAME` spends one by hand.
- Merged to local main part by part (43f519f, 753f7b8, a03049c, and this part); nothing pushed.

## Open
- No credit has been spent for real: the consume call is proven against a stand-in `codex app-server` only.
- A login's meter covers the whole ChatGPT account: other Codex use on the same account during a round counts as
  that round's cost (seen live: codex-a fell 17 % → 4 % with no keryx round running).
- Subagent rounds record no cost (they do not go through `wait`); Cursor and Mistral have no meter, so they are ranked
  "unknown" until they hit a limit.
- Not in other sessions until a release: the installed plugin is 1.7.3.

## Rulings
- Ruling (replaces the 1-day guess in codex-credits-limit): a Codex limit message is only a hint — Part 1 reads the login's meter at that moment and records the real reset (Team plans word a spent 5h window as 'workspace out of credits') — meter on codex-b: 5h 100%, rateLimitReachedType workspace_member_credits_depleted, resets in 3h30 — until Part 1 lands, a workspace message parks the account for a day
- Ruling: open-source constraint — the budget is opt-in and off by default; plans and capacities are detected or learned, never hard-coded; executors without a meter fall back to learned estimates; no owner paths, accounts or vendors baked in; a machine with only the subagent behaves exactly as today — owner 2026-11-18: 'keryx is open source … it also needs to work for everyone else' — binds every part
- Ruling: each part merges to local main once its own fresh review is fixed and checked; the final full-branch review covers all parts before the release — each part is usable alone; the owner wants the row now — if wrong: a later part reworks an earlier one's code
- Ruling: Part 2 tests-only on codex-a now (cheap); implement on the Claude subagent now — codex-a has 33% of its 5h left and the one IMPLEMENT sample's p80 is ~104%, codex-b frees at 03:56Z, both weekly windows have 68-89% left a week out (no lapse pressure), so waiting 2.5h buys nothing — the budget model applied by hand: fit fails on both codex logins now, pressure low — if wrong: Claude plan usage that Codex could have taken after 03:56Z
- Ruling: seeded the owner's cost ledger with the 5 rounds measured on codex-a today (marked seeded), so the chooser starts from real numbers — rows of measured meter deltas in this run's log — if wrong: delete the seeded lines
- Ruling: plan defect — test_executor_choice.py passed {} as environ, so test runs on this Mac read and CLEARED the owner's real limits.json (codex-b's record was deleted; restored until 03:56:13Z). Every test now gets its own KERYX_CONFIG; re-locked — executor's DONE_WITH_CONCERNS + limits.json missing codex-b — fixed in the locked test; executor FIX round re-runs
- Ruling: a credit may be spent when nothing is known to fit, even if an unmetered rung (subagent) could take the work — only credits expiring within 3 days qualify, so it is use-it-or-lose-it — security P2 #1 read as a design choice; owner: 'we want to use them up' — if wrong: a credit spent where the Claude plan would have done
- Ruling: when the meter re-read under the credit lock fails, the spend goes on with the reading already in hand — a failed read means the app-server is down and the consume call fails too — executor's note; keeps the locked test of Part 4 as written — if wrong: two sessions could spend when the re-read fails in one of them

## Run
- 2h 10m wall clock, 10 executor rounds (4 FIX): executor-budget-meters 3, executor-budget-cost 3, executor-budget-chooser 2, executor-budget-credits 2

## Now
- Live: the budget is on for this Mac; `reset-credits` granted `allow` from the owner's answer.
- Waiting on you: whether to release (push, tag, GitHub release) so other sessions get it.
- Next: the follow-ups logged in the run.
