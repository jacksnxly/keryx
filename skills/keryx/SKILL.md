---
name: keryx
description: "Use for any code change worth more than a one-line edit — fixing a bug or a red CI job, building a feature from a spec, or reviewing and fixing a PR or branch. One loop for all three: agree what \"done\" looks like and prove it fails now, change the code (yourself or a cheaper executor), check it mechanically, QA it on the real surface, get one fresh review, and finish within the autonomy the owner gave."
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
Log the size as its own row, and again when it changes — the size the run has now, never `S → M`: `keryx.py log --slug <slug> size M "<why>" - -` (the letter first; `M — several files` reads too). `finish` reads the latest one. *(evidence: 53 of 104 field runs logged no size a program could read)*

**Urgency is a second axis.** When harm is happening now — the owner says hotfix, urgent or prod is down, or you find a failing production check, live errors or an outage and the owner agrees to the lane — take the **hotfix lane** (`references/hotfix.md`): you fix it yourself, fast, with no plan file and no executor, behind a regression test and a fast review; then the lasting fix runs as its own keryx run, and `finish` waits for it. Never for work that is merely small or "quick". *(owner)*

## 2. The loop

1. **Intake** — `references/intake.md`. Read what you can yourself, then ask only what you can't find: one question at a time, choices where possible. Ask the autonomy question once. Turn "who accepts this and what do they look at" into a check, run it on the base, and see it fail. *(owner)*
2. **Ground truth** — facts with their source, assumptions with the cheapest test that would disprove each; test the riskiest one with a real call before building on it. *(evidence)* When the change touches a business rule, owned data or an integration, the domain facts too: context, terms, invariants, who owns the data, which way imports go — `references/domain.md`. *(owner)*
3. **Plan** (M/L) — `references/plan.md`. Decisions (with the Domain block where `domain.md` applies) and locked tests, never implementation code. Run every done-command once on the base before anyone builds. *(owner; evidence)*
4. **Execute** — `references/execute.md`. The executors set up once with `keryx.py setup` (the Claude subagent when there is no setup), in `keryx.py executors` order — the plan that resets soonest first when the owner turned on `order: resets` — the next one on any error. Tests first, proven to fail for the stated reason; then the code. Escalate after 2 failed rounds on the same finding. *(evidence; owner)*
5. **Check** — `references/check.md`. Mechanical first: locked tests unchanged, diff inside bounds, tests re-run by you, no assistant attribution. Then QA on the real surface, scripted and exploratory, and at least one mutation probe. *(evidence: a lock check caught a false "copied verbatim"; probes found weak tests twice)*
6. **Fresh review** (M/L) — `references/review.md`. `keryx.py review-brief` writes the reviewer's brief (two for a risk-list diff); dispatch it exactly as printed, never a prompt of your own. One reviewer with fresh context on the whole branch; validate each finding before acting on it. At most three review rounds on one branch: after the third, what is left is fixed and checked mechanically, or deferred. *(owner; evidence: converged branches still had 3–12 real bugs; a reviewer briefed from memory lost the reach question and the grades; rounds 4 to 9 of three field runs found no P0 or P1 in 13 rounds)*
7. **Finish** — `references/finish.md`. Act within the autonomy, log a finish row, and run `keryx.py finish`: a run is finished only when it prints FINISHED — size S on its finish row; M and L with the fresh review, the report and the QA file. Then a short report with links to evidence, `keryx.py cleanup` for what was merged, and the follow-ups (§3). *(owner; evidence: three field runs in a row ended without a finish row; 10 runs overruled a NOT FINISHED that had no way to say size S, QA only or umbrella)*

Modes add their own steps: **bug** and **CI** `references/bug.md` · **feature** `references/intake.md` · **review a PR/branch** `references/review.md` · **hotfix** `references/hotfix.md`.

## 3. Rulings, not stalls

Between intake and the autonomy limit, never wait on the owner. Decide conflicts and gaps yourself with the request as the authority and log each as a ruling: what you decided, why, what it costs if wrong. *(owner; evidence: ~47 h of a 12-day run was idle at gates the owner would have waved through)*

Stop and ask only for: an irreversible or destructive step; a security-sensitive action; a step beyond the autonomy answer; a plan so broken that every way forward is a guess; a gate the repository or the owner's standing grants put on a human; a price, credit cost or billing rule the owner has not set — asked on its own, with a worked example of what a customer does, pays and gets, even when the owner said to decide everything else. Those rules outrank this skill. *(owner; evidence: two prices decided under a broad approval were wrong: a credit price "way too generous", a price the owner wanted flat)*

