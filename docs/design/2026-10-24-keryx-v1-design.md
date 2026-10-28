# keryx v1 — design

Status: draft for owner review, 2026-10-24. Owner: Jackson Ly. Repository: `jacksnxly/keryx`.

## 1. Why

keryx becomes one open-source agent workflow that is fast and keeps quality, and
that is improved over time against a benchmark. It replaces today's mix of skills.
The evidence behind every decision below:

- **Product A "Ereignisse" (10-12 → 10-24, still open).** About 12 days of wall
  clock. Ranked causes: scope growth (a billing reform ran inside "parity" for ~5
  days while the feature sat untouched); false "done" signals (the parity gate
  reported 0 failures while 9 of 49 screens matched, and the agent reported the
  area closed twice); process weight (plans of 3k–22k lines that contained the code,
  so it was written twice; a deep review after every task costing ~0.85× the
  implementation; plans run strictly in sequence); waiting at gates (~47 h idle after
  questions/reports; 15 PRs waiting on an approval label the owner never refused);
  environment limits (usage limit ~11 h, Actions budget, ~1 h local gates). The
  owner answered within minutes most of the time; skill invocation itself was cheap.
- **keryx history (May → Oct).** The short skill chain (review → validate → execute)
  shipped tested fixes fast (one Product B PR: 5 findings fixed RED→GREEN in 30–45 min).
  The heavy Python successor took ~30 h and $188 on the same PR and confirmed 13 of
  555 findings, though its raw findings held real issues the short chain declared
  clean. A plain loop that runs the real tests fixed 8/10 public benchmark bugs for
  $0.60; a version that required every fix to be backed by an external document fixed
  0/10. "Converged" did not mean clean: fresh reviews of converged branches found 3,
  5 and 12 new real bugs. Validation reports were ~2.6× the size of the reviews they
  checked. Use fell from ~100 reviews/month to 1.
- **cursor-loop (8 loops, 21 Cursor runs, 10-23/24).** Cheap executors (Grok via the
  Cursor CLI) did the work; every loop converged within one fix round. Most fix
  rounds came from the coordinator's own plans and tests, not executor bugs. A
  mechanical lock check caught an executor report that falsely claimed tests were
  copied verbatim. Breaking the code on purpose (mutation probes) found weak tests in
  two loops. The 2–5-round machinery, the fresh-agent escalation and the cross-model
  second opinion never ran.

## 2. Goals

1. One system, in `jacksnxly/keryx`, that replaces the keryx skills (5), cursor-loop,
   triple-check and, for daily work, the external workflow pack the owner uses today.
   - The pack's daily functions keryx must cover: intake/brainstorm, plans, TDD,
     debugging, verification before "done", worktrees, parallel dispatch, requesting and
     receiving review, finishing a branch. (Authoring skills is not a daily function.)
   - triple-check is an always-on policy today (a session hook in Claude Code and Codex,
     named in the global CLAUDE.md). keryx ships its own short always-on evidence policy
     to take that place, so sessions that are not keryx runs keep the rule.
   - Cutover — disabling the pack and the old skills, removing the triple-check hook,
     editing the global CLAUDE.md/AGENTS.md — happens only after v1 holds the baseline's
     quality floor (§7.3), and with the owner's go. Other installed tools (review
     toolkits, spec kits, commands) are untouched in v1; they belong to the later cleanup.
2. Coordinators: Claude Code and Codex. A frontier model plans, reviews and judges.
3. Executors: cheaper models do the implementation through adapters: Cursor CLI +
   Grok, Claude Code pointed at GLM, Pi + MiniMax/GLM, Codex with a smaller model,
   Claude Sonnet or Haiku.
4. Three entry modes from v1, on one core loop: feature from a spec, bug fix, review
   and fix a PR/branch.
5. A benchmark that decides whether a change to keryx is kept, and a measured baseline
   of today's setup before keryx v1 replaces it.

## 3. Non-goals

- Self-improvement without the owner. Changes to keryx are made by hand (owner
  decision); the benchmark only reports.
- Cursor, Pi or other tools as coordinators (they are executors only).
- Proof machinery: hash-pinned campaigns, document-entailment gates, "every fix needs
  an external source" rules, multi-KB report templates.
- Release notes. The Rust release-notes tool in this repo is archived (§8).

## 4. Anti-goals — failure even if it works

Each has a guard that the benchmark and the run log measure:

