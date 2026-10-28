# Execute

## Who writes the code

keryx works with Claude Code alone. Which executors a person has, and in which order, is set once with `keryx.py setup` and read with `keryx.py executors`; without a setup the ladder is the Claude subagent alone. *(owner)*

| Executor | Name | How |
|---|---|---|
| A Claude subagent | `subagent` | `keryx.py create --runner subagent` makes its worktree (`.worktrees/sub-<slug>`, branch `sub/<slug>`) and loop state and starts nothing; you dispatch the plugin's `keryx:executor` agent (Sonnet) through the Agent tool in the background with that worktree path in its brief. Its completion notice is its report; `keryx.py mark --slug S --status FINISHED|ERROR` closes the round. It runs with your session's environment and permission mode, without MCP tools, and its worktree cannot push; put `cli` or `glm` first for work that must not see your credentials. Always available. |
| Cursor CLI | `cli` | `keryx.py create --runner cli`: `.worktrees/cursor-<slug>`, branch `cursor/<slug>`; commits stay local. |
| GLM Coding Plan | `glm` | `keryx.py create --runner glm`: headless Claude Code on a GLM Coding Plan, `.worktrees/glm-<slug>`, branch `glm/<slug>`. The model is a third party's: it sees the repository, never credentials (secret variables stripped, `.env` files and key folders denied, no MCP servers). |
| Cursor Cloud Agent | `cloud` | `keryx.py create --runner cloud`: on Cursor's machines; the repository must be on GitHub. |
| You, inline | `inline` | S work, M work that is mostly judgement, and the rung after the last executor. |

The executor never dispatches its own subagents, never reviews itself in your place, never pushes. *(evidence; owner)*

### First use: setup

When nothing is set up, `keryx.py executors` says so on stderr. Then, once: run `keryx.py setup --detect`, show the owner what it found, and ask which executors to use and in which order — the cheapest available first, the subagent last. Save the answer with `keryx.py setup --executors <list>`, and `keryx.py remember` it. Never probe or guess usage limits. *(owner; evidence: a run skipped the question because nothing told it the setup was missing)*

### A usage limit

A round stopped by a usage limit ends ERROR, and `wait` prints `USAGE_LIMIT` with the reset: a time in UTC for GLM (which prints UTC+8), a span such as "4 days" for Cursor. If the reset is within about 45 minutes, wait for it and `followup` on the same slug: the round resumes its session and its uncommitted work; when `followup` finds no session (the run died before it started one), `create` on the same slug and runner again. Otherwise take the next rung (`executors --after`; `inline` means you). *(evidence: runs that resumed after a GLM reset lost ~25 minutes; GLM prints its reset time in UTC+8)*

### On any executor error, the next rung

A round that ends ERROR, EXPIRED or CANCELLED, a dispatch that fails, or a run that stalls a second time moves to `keryx.py executors --after <runner>` on the same slug: `create --slug <same> --runner <next> --prompt-file <brief>` keeps the plan, the locks, the base and the round count and starts from the last executor's commits (from GitHub's copy only: the cloud rung refuses commits that exist only here). A first stall usually left its commits: fetch, check, and follow up once on the same executor. Log the switch with its reason. *(owner; evidence: five runs re-created their slugs by hand after an executor stopped)*

## Cursor adapter

```bash
python3 "$SKILL_DIR/scripts/keryx.py" setup [--detect | --executors subagent,cli,glm]   # once per machine
python3 "$SKILL_DIR/scripts/keryx.py" executors [--after <runner>]   # the ladder, or the next rung
python3 "$SKILL_DIR/scripts/keryx.py" preflight            # every FAIL blocks; it lists the models
python3 "$SKILL_DIR/scripts/keryx.py" preflight --runner glm   # key, endpoint, and a one-line probe answered by GLM
python3 "$SKILL_DIR/scripts/keryx.py" create --slug S --prompt-file <state>/rounds-in/01.md --model <id> --ref <base sha>
python3 "$SKILL_DIR/scripts/keryx.py" wait --slug S        # run in the background; you are notified (not for subagents)
python3 "$SKILL_DIR/scripts/keryx.py" mark --slug S --status ERROR   # a subagent round that failed
python3 "$SKILL_DIR/scripts/keryx.py" fetch --slug S       # its head into refs/keryx/S
python3 "$SKILL_DIR/scripts/keryx.py" locked --slug S [--ref R]   # every locked block must be ok
python3 "$SKILL_DIR/scripts/keryx.py" gates --slug S [--ref R]    # architecture gates the diff changed
python3 "$SKILL_DIR/scripts/keryx.py" followup --slug S --prompt-file <state>/rounds-in/02.md
python3 "$SKILL_DIR/scripts/keryx.py" scrub --slug S       # strip the attribution trailer before anything leaves
python3 "$SKILL_DIR/scripts/keryx.py" review-brief --slug S [--risk]   # the fresh reviewer's brief and how to dispatch it
python3 "$SKILL_DIR/scripts/keryx.py" report --slug S                  # draft docs/keryx/<date>-S.md for the owner to read
python3 "$SKILL_DIR/scripts/keryx.py" finish --slug S [--head R] [--findings-only]   # FINISHED, or what the run still lacks
```