**What the owner granted** is one file on this machine, and `keryx.py grants` prints it for the repository you are in: `allow` means do the step once keryx's gates pass and tell the owner afterwards, `ask` means stop for it. The repository's own rules still outrank a grant. Record a grant only in the owner's words: `keryx.py grant <action> allow|ask [--repo] --source "<their words, the date>"`. *(owner; evidence: sessions in one repository released on their own while sessions in two others asked for the same production go, one waiting 520 minutes)*

**A question for the owner goes to the inbox**, never only into a message: `keryx.py ask --slug <slug> "<question>" --option "A: …" --option "B: …" --recommend A --blocks "<what waits on it>"` (no `--slug` between runs), and `keryx.py answer --slug <slug> <row> "<their answer>"` when they reply. Ask one decision per question, with the options and your recommendation, and keep working on everything that does not depend on it. `keryx.py inbox --all` is the owner's one list across repositories; a session's own status block shows only the questions of its own run. When the owner answers in your session a question another run asked, log it there (`keryx.py answer --slug <that run> <row> …`) and say so in one line; never repeat another run's question. *(owner; evidence: 9 owner waits were logged while about 35 messages ended "Waiting on you"; "what is waiting on me? i dont understand"; "what was the options again?")*

**Scope:** work that grows beyond the accepted task becomes a new task with its own intake; it never rides along. *(evidence: a billing reform ran inside "parity" for ~5 days)*

**Follow-ups:** log each follow-up the run recommends as a `next` row — `keryx.py log --slug <slug> next "<the task>" "<why>" "<evidence>" safe|risk|price` (`risk`: on the risk list; `price`: needs a price or billing rule; `safe`: neither). `finish` and `inbox` print `start` or `ask` for each, by the owner's `followups` grant. A follow-up marked `start` begins at once as its own run with its own intake, and you close its row: `keryx.py answer --slug <slug> <row> "started as <new slug>"`. One marked `ask` is a question for the inbox. Stop when nothing is left to start. *(owner: "only stop if nothing is left to do"; evidence: about 33 of 50 go-aheads in five days approved the session's own recommendation, six of them after 8 to 21 hours)*

## 4. Spend little, move fast

- The cheapest model that can do a step does it: executors write code, Sonnet reviews ordinary diffs, the strongest model only for risk-list reviews and judgement. *(owner)*
- Subagents only as the executor, for the fresh review and for parallel slices; never a reviewer per task. Never chain review skills into each other. *(evidence: chained review skills cost ~$25 per review case in the benchmark)*
- Read what you need, not whole trees; send long command output to a file and read its tail. *(evidence)*
- Start slow things (builds, installs, executor runs) in the background and keep working. *(fact)*
- Every message that ends your turn opens with what proves it — the check's result, the QA file and its screenshots, as paths — and closes with the status block that `keryx.py progress --slug <slug> --live "<what runs or is in use now, and where>" --next "<the next step>"` prints: paste its lines as they are, after a blank line, and write nothing after them. A few lines, not a log. *(owner; evidence: "where are we / what's next?" was the owner's most common check-in, a median 4.8 h after their previous prompt)*

  ```markdown
  | Step | 5 of 9 · `■■■■ ■■■■ ■■■■ ■■■■ ▶▶▶▶ ···· ···· ···· ····` |
  |---|---|
  | **Plan** | Intake → Plan → Part A → Part B → **[Part C]** → Fixes → QA → Review → Merge |
  | **Live** | Executor round 04 on its branch; a watch wakes me when it ends |
  | **Waiting** | 1 decision, listed below |
  | **Next** | Check round 04, then one fix round |

  1. **Keep the personal webhook on every paid plan?** (blocks: the price table)
     - **A: yes, as today** (recommended)
     - B: Business and above only
  ```

  It is a table, and it stays one only while its rows are short: `--live` and `--next` take at most 96 characters each (the command refuses more — say it shorter and put the detail in the message above), a long plan folds its finished steps into a count, and the decisions are listed under the table, never inside it. **Waiting** is this run's own open questions (and its slices'), each with what it blocks and its options, the recommended one in bold. Another run's questions never appear in your block: the owner answers a question where it was asked, and `keryx.py inbox --all` is the one list across runs and repositories, for when they ask for it. Never retype the block and never add emoji. *(owner: "i never know what is planned and where we exactly are"; "too much emojis"; "it should be a table"; "i needed to tell each session that i already answered"; evidence: the terminal draws a table as a grid while no cell needs more than about four lines — a 97-character cell held at 50 columns, a 164-character one came out as stacked "Header: value" records at 60 — and labels of more than one word wrapped)*
