# Intake

## Read first, then ask

Start with `keryx.py recall`: the owner's standing choices, this repository's known traps and settings, and what the owner granted here. What it answers you do not ask again; a remembered fact the repository has since changed is checked, not trusted. *(owner: "keryx gets its own memory … it remembers the user's decisions and adapts over time")*

Read the code, docs, data, issue and history you can reach. Ask only what changes what gets built and you cannot find out yourself. *(owner)*

- One question per message, multiple choice where possible, your recommendation first. *(owner)*
- A guess the owner can correct beats an open question. *(borrowed)*
- When the request is already complete ("fix this failing test"), skip straight to the acceptance check.
- A question that has to wait for an answer is logged with `keryx.py ask` (the question, its options, your recommendation, what it blocks), so it shows in the owner's inbox; `keryx.py answer` closes it. *(owner; evidence: "what is waiting on me? i dont understand")*

## Autonomy — ask once

Ask once, at the start, how far you may go without asking: commit only · push your branch · open a draft PR · merge to main · deploy. When the request or a standing rule already says it ("commit locally, do not push"), that is the answer: do not ask. Log the answer; it is the authority for the whole run. Inside it, do not ask again. *(owner)*

On top of it always: the repository's own rules (`CLAUDE.md`, `AGENTS.md`, contributing docs) and, before any push, merge, deploy, release or production data change on the owner's systems, the owner's standing grants: `keryx.py grants` (the file is `~/.config/keryx/grants.json`). `allow` answers the autonomy question for that action: do it once keryx's gates pass, and tell the owner afterwards. `ask`, or an action the file does not list, needs the owner's explicit words. *(owner; evidence: the skill named a grants file that did not exist, and sessions guessed differently)*

## The acceptance check

1. Name who accepts the work and what they look at: the CPO compares screens with the master; the data owner compares the live page with the source; a bug's reporter repeats the reproduction. *(owner)*
2. Turn that into a check that a script or you can run: a command, a test, a request with an expected response, a screen-by-screen comparison with a list.
3. Run it on the base. It must fail, for the reason the task names. A check that passes on the base cannot tell done from not done: fix the check, not the bar. *(owner; evidence)*
4. Write down the command and the failing output. This is the run's exit test; never relax it to finish. *(evidence)*

When no automatic check is possible (taste, look and feel), name the human judgement, prepare what they need to judge, and say so in the report. *(owner)*

- **A screen built from a design master**: the check is the list of screens and states the master shows. QA screenshots each one at the master's widths and puts master and build side by side in `qa/QA.md`; every difference is fixed or ruled. A parity script's own pass count is not the check. *(owner; evidence: 5 of 8 false "done"s in a week of field runs were UI builds the owner found off the master; a parity gate reported 0 failures while 9 of 49 screens matched)*
- **A screen without a master**: before building, show 2–3 directions as screenshots and let the owner pick; the pick is a taste call. *(owner; evidence: a finished page came back as "not visually appealing")*

## Ground truth

Before planning, a short list:

- **Facts** with where you saw them (command output, file:line, log line, doc URL).
- **Assumptions** with the cheapest test that would disprove each.
- Run that test for the riskiest assumption now, with a real call. *(evidence: plans built on an untested premise caused most fix rounds)*
- **Domain facts** when the change touches a business rule, owned data or an integration: context, terms, invariants, owner of the data, direction (`domain.md`). *(owner)*

For anything outside the repository (a library, an API, a CLI flag), read the current official docs for the installed version before relying on it. *(owner)*

**A research agent.** When the owner set one (`config.json` `"research": {"agent": "codex"}`, saved with `keryx.py setup --research codex`), hand that research to it: `keryx.py research --slug <slug> "<question>"`, one question per call. It runs Codex with the owner's own Codex login, read-only, with live web search and without the owner's Codex config, rules, plugins, apps and memories; it prints the answer with its sources, saves it as `<state>/research/NN.md` and logs a `ground-truth` row. Exit 3 means no research agent is set (the default) and exit 1 that the run failed: research it yourself then. The answer is a claim: open the source of anything a decision rests on before you rely on it. *(owner)*

## Scope

What the owner accepted is the task. When the work turns out to need something else (a refactor, a schema change, a second feature), log it, finish the task, and propose the rest as a new task with its own intake. *(evidence)*

## Size

Pick S, M or L from the skill's table now, and log it as its own row with one line of why: `keryx.py log --slug <slug> size M "<why>" - -`.