| Failure | Guard |
|---|---|
| Says done when it isn't | Done = the acceptance check passes (§5.1). A check that cannot fail on the unfinished state is invalid; it is run on the base first and must fail there. Escaped defects (found after "done") are counted. |
| Bothers the owner too often | Questions only at intake and at the autonomy limit; every other uncertainty becomes a logged ruling. Owner interruptions per run are counted. |
| Grows heavy again | Size budgets (§6.6). Plans hold decisions, never implementation code. Reports are short; evidence lives in files. |
| Burns limits or money | Per-run budget, executors spread across providers, benchmark kept small (§7.4). Tokens/cost per run are logged. |

## 5. The core loop

All three modes run the same loop. Each step names its owner.

### 5.1 Intake (coordinator, with the owner)

- **Step-by-step Q&A** with the owner (owner decision): one question at a time,
  multiple-choice where possible, after keryx has read the code, docs and data it can
  read itself. Questions cover only what keryx cannot find out.
- **Autonomy, asked once** at the start: how far keryx may go without asking — push its
  branches, open draft PRs, merge to main, deploy. The answer is the authority for that
  run and is logged; keryx does not ask again for steps inside it. Repository rules and
  the owner's standing grants still apply on top (for the owner's production systems the
  grants file is read before any merge, deploy or production data change).
- **Acceptance check.** Name who accepts the work and what they look at; turn that into
  a check before any work starts. Examples: CPO parity = screen-by-screen comparison
  with the master (behaviour and look, incl. icons, adapted to the current system);
  Product B data = the live page/API against the real source; a bug = the reproduction.
  The check is run on the base and must fail there.
- **Scope rule.** When the work grows beyond the accepted task (e.g. "parity" turns
  into a billing change), the new part becomes a new task with its own intake.

### 5.2 Ground truth (coordinator)

A short block in the plan: facts with their source (command output, doc, log line),
assumptions with the cheapest test that would disprove each, and the riskiest one
tested with a real call before anything is built on it.

### 5.3 Plan (coordinator)

- Decisions, not code: files, signatures, invariants, the domain rule, out-of-bounds.
- Locked acceptance tests as exact code (they are the only code in a plan), registered
  so a mechanical check proves they are unchanged.