For Cursor, pick the cheapest model preflight lists that has done this kind of work. For GLM, `create --runner glm` with no `--model` runs glm-5.3; every other command takes only `--slug`, since the loop remembers its runner. Never poll in short loops; while it runs, prepare the QA script and the review package. *(owner; fact)*

## The brief

A worker cannot ask you anything mid-run, so a brief with a missing field is not sent. *(evidence)*

```markdown
Mode: TESTS-ONLY | IMPLEMENT | FIX
Goal: <one sentence>
The plan: <PLAN.md pasted in full>
Rules: work only in this worktree; do not push; do not edit the locked tests or any architecture gate (guard tests, import contracts, dependency rules, lint and CI config) unless the plan says so; use the plan's terms for new
names and keep domain code free of framework, database and provider imports; no co-author or
"generated with" trailers; do not start subagents; run the commands below and paste their real output;
start no long-lived process (dev server, watcher): a check that needs a server runs through a test runner that
starts and stops it, and anything you did start is stopped before your final report.
TESTS-ONLY: add the locked tests exactly as written, run them, commit as `test: …`; write no fix.
IMPLEMENT: make the locked tests and the done-when commands pass; commit as `fix: …` / `feat: …`.
FIX: the findings below, verbatim; every rule above still holds.
Report (your last message): first line `Status: DONE | DONE_WITH_CONCERNS | NEEDS_CONTEXT | BLOCKED`,
then the commands you ran with their output, then the files you changed.
```

Exact values (numbers, strings, signatures) appear once, in the plan. A follow-up repeats every rule still in force: follow-ups silently drop the ones they leave out. *(evidence)*

## Order

1. **Tests first.** Run 1 is TESTS-ONLY. Then `fetch`, `locked`, and read the failing output yourself: each test must fail on the base for the reason the plan states. A test that passes, or fails on a typo or a missing fixture, is a plan defect: fix the plan, log the ruling, run 1 again. *(evidence)*
2. **Implement** as a follow-up on the same agent: it keeps its context and its build cache. A Claude subagent gets TESTS-ONLY and IMPLEMENT in one brief, as two commits; check red at the test commit. Its next round (a FIX) is `followup`, after `mark` closed the last one: dispatch a fresh `keryx:executor` with the new brief in the same worktree. *(evidence)*
3. **Status.** DONE → check. DONE_WITH_CONCERNS → read the concerns first. NEEDS_CONTEXT → supply it in a follow-up. BLOCKED → more context, a stronger executor, a smaller slice, or a corrected plan; never the same request unchanged. *(borrowed)* A run that errors or times out is not a report: read its events and retry once as fits the cause. Never set `wait --timeout` below its default for an IMPLEMENT or FIX round: a long run is not a stalled one, and silence and stuck tool calls have their own clocks. *(evidence: a 90-minute cap stopped a GLM round mid-implementation with nothing committed)* `wait` bounds every run with three clocks: 10 silent minutes with nothing in flight, 60 minutes for one tool call, and `--timeout` for the whole run; past any of them it saves what was running (`processes.txt`, credentials masked), stops the run with everything it started, and returns `STALLED` (exit 4) or a timeout (exit 3). A run that reported its result but did not exit is stopped after a minute and counts as finished. Seen: two executors finished, left dev servers running and never reported, because the CLI waits on everything a run leaves behind. A stalled run's commits are usually all there: `fetch`, check, and follow up only for what is missing. Live QA on a running server is the coordinator's job, not the executor's. *(evidence)*

## Escalation

Two failed fix rounds on the same finding move it one rung up the ladder (`create --slug <same> --runner <next> --escalate --prompt-file <brief>`); past the last executor, to you. Log each step with its reason. Code you write yourself still gets the fresh review. *(owner)*

Before a third attempt on one problem, write down the premise the failed attempts share and test it directly. *(evidence)*

## Parallel slices (L)

Up to 3 at once, never two on the same file, spread across the configured executors when there are several. Merge each finished slice into your integration branch before the next depends on it. *(owner)*