- Declare the steps as soon as the plan is settled, in the owner's words, a few words each: `keryx.py steps --slug <slug> "Intake" "Plan" "Part A: adapter" … "QA" "Review" "Merge"` (an S run: `"Check" "Fix" "Ship"`). Tick each one as it starts and as it ends — `keryx.py step --slug <slug> "Part A" running|done|failed --note "<what it is, or why it failed>"` — and declare them again when the plan changes: what is done stays done. Print the whole plan, `keryx.py progress --slug <slug> --full`, in the first message after the plan is settled, whenever the steps change, and when the owner asks where things stand. *(owner)*
- Outside a run (a question, a task with no log) close with the last three rows alone, typed as the same two-column table with short cells: **Live**, **Waiting**, **Next**. *(owner)*
- Never end a turn idle while work is in flight. Start a watch in the background that wakes you when it ends — `keryx.py wait` for an executor, `gh run watch <id>` or `gh pr checks <pr> --watch` for CI, a small polling script for a verdict or a usage-limit reset — and log what you wait on: `keryx.py log --slug <slug> waiting "<who>: <what>" <why> <evidence> "<expected by>"` (`owner: …` when it is the owner). Under the autonomy you were given, a report is not a stopping point: stop only for §3's list. *(owner; evidence: 13 nudges in one week — "and?", "are we done?", "so we sit and wait?", "why did you stop in first place?")*

## 5. Run log

M and L runs keep one log, written as you go, one row per decision: `python3 "$SKILL_DIR/scripts/keryx.py" log --slug <slug> <phase> <decision> <why> <evidence> <result>` — five quoted arguments; it prints the log's path (`.keryx/runs/<slug>/decisions.tsv`) and the row's number. The adapter adds its own rows. After a context reset, trust the log, `git log` and the executor's status over your memory. *(evidence: lost-context coordinators re-ran finished work)*

The phase is one word: `intake`, `size`, `ground-truth`, `plan`, `dispatch`, `execute`, `check`, `qa`, `probe`, `review`, `ruling`, `waiting`, `answer`, `next`, `ci`, `ship`, `deploy`, `release`, `merge`, `cleanup`, `followup`, `finish`, `done`, `note`, `repro`. The decision is the next argument; a sentence in the phase's place is refused. *(evidence: over 60 phase spellings in the field logs, some of them rulings)*

Write each ruling as `Ruling: <what> — …`; one that overturns an earlier ruling says so, `Ruling (replaces row <N>): <what>`, and the report and `finish` then list only the standing one. Write each deferred point as `minor (deferred): <what>`: only a row whose label carries `(deferred` is listed as deferred. *(evidence: 1.2.0's report listed two overturned rulings and a review row that only mentioned "deferred")*

`SKILL_DIR` is this file's folder. Run commands from inside the target repository.

## 6. Where things live

- **`.keryx/runs/<slug>/`** in the repository's main checkout, written `<state>` in the references: the plan, the run log, locked tests, executor rounds, review briefs and findings, QA evidence, reproductions. The folder ignores itself (`.keryx/.gitignore`), so it never shows up in `git status`; `git clean -fdx` deletes it. The first `keryx.py log` row creates the folder and its `.gitignore`: log the intake before you write any file there. A run started before keryx 1.2 keeps `.git/cursor-loop/<slug>/` until it finishes. *(fact: `.git` is a protected path, where an agent's writes prompt or are denied)*
- Start the session in the main checkout, or add it as a working directory (`/add-dir`): from a linked worktree, `.keryx/` lies outside the working directory and every write there prompts. *(fact)*
- **`.keryx/memory.md`**: this repository's traps; **`.keryx/config.json`**: its settings (`keryx.py repo`: the CI-parity command, and whether reports are committed or stay local). `~/.config/keryx/memory.md` and `config.json`: the owner's choices and executors; **`~/.config/keryx/grants.json`**: what the owner granted (`keryx.py grants`).
- **`.keryx/runs/owner-inbox/`**: the questions asked between runs (`keryx.py ask` without `--slug`).
- **`docs/keryx/<date>-<slug>.md`**: the run's report, committed with the change (`keryx.py report`); `<state>/REPORT.md` in a repository whose setting says `local`. Screenshots, executor logs and the plan never leave `.keryx/`. *(owner)*
- **`.worktrees/<runner>-<slug>`**: each executor's worktree, on branch `<runner>/<slug>`; its fetched head is `refs/keryx/<slug>`. The folder ignores itself, as `.keryx/` does. A GLM executor's own Claude Code config is in `.keryx/glm/<slug>/`, outside the runs its permission rules refuse it.
- Name an L run's slices `<slug>-<name>` and list them in the plan: the report and `finish` count their executor rounds with the run's, and a slice's `locked`, `gates`, `review-brief` and `finish` read the run's locks, gate list, plan and QA file when the slice has none of its own — only from a run that names the slice in its plan or its log.