- **Preflight:** every done-command in the plan is run once on the base before dispatch,
  so a command that is already broken (or stricter than the repo's own gate) never
  reaches an executor.
- Slices with file ownership, so independent slices can run in parallel.

### 5.4 Execute (executors)

- Each slice runs in its own worktree and branch through an executor adapter (§6.2).
- **Parallel, capped:** independent slices (no shared files) run at once, up to 2–3,
  spread across executors so no single usage limit runs dry.
- First run per slice: tests only, proven to fail for the stated reason; then implement.
- **Escalation ladder:** after 2 failed fix rounds on the same finding, the finding moves
  to a stronger executor (e.g. Grok/GLM → Sonnet → the coordinator writes it); each step
  is logged with its reason. Code the coordinator writes still gets the fresh review in 5.7.

### 5.5 Check each slice (coordinator, mechanical first)

- Locked tests intact, diff inside the slice's bounds, the slice's tests re-run by the
  coordinator, no assistant attribution in commits.
- **Deep review only by risk:** money, auth, privacy, migrations, concurrency, data
  deletion, public contracts. Other slices get the mechanical check only.

### 5.6 QA (split; owner decision)

- The coordinator writes the QA checklist/script and the pass criteria.
- A cheap model or a script drives the browser/API and collects raw evidence
  (screenshots, responses, logs). Its own verdict does not count.
- The coordinator judges the raw evidence. Mutation probes are mandatory: break the
  change on purpose and confirm the tests and QA notice.
- The owner decides only taste calls (e.g. the CPO's look).

### 5.7 Fresh review before merge (coordinator, fresh context)

One full-branch review with fresh context and full scope, not limited to the last
diff. Findings go through validation (reproduce or prove from the code; reject false
alarms; no external-source requirement for repo-local logic), then back into 5.4.

### 5.8 Finish (coordinator)

Act within the autonomy limit (push, draft PR, merge, deploy with a written rollback,
production QA), then report: what changed, the acceptance evidence, open gaps, rulings.

## 6. Components

### 6.1 Modes

- **Feature:** full intake Q&A → acceptance check → plan → loop.
- **Bug:** reproduce twice on the real surface → locked failing test → loop.
  CI repair is part of this mode (owner decision): a red CI job is a bug whose
  reproduction is the failing job; the mode adds CI-specific checks (errors inside
  HTTP-200 bodies, flaky reruns, the Actions budget, push rarely).
- **Review a PR/branch:** fresh review → validate each finding → fix the confirmed ones
  through the loop → fresh review of the result.

### 6.2 Executor adapters

One interface: start a run (brief, worktree, model) and stream events; resume/follow
up; status; cancel; parse the final report. Guard rails per adapter where the tool
supports them: own worktree, command deny list, no cluster or SSH credentials, a push
URL that goes nowhere, attribution off.

| Adapter | Basis | Known facts (checked 2026-10-23/24) |
|---|---|---|
| Cursor CLI | `agent -p --force --output-format stream-json`, `--resume` | Works today (cursor-loop `loop.py`); per-run config dir turns attribution off. |
| Claude Code (Sonnet/Haiku) | `claude -p` headless | Same tools/hooks as the coordinator. |
| Claude Code → GLM | `claude -p` with a separate profile setting `ANTHROPIC_BASE_URL` to Z.ai's Anthropic-compatible endpoint | Z.ai docs: `https://api.z.ai/api/anthropic`; model names to be checked at build time. Never edit the owner's main settings env (separate profile). |
| Codex | `codex exec --sandbox workspace-write --json -o <file> -m <model> -C <dir>`; `codex exec resume <id>` | From the Codex CLI reference. |
| Pi | Pi SDK (`@earendil-works/pi-coding-agent`) | Used in July's benchmark (8/10 at $0.60); adapter needs isolation per Pi's security docs. |

### 6.3 Coordinator packaging

- Claude Code: a plugin (skills, hooks, agents) — also what `claude plugin eval` loads.
- Codex: the same `SKILL.md` skills (Codex reads `.agents/skills` and plugins).
  Hook/subagent differences are handled in a thin per-harness section, not by forking skills.
- Order (owner decision): v1 is proven and cut over on Claude Code first. Codex follows in
  v1.x with its own small benchmark set; it does not block the v1 cutover.

### 6.4 Run log

One append-only log per run (the cursor-loop decision log, extended). It is both the
recovery map after context resets and the benchmark's live telemetry: time per phase,
tokens/cost per executor, owner interruptions, fix rounds, each finding's cause
(plan/test defect vs executor defect), rulings, and escaped defects reported later.

### 6.5 Rule origins (first principles)

Every rule in a keryx skill carries one origin tag: `fact` (cannot be otherwise),
`owner` (the owner's rule), `evidence` (seen in our logs; cite the log), `borrowed`
(copied tactic, unproven here). Skill text never names a source pack; sources live in
the private provenance file. A `borrowed` rule must show value in the benchmark or is
deleted at the next cleanup. Cleanup order: question each rule, delete, simplify,
speed up, automate last.

### 6.6 Size budgets

Builder's call within these limits: the always-loaded entry skill stays short (one
screen of routing, not a manual); a mode loads only what it needs; a plan for one
slice fits on a screen or two plus its locked tests; a report is a short message with
links to evidence files.

## 7. Benchmark

### 7.1 Layers

1. **Skill checks — `claude plugin eval`** (Claude Code only). Cases under `evals/`:
   triggering, the autonomy question asked once, refusing "done" without passing
   evidence, small bug fixtures (`scaffold_script` seeds a git repo). Runs are isolated
   `claude -p` sessions with only the plugin loaded, 3 runs per case, a no-plugin
   baseline arm (Δ), and hard caps of 200 turns and 3600 s per run — so full feature
   loops do not fit here.
2. **Replay runner — keryx's own.** Full loops on cases with a known good outcome:
   (a) replays of the owner's past work (Product B, Product A…; private, not
   published), (b) public SWE-bench-style reverse-fix cases (publishable; July's ten-case
   harness exists in a private review benchmark).
   Runs any coordinator × executor combination. The per-change gate uses one reference
   combination (Claude Code coordinator + Cursor CLI/Grok executor, the one that works
   today); every other adapter passes a small adapter smoke set before it is used.
   **The owner's part is scripted from history** (owner decision): each case carries the
   owner's real past answers to intake questions and taste calls, taken from the
   transcripts; keryx's questions get those answers, and interruptions are counted as
   questions asked. A few release-set cases are answered by the owner live. The baseline
   needs a small driver that chains today's skills the way the owner did by hand.
3. **Live runs.** Every real keryx run's log is summarised weekly: speed, cost,
   interruptions, escaped defects.

### 7.2 Scores

- Quality: hidden tests / acceptance check pass, known defects caught in review cases,
  planted mutations caught by QA, escaped defects, false "done" count.
- Speed: wall clock to accepted, owner interruptions, idle time at gates.
- Cost: tokens and dollars per executor, share of weekly usage limits.

### 7.3 Decision rule (owner decision)

A new version may not lose quality on any case group. Among versions that hold
quality, the faster one wins. Cost is a cap, not a goal.

### 7.4 Budget (owner decision)

Small and frequent: ~10 replay cases, under ~2 h and a few dollars, before every keryx
change that touches the loop; the larger set only before releases.

- Case size (coordinator's call): per-change cases are slice-sized (~10–15 min each):
  bug replays, review cases with known defects, one feature slice with an acceptance
  check. Full multi-day features run only in the release set and the live runs.
- The multi-day failure modes are pinned by targeted small cases instead: an acceptance
  check that must fail on the base, a request that grows in scope mid-run, a planted
  "all green but not done" state, a gate where the autonomy limit applies.
- Dollars = API-billed executor and judge calls. A subscription coordinator is counted as
  its share of the weekly usage limit.
- One run per case in the per-change gate; any case that loses quality is re-run 3× before
  the verdict (builder may tune).

### 7.5 Baseline first

Before keryx v1 replaces anything, the same small set runs on today's setup (keryx
skills + cursor-loop + the current packs) to set the floor v1 must hold.

## 8. Repository

- Archive the release-notes tool: tag its last version, remove its code from `main`;
  releases and tags stay downloadable (owner decision).
- Layout (builder's call in detail): `skills/`, `adapters/`, `bench/` (replay runner and
  public cases), `evals/` (plugin eval), `docs/`.
- Copied passages are recorded in the private provenance file
  (`.git/keryx-private/provenance.md`, never committed). The third-party notices go in
  before the first public push that contains copied text.
- Today's cursor-loop is folded into keryx rather than fixed separately; its known
  defects (§1) are design inputs here.

## 9. Decided by the owner

Coordinators Claude Code + Codex · executors: Cursor+Grok, Claude Code→GLM, Pi,
Codex small model, Claude Sonnet/Haiku · QA split · all three modes in v1 · autonomy
asked once per run · reuse `jacksnxly/keryx`, archive the release-notes tool ·
standalone, no source packs named in skill text, attribution at the end · absorb keryx
skills, cursor-loop, triple-check and the packs for daily work · benchmark from past
work + public cases + live runs · quality floor then speed · small frequent benchmark ·
manual improvement only · parallel capped · escalation ladder · review by risk plus a
fresh full review before merge · step-by-step intake Q&A · benchmark answers scripted
from the owner's history · Codex follows in v1.x · CI repair folded into bug mode.

## 10. Calls made by the coordinator (owner to check)

- Benchmark and baseline are built before keryx v1's loop.
- v1 ships all three modes; inside v1 they may land in stages.
- Mutation probes and done-command preflight are mandatory steps.
- The acceptance check must fail on the base before work starts.
- Deep-review risk list: money, auth, privacy, migrations, concurrency, data deletion,
  public contracts.
- Escalation threshold: 2 failed rounds on the same finding.
- Parallel cap 2–3.
- keryx ships its own always-on evidence policy in place of triple-check's hook; cutover
  only after v1 holds the quality floor, with the owner's go.
- Per-change benchmark cases are slice-sized; multi-day failure modes are pinned by
  targeted small cases; the reference combination is Claude Code + Cursor/Grok.

## 11. Left to the builder

File formats, script language, names, exact thresholds (tuned by the benchmark), the
per-harness section, the replay runner's internals, and which past-work cases make up
the first 10.

## 12. Known unknowns

- `claude plugin eval` may be in early access on some accounts; Claude Code here is
  2.1.310 (needs ≥ 2.1.269).
- Codex hooks: not yet read in the official docs.
- GLM model names and limits on the owner's plan.
- Cost and access of the SWE-bench evaluator used in July.
- Cursor cloud runs stay unusable while API-started runs need prepaid credit.
