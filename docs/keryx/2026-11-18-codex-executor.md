# codex-executor: a Codex provider that runs on a ChatGPT login (one rung per account)

2026-11-18 · keryx run `codex-executor`

## Proof
- Acceptance check:
  `cd skills/keryx && python3 -m unittest tests.test_codex_login` — on the base: `FAILED (failures=2, errors=8)` of 14
  (no `codexHome` provider, no `codex_login_home`/`write_login_home`/`LOGIN_HOME_MARK`, `codex_env` takes no `gh_dir`,
  no ChatGPT limit wording). Live: `keryx.py preflight --runner codex-a` answers KERYX_OK through the owner's ChatGPT login.
- Fresh review: `.keryx/runs/codex-executor/review/2ac58ac116da..0a8ec5c18db2.findings.md`: P0 0 · P1 0 · P2 2 · P3 1
- Second finder: `.keryx/runs/codex-executor/review/2ac58ac116da..0a8ec5c18db2.security.findings.md`: P0 0 · P1 0 · P2 1 · P3 3
- QA, live: `preflight --runner codex-a` answered `KERYX_OK` on gpt-6.2-sol through the owner's ChatGPT login
  (Codex wrote `auth.json`, mode 600, into the keryx-owned home). A real `create`/`wait` round in a throwaway repository
  wrote `hello.txt`, committed `chore: add hello` on `codex-a/live1` and finished in 15 s.
- QA, stand-in `codex` through the real `preflight`/`create`/`wait`/`executors` path, before and after the fix round:
  a normal round (no `OPENAI_*` or key variable reaches `codex exec`); a usage-limit round (`plan limit; resets at
  2026-11-20T14:45:00Z`, codex-a left out of the ladder until then); no login (stops before a worktree exists and
  prints the login command).
- Mutation probes: dropping the foreign-config refusal and counting the ChatGPT message for non-codex rounds were both
  caught by the locked tests.
- Tests: 384 adapter tests OK on b298f67 (base 362); bench 124 passed, 2 skipped; field 33 passed.

## What changed
- A Codex provider can now run on a ChatGPT login instead of an API key: in `~/.config/keryx/config.json`,
  `"providers": {"codex-a": {"runner": "codex", "codexHome": "~/.config/keryx/codex/a", "model": "gpt-6.2-sol",
  "effort": "high"}}`, after `CODEX_HOME=~/.config/keryx/codex/a codex login` once. One provider per account; two
  accounts are two rungs, and the ladder moves to the next when one hits its limit.
- keryx owns that home's `config.toml` (approvals off, file login store, plugins/apps/memories off, `CODEX_HOME` kept
  out of the executor's shells) and refuses `~/.codex`, a `config.toml` it did not write, and a non-empty folder
  without one. Only `Logged in using ChatGPT` counts as a login.
- The ChatGPT plan's "You’ve hit your usage limit … try again at …" is read as a usage limit, its local reset time
  taken on the day the round wrote it; "try again later" counts as 5 hours.
- Model choice: gpt-6.2-sol scores 60.6 % on Terminal-Bench 4.0 (Vals AI) beside Sonnet 5.5's 64.1 % and GLM 5.3's
  38.9 %, at an estimated 17–180 Plus messages per 5 hours (OpenAI's pricing page), about 3× gpt-6.2-astra.
- Commits b67d693, 0a8ec5c, bcb0573, b298f67 on `sub/codex-executor`, merged to local main; nothing pushed.

## Open
- The second account (codex-b) is not logged in yet, and whether to rotate two accounts is the owner's call: OpenAI's
  Terms forbid conduct that would "circumvent any rate limits or restrictions"; no clause names separately paid Plus
  accounts.
- A real usage-limit message from the ChatGPT backend has not been seen; the wording comes from codex-rs 0.169.0
  `protocol/src/error.rs`.
- codex-a has no reset date in the ladder: the owner's weekly reset is not known to keryx.
- Deferred: minor (deferred): injected limit wording in an ERROR round's report can skip the account 5h; same trust model as every runner's result.md
- Deferred: minor (deferred): parents created by write_login_home are not 0o700 (only the home itself)

## Rulings
- Ruling: model gpt-6.2-sol at effort high — near Sonnet 5.5 on TB4, well above GLM 5.3, ~3x the Plus capacity of 6.2-astra; owner wants the spare allowance used, so high over medium — owner: 'as strong as glm or sonnet', 'i want to use it' — if wrong: change model/effort in config.json, no code change
- Ruling: two accounts = two providers (codex-a, codex-b), each with its own codexHome login; the ladder's limit record + reset order rotates them (drain the one that resets first, skip one at its limit) instead of a per-round round robin — reuses the tested ladder/limits machinery; per-round alternation would split sessions across homes and waste the reset that comes first — if wrong: a strict alternation can be added later on top of two rungs
- Ruling: keryx owns <codexHome>/config.toml (marked first line) and refuses a config.toml it did not write, so ~/.codex is never touched; apps/plugins/memories off as in research runs — research memo: the owner's Codex loads a production connector unless plugins/apps are off — if wrong: the owner points codexHome at a fresh folder
- Ruling: the run's ChatGPT limit message without a time counts as 5 hours — Codex prints 'try again later.' when the backend gives no reset; 5h is the short window — if wrong: a rung is skipped too long or retried too early
- Ruling: no second review round — the fix diff is small, each finding has a locked test, and I read it line by line — skill: fixes after review are checked mechanically — if wrong: a regression in the five fixed paths that the 8 tests miss

## Run
- 0h 36m wall clock, 2 executor rounds (1 FIX)

## Now
- Live: codex-a is on this Mac's ladder.
- Waiting on you: the codex-b login and the two-account decision.
- Next: add codex-b once both are answered.
