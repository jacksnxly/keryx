# research-agent: an optional research agent (Codex) that keryx hands research to; none by default

2026-11-12 · keryx run `research-agent`

## Proof
- Acceptance check: `cd skills/keryx && python3 -m unittest tests.test_research_agent` — 9 locked tests, FAILED (failures=1, errors=8) on the base `f3b7320`, OK on `d0951f4`. Live: `keryx.py research --slug research-agent "…"` through the owner's ChatGPT-plan Codex answered with sources in 24 s (pytest 9.1.1 pinned, 9.2.0 latest on PyPI).
- Fresh review: one round, a full review and a security pass on `f3b7320..dc90364`. One P1 (overlapping calls overwrote each other's `NN.md`; a two-process replay now gives `01` and `02`), one P2 (answers unmasked) and two P3 (timeout under one second, the same overlap) were fixed in `d0951f4`; prompt injection is mitigated in the prompt; two minors are deferred (below).
- QA: `.keryx/runs/research-agent/qa/QA.md` (kept where the run ran, not committed)
- Mutation probes: 4; the two that survived the locked tests (stdin inherited, a finished run with no answer) are caught by `tests/test_research_edges.py`.
- CI parity (`keryx.py repo`) on the branch: adapter 362 OK, bench 124 passed (2 live-only skipped), field 33 passed.

## What changed
- `keryx.py setup --research codex` saves `"research": {"agent": "codex"}` in `~/.config/keryx/config.json`; `--research none` removes it. Nothing is set by default, so nobody else's sessions change.
- `keryx.py research [--slug S] "<question>"` runs `codex exec` read-only with live web search and the owner's own Codex login, without the owner's Codex config, plugins, apps and memories. It prints the answer with its sources (credentials masked), saves `<state>/research/NN.md` and logs a `ground-truth` row. Exit 3: none set; exit 1: the run failed — the session researches itself.
- The skill's ground-truth step and `references/intake.md` hand outside research to it; README and CHANGELOG describe it.
- Branch `cursor/research-agent`: `b4dc2bb` tests, `0404a05` feature, `56134b4` and `d0951f4` fixes, `dc90364` docs.

## Open
- Only Codex 0.163.0 was run live; a later Codex that drops one of the four `--disable` feature names may refuse the command, which then fails with exit 1 and the session researches itself.
- Deferred: minor (deferred): Codex project rules/config can still shape a research run (--ignore-rules not passed); read-only sandbox bounds it
- Deferred: minor (deferred): the research run gets the full environment — ruled: the owner's own Codex login decides the account

## Rulings
- Ruling: research config is an object {agent, model?, effort?}, not a bare string — one shape to validate; costs a hand edit if the owner wanted the shorthand — room for model/effort without a second form — standing
- Ruling: the research run ignores the owner's Codex user config, plugins, apps and memories — production connectors (Registercheck) stay out of an autonomous agent's reach; costs the owner's default model choice, which research.model restores — least privilege for read-only research — standing
- Ruling: drop _shield_research_question — it turns options written after the question into an argparse error; a question starting with - uses -- as any CLI — less magic, keeps argparse's normal option order — standing
- Ruling: a failed research run also writes NN.md (question + failure) so its log evidence exists and the number advances — the failed row named a file that was never written — standing

## Run
- 1h 14m wall clock, 2 executor rounds (0 FIX)

## Now
- Live: nothing
- Waiting on you: push and release (repository rule: never without the owner's go)
- Next: merged to local `main` (live on this Mac) with research set to codex on the owner's machine
