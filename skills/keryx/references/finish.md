# Finish

## Before you finish

- Run the done-when commands once more on the final head, and bring the branch up to date with its base (merge, not rebase, once it is shared). *(evidence)*
- Log the finish row: `cursor.py log --slug <slug> finish <what> <why> <evidence> <result>` — one per PR when the run ships several. Rulings live in the run log, nowhere else. *(evidence: a run kept its rulings in the repository's docs and logged no finish; a 27-hour run shipped five PRs under one record)*
- Remember what the next run should not have to ask or relearn: `cursor.py remember "<note>"` for an owner's choice that will recur, `--repo` for this repository's trap that cost a round. Never a secret (the command refuses anything that looks like one, a full 40-character commit id included: write short ids), never a one-off. *(owner)*

## Act within the autonomy

- Commit locally always. Push, open a draft PR, merge, deploy — only as far as the intake's autonomy answer and the repository's rules allow; before a merge, deploy, release or production data change on the owner's systems, read the standing grants first. *(owner)*
- Strip assistant attribution before anything leaves the machine (`cursor.py scrub`). *(owner)*
- A deploy comes with a written rollback and production QA of the acceptance check afterwards. *(owner)*
- Leave executor worktrees and branches in place and list them; deleting a branch needs the owner's yes. Remove your own scratch and QA worktrees. *(owner)*
- When the autonomy ends before the work is in use (commit only, or a push without a PR), end with the options, your recommendation first: merge locally, push and open a PR, keep the branch as it is, or discard it. Discarding needs the owner's typed yes. *(borrowed)*

## The report

A few lines, in the owner's words, not the process's:

1. **What changed** for the person using it, and where it lives (branch, commits, PR).
2. **Proof**: the acceptance check's command and its result on the base and now; the mutation probes and what caught them; the QA file (`<state>/qa/QA.md`), with each piece of evidence named for what it is.
3. **Open**: what was not verified and why; deferred minors.
4. **Rulings I made** you may want to change, each with what it costs if wrong.
5. Time and tokens: wall clock, executor runs, fix rounds.

Evidence lives in files; the report links them. *(owner)*
