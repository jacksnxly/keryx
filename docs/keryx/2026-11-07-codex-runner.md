# codex-runner: a provider declared in config.json runs as a keryx executor through `codex exec`

2026-11-07 · keryx run `codex-runner`

## Proof
- Acceptance check:
  `python3 skills/keryx/scripts/keryx.py preflight --runner mistral-vibe` with `~/.config/keryx/config.json` declaring the
  `mistral-vibe` provider passes. A real round, `create --runner mistral-vibe` in a scratch repository, then `wait`, leaves
  a commit on branch `mistral-vibe/<slug>`, and the Vibe Code meter on Mistral's console moves.
  On the base: `keryx.py preflight: error: argument --runner: invalid choice: 'mistral-vibe' (choose from cli, cloud, glm, subagent)`.
- Fresh review: two finders (general, security) on 149ef0a..e9fbbf7 and again on e9fbbf7..ab76ae1; confirmed findings fixed test-first in rounds 03 and 04 (limit text of a failed turn, Codex's `last status: 429` wording, codex-only limit patterns, GitHub/git credentials, askpass, a cancelled round's report, `--env` guards); the rest deferred below.
- QA: live rounds on GLM 5.3 through Mistral in a scratch repository (`.keryx/runs/codex-runner/qa/`): a round committed a failing test and the fix; the key never reached the executor's shell or any run file; pushes go nowhere; a bad key ends ERROR without a limit; preflight's probe answers KERYX_OK; `gh` sees only a placeholder token and `git` over HTTPS cannot authenticate.
- Mutation probe: an OpenAI key let into the Codex environment fails the locked env test. Adapter suite 229 OK, field 33, bench 124.

## What changed
A provider declared in `~/.config/keryx/config.json` under `providers` (`"runner": "codex"`, `baseUrl`, `keyFile`, `model`, `effort`, `codexConfig`) is an executor like `glm` or `cli`: it can sit in the ladder and the reset order, `create --runner <name>` runs it through `codex exec`, and its usage limits (HTTP 402 until the 1st, 429 for ten minutes) move work to the next rung. The owner's first provider is `mistral-vibe`: GLM 5.3 on Mistral's API with the Vibe Code key, which draws on the plan's Vibe Code allowance. Branch `cursor/codex-runner`.

## Open
- A provider round runs with full access: it can read the provider's key file, the run records and, if determined, the owner's SSH keys and keychain; the guards stop mistakes only (documented in execute.md).
- The Vibe Code meter for these rounds is the owner's to read.
- Deferred: minor (deferred): _toml does not escape control characters in config values
- Deferred: minor (deferred): no test drives a codex round through cli_launch/wait (covered by live QA rounds qa1-qa4)

## Rulings
- Ruling: Codex executors run danger-full-access — workspace-write cannot commit in a linked worktree even with .git writable — probe 2026-11-07: writes under .git refused; Morndo's engine layer made the same call; guard rails: scrubbed env, own CODEX_HOME, no pushes, shell env excludes the key — cost if wrong: a third-party model can read files outside the worktree as the cli and glm runners already can
- Ruling: FIX round 02 on cli (Cursor), not glm (limit until 03:42Z) or subagent (owner directive via a peer session 2026-11-07: code execution on Cursor and GLM, Claude for coordination and review) — executors --after glm = cli — switch
- Ruling: the provider key file and process env stay readable under full access (accepted, documented), like the glm runner's key — full access is required to commit (row 3) — accepted
- Ruling: lock 01's NO_PUSH_ENV equality amended to read the push block as git config pairs — it contradicted lock 03 (credential.helper as a second pair) — plan defect: two locks could not both pass; NO_PUSH_ENV for cli/glm stays unchanged as the brief said — lock amended
- Ruling (replaces nothing; second amendment of lock 01): GH_TOKEN left the gone-list — lock 04 sets a placeholder; lock 01 now asserts the real token never passes — plan defect: locks 01 and 04 contradicted on GH_TOKEN — lock amended
- Ruling: no third fresh review — each fix since the reviewed head ab76ae1 answers that review's findings with a test that failed first and a live QA; the owner asked to keep Claude use low today — finish counts the ab76ae1 review (earlier on the line); cost of another two-finder pass vs small test-first fixes — cost if wrong: a defect in round 04's 3 small changes ships unreviewed

## Run
- 4h 09m wall clock, 4 executor rounds (3 FIX)

## Now
- Live: keryx 1.6.0 on main; `mistral-vibe` in the owner's executor ladder.
- Waiting on you: nothing for keryx.
- Next: the deferred items, when a provider round shows them in the field.
