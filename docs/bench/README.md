# keryx bench

A replay benchmark: it runs a coordinator setup on tasks whose good outcome is already known, scores the
result with checks the run never sees, and compares two setups. Design: `docs/design/2026-10-24-keryx-v1-design.md` §7.

## A case

A directory, kept outside this repo (`~/.config/keryx/cases/<id>/`), because most cases come from private work:

| File | What it holds |
|---|---|
| `case.yaml` | `id`, `mode` (`bug`, `review`, `feature`), `repo`, `base` and `good` (full SHAs), `hidden.checks`, `known_defects` (review), `env`, `check_env`, `prepare`, `budget`, `tags` |
| `prompt.md` | What the owner asked — the symptom or the task, never the fix |
| `owner.yaml` | The owner's scripted answers (`autonomy`, `answers` by topic, `default`) |
| `hidden/` | Test files copied over the result only for scoring |

`env` reaches the system under test and the checks; `check_env` reaches only the checks and `prepare` in scoring trees (for example a shared build cache).

Commands run from `bench/`: `.venv/bin/python -m keryx_bench validate|run|compare|rerun|rescan`.

`validate` accepts a case only if its checks fail on `base` and pass on `good` in every one of three runs (a check that passes on base rewards doing nothing; a flaky one turns every comparison into noise). A review case needs each known defect's check to fail on base. An accepted case gets `validation.json`: which checks the base fails, tied to the case's hash.

## A run

1. **Workspace.** An empty repo that fetches only `base` and its ancestors, plus the tags reachable from it. Later commits — the good result, other branches — never exist there, the remote points nowhere, and nothing in it names the source repo.
2. **Session.** The system under test runs through the Claude Agent SDK with Claude Code's normal system prompt; the owner's user and local settings, auto memory and claude.ai connectors are off; a system may load the repo's own committed project settings. Infrastructure commands (`kubectl`, `ssh`, `gh`, `git push`, deploy CLIs) are denied; the cluster config, SSH agent and secret-looking variables are removed and git cannot use SSH keys, both in the session and in the hidden checks (which run the system's code); file edits outside the run's directory are refused. These are guard rails, not a sandbox, and they bind the coordinator's own tools only: an executor it starts (Cursor with `--force`) is outside them.
3. **Owner stand-in.** Questions (`AskUserQuestion`, or a final message that asks something) get the scripted answer a cheap model picks, or the autonomy text plus the default. Every question counts as an interruption; questions the script cannot answer are recorded. A final message without a question mark is never treated as a question (a cheap judge once called a plain report one).
4. **Background work.** A run that ends its turn while its own background job runs (a build, an executor) and does not claim to be done is kept open until the job's completion wakes it, or given up as `stalled` after an hour of silence. Processes left behind in the run's directory are stopped before scoring.
   **Scratch in /tmp.** /tmp is shared by every run and by the owner's other sessions, and two runs of one task pick the same names there (seen: both arms built into `/tmp/rc-review-target` at once). After a run, the /tmp entries it named in its tool calls (coordinator, subagents, executor) and that did not exist when it started are removed, with any process still using them (seen: Postgres servers left under `/tmp`). A run that used a /tmp entry that already existed ends `harness` and is re-run. Only one bench runner may run at a time (`~/.local/share/keryx/runner.lock`), so the two arms of a pair run one after the other, case by case.
5. **Scoring.** From a snapshot of the hidden files taken when the run started, a fresh checkout of the committed head of `bench/<run-id>` — uncommitted edits score nothing — gets `prepare`, the hidden files, then the checks; a shared build cache is used by one scoring tree at a time. Checks the base fails are **targets**, the others **gates**: quality = share of targets passed minus share of gates broken (never below 0), so an untouched branch scores 0. Review cases also count known defects fixed. Per-test counts are shown as a diagnostic. A run that claims done while a check fails is a **false done**. A run whose tool calls — the coordinator's, its subagents' (from their own transcripts, kept in `subagents/`: a background subagent's calls never reach the coordinator's stream), and the Cursor executor's from its logs — touched the source repo, the case, `~/.config/keryx`, `~/.claude/projects`, other projects under `~/.cursor/projects`, or other runs' results and workspaces is **contaminated** and scores 0 (paths written with `~`, `$HOME` or `../` included).
6. **Status.** `finished`, `stalled` (still asking after 3 replies, or silent while waiting), `timeout`, `budget`, `infra` (rate or usage limits, provider outages) and `harness` (the bench's own failure: a broken prepare, a failed judge, an isolation breach) — `infra` and `harness` are re-run, never scored — and `error`.
7. **Usage limits.** The runs share the owner's subscription. When its five-hour window rejects a run, the run waits for the reset (the SDK's `RateLimitEvent` gives the time), says "Continue where you left off." and goes on; the wait is left out of `wall_s` and of the case's timeout, and is counted in `limit_pauses` and `paused_s`. No new case starts once the seven-day window is at `--weekly-cap` (default 50 %); those cases end `infra` and `run --resume RUN_DIR` re-runs every `infra` and `harness` case of a run in place, recording the resume in `run.json`.
8. **Provenance.** `run.json` records the case hashes from the start, any case edited during the run, the bench commit and a fingerprint of the system and its skills.

## Comparing

`compare RUN_A RUN_B`: A is the current setup, B the candidate. Different case sets, edited cases, or different bench versions → invalid. `infra` and `harness` cases are left out, listed for re-run, and the verdict is marked provisional. Then, in order: B loses if any mode's mean quality drops, if it has more false dones or finds fewer known defects; B loses if it is over the cost cap; otherwise B wins if its median time is more than 5 % lower, ties within 5 %, loses if slower. Cases where quality dropped are listed for `rerun --times 3` before deciding.

`rescan RUN...`: after a fix to the leak detector, re-checks finished runs from their saved transcripts and executor logs and re-scores them from their saved checks; nothing runs again. The old values stay in each case's `rescan.json`, and two runs compare only when both were resumed and rescanned by the same bench versions. Rescan both runs of a pair, never one.

## Known limits

- About 10 cases with one run each can show large regressions, not small ones: with 3 runs per side and a "2 fewer passes" rule, an identical setup is wrongly rejected 19–59 % of the time and a real 40-point drop on one case is caught about 40 % of the time (simulation). Re-run disagreeing cases, keep most cases near 100 % pass, and grow the set.
- Passing hidden tests is not the same as mergeable work; a quality rubric is not scored yet.
- The stand-in is more cooperative than a person.
- Cost: `cost_usd` is the coordinator's client-side estimate; executor tokens come from their own logs; the judge calls of the stand-in are not counted.
- Not yet: pass^k reporting, a held-out case split, flagging edits to existing tests, public SWE-bench cases.
