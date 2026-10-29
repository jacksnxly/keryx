---
name: keryx
description: Use for any code change worth more than a one-line edit — fixing a bug or a red CI job, building a feature from a spec, or reviewing and fixing a PR or branch. One loop for all three: agree what "done" looks like and prove it fails now, change the code (yourself or a cheaper executor), check it mechanically, QA it on the real surface, get one fresh review, and finish within the autonomy the owner gave.
---

# keryx

**Done means the acceptance check passes, and that check failed before the work started.** Reports — the executor's, a reviewer's, your own — are claims until you have seen the check pass. *(owner; evidence: a parity gate reported 0 failures while 9 of 49 screens matched)*

Origin tags: *fact* cannot be otherwise · *owner* the owner's rule · *evidence* seen in our own logs · *borrowed* a tactic not yet proven here.

## 1. Size the work first

| Size | When | What runs |
|---|---|---|
| **S** | One obvious place, a few dozen lines, nothing on the risk list | You do it inline: check fails → failing test → fix → check passes → repo gate → one mutation probe → finish. No plan file, no executor, no reviewer. |
| **M** | Several files, or anything on the risk list | Plan with locked tests → executor (tests first, then code) → mechanical check → QA with probes → one fresh review → finish. |
| **L** | More than a day, or parts that can move independently | Split into M slices with file ownership; up to 3 run in parallel; one fresh full-branch review before merge. |

Risk list: money, auth, privacy, migrations, concurrency, data deletion, public contracts. *(owner)*
Size by the work, not the wording; when an S grows, stop and re-size. *(evidence: per-task plans and reviews cost ~0.85× the implementation; a subagent-per-task turn used ~4 M fresh tokens in the field log)*

## 2. The loop

1. **Intake** — `references/intake.md`. Read what you can yourself, then ask only what you can't find: one question at a time, choices where possible. Ask the autonomy question once. Turn "who accepts this and what do they look at" into a check, run it on the base, and see it fail. *(owner)*
2. **Ground truth** — facts with their source, assumptions with the cheapest test that would disprove each; test the riskiest one with a real call before building on it. *(evidence)* When the change touches a business rule, owned data or an integration, the domain facts too: context, terms, invariants, who owns the data, which way imports go — `references/domain.md`. *(owner)*
3. **Plan** (M/L) — `references/plan.md`. Decisions (with the Domain block where `domain.md` applies) and locked tests, never implementation code. Run every done-command once on the base before anyone builds. *(owner; evidence)*
4. **Execute** — `references/execute.md`. The executors set up once with `keryx.py setup` (the Claude subagent when there is no setup), the next one on any error. Tests first, proven to fail for the stated reason; then the code. Escalate after 2 failed rounds on the same finding. *(evidence; owner)*
5. **Check** — `references/check.md`. Mechanical first: locked tests unchanged, diff inside bounds, tests re-run by you, no assistant attribution. Then QA on the real surface, scripted and exploratory, and at least one mutation probe. *(evidence: a lock check caught a false "copied verbatim"; probes found weak tests twice)*
6. **Fresh review** (M/L) — `references/review.md`. `keryx.py review-brief` writes the reviewer's brief (two for a risk-list diff); dispatch it exactly as printed, never a prompt of your own. One reviewer with fresh context on the whole branch; validate each finding before acting on it. *(owner; evidence: converged branches still had 3–12 real bugs; a reviewer briefed from memory lost the reach question and the grades)*
7. **Finish** — `references/finish.md`. Act within the autonomy, log a finish row, and run `keryx.py finish`: an M or L run is finished only when it prints FINISHED. Then a short report with links to evidence. *(owner; evidence: three field runs in a row ended without a finish row)*

Modes add their own steps: **bug** and **CI** `references/bug.md` · **feature** `references/intake.md` · **review a PR/branch** `references/review.md`.

## 3. Rulings, not stalls

Between intake and the autonomy limit, never wait on the owner. Decide conflicts and gaps yourself with the request as the authority and log each as a ruling: what you decided, why, what it costs if wrong. *(owner; evidence: ~47 h of a 12-day run was idle at gates the owner would have waved through)*

Stop and ask only for: an irreversible or destructive step; a security-sensitive action; a step beyond the autonomy answer; a plan so broken that every way forward is a guess; a gate the repository or the owner's standing grants put on a human. Those rules outrank this skill. *(owner)*

**Scope:** work that grows beyond the accepted task becomes a new task with its own intake; it never rides along. *(evidence: a billing reform ran inside "parity" for ~5 days)*

## 4. Spend little, move fast

- The cheapest model that can do a step does it: executors write code, Sonnet reviews ordinary diffs, the strongest model only for risk-list reviews and judgement. *(owner)*
- Subagents only as the executor, for the fresh review and for parallel slices; never a reviewer per task. Never chain review skills into each other. *(evidence: chained review skills cost ~$25 per review case in the benchmark)*
- Read what you need, not whole trees; send long command output to a file and read its tail. *(evidence)*
- Start slow things (builds, installs, executor runs) in the background and keep working. *(fact)*
- Reports are a few lines with paths to evidence files. Before a wait of more than a few minutes, tell the owner what is running, since when, and when you expect it back. *(owner; evidence: "are we done yet or what are we waiting for?")*

## 5. Run log

M and L runs keep one log, written as you go, one row per decision: `python3 "$SKILL_DIR/scripts/keryx.py" log --slug <slug> <phase> <decision> <why> <evidence> <result>` — five quoted arguments; it prints the log's path (`.keryx/runs/<slug>/decisions.tsv`). The adapter adds its own rows. After a context reset, trust the log, `git log` and the executor's status over your memory. *(evidence: lost-context coordinators re-ran finished work)*

`SKILL_DIR` is this file's folder. Run commands from inside the target repository.

## 6. Where things live

- **`.keryx/runs/<slug>/`** in the repository's main checkout, written `<state>` in the references: the plan, the run log, locked tests, executor rounds, review briefs and findings, QA evidence, reproductions. The folder ignores itself (`.keryx/.gitignore`), so it never shows up in `git status`; `git clean -fdx` deletes it. The first `keryx.py log` row creates the folder and its `.gitignore`: log the intake before you write any file there. A run started before keryx 1.2 keeps `.git/cursor-loop/<slug>/` until it finishes. *(fact: `.git` is a protected path, where an agent's writes prompt or are denied)*
- Start the session in the main checkout, or add it as a working directory (`/add-dir`): from a linked worktree, `.keryx/` lies outside the working directory and every write there prompts. *(fact)*
- **`.keryx/memory.md`**: this repository's traps; `~/.config/keryx/memory.md` and `config.json`: the owner's choices and executors.
- **`docs/keryx/<date>-<slug>.md`**: the run's report, committed with the change (`keryx.py report`). Screenshots, executor logs and the plan never leave `.keryx/`. *(owner)*
- **`.worktrees/<runner>-<slug>`**: each executor's worktree, on branch `<runner>/<slug>`; its fetched head is `refs/keryx/<slug>`.
