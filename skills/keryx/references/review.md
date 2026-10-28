# Fresh review, and the review mode

## The fresh review (M and L, before finish)

One reviewer, fresh context, the whole branch, not just the last round's diff. *(owner)*

1. `scripts/package.sh <state> <base> <head>` writes the commits, stat and diff to one file.
2. Dispatch one subagent (Agent tool), two for a risk-list diff (step 3). Model: `sonnet` by default, the strongest model when the diff touches the risk list. Its prompt:

```
Review the change in <package file> against the base <base> in <repo>. The task and its decisions:
<state>/PLAN.md. Read the surrounding code you need; change nothing.
Architecture rules of this repository (<ADR / CLAUDE.md paths>): <each rule, one line>. A break of one
of them is a defect too: cite the rule and what it lets go wrong.
Report a defect only when all of these hold: this change introduced it; the author would fix it if told;
you name the code on both ends of the path, not a guess about some other part; it rests on no unstated
assumption about intent. Most severe first, each as:
<file>:<line> — what breaks — the concrete input or state and the wrong result — P0|P1|P2|P3 — confidence 0–1
(P0: blocks use whatever the input; P1: fix before merge — data loss, security, money, wrong results served,
a broken feature or contract; P2: fix soon; P3: no visible effect).
Answer two more questions. Reach: how is the changed code reached in production — entry points, mounts and
path prefixes, middleware, proxies, feature flags, jobs, other callers of what changed? Follow the main path
to the change and report what breaks on the way. Spec: against the plan and its acceptance check, which
requirements are missing or partial, what behaviour did nobody ask for, what is implemented wrongly (quote
the plan line)? Then up to 3 lines on tests that would not catch a regression here.
No style notes, no praise, no summary of the diff.
```

3. **Risk-list diffs get two finders**, dispatched together with the same package: the strongest model with the prompt above, and `sonnet` with the prompt plus a security pass — rank the changed files by risk (auth, money, privacy, outside calls), read what the change removed (`git log -p`, blame on the deleted lines), and name who could misuse each risky path and how. Merge their findings by location and defect before you validate. *(evidence: a high-severity privacy defect reached through a path prefix passed one reviewer and two follow-up rounds and was found by an independent second reviewer; borrowed: parallel finders in published review tools — measured in field runs)*
4. Never pre-judge findings for the reviewer and never pass it the executor's report. *(evidence)* Do fill in the repository's architecture rules (its ADRs, the domain and layering lines of its `CLAUDE.md`, the plan's Domain block); with none, drop those two lines. *(owner)*

## Validate before acting

A finding is a hypothesis. For each: *(owner; evidence: a reviewer's raw findings held real bugs a short chain called clean, and many false alarms)*

- **Confirm** by reproducing it (a failing test, a request, a script) or by proving it from the code with file:line on both ends of the path.
- **Reject** with one line of reason: intended behaviour (check docs, tests, commit messages), unreachable input, already handled elsewhere (cite where).
- Repository-local logic needs no external source; external behaviour (a library, an API) needs its current docs.
- Grade by what a user gets if it ships, not by how the reviewer labelled it.

Confirmed P0 and P1 findings go back through the loop as one FIX round with a failing test per finding; P2 goes in too unless you rule it deferred, with what that costs; P3 goes to the log and the report. *(evidence)*

After the fixes: re-run the mechanical check, the gates and each fixed finding's test. A second fresh review only when the fixes touched the risk list or grew past the original diff. *(evidence: re-reviews of clean fixes found nothing new; chained reviews cost ~$25 per case)*

## Review mode: "review and fix this PR / branch"

1. **Scope.** The base is the merge base with the target branch. Read the PR description and linked issue; the acceptance check is "the confirmed defects are fixed, each proven by a test that failed before". *(owner)*
2. **Two passes, different eyes.** *(borrowed: one reviewer's recall varies run to run)*
   - Breadth: one fresh `sonnet` reviewer over the whole package (prompt above); for risk-list code, the two finders of step 3.
   - Depth: your own pass over the risk-list code and the paths the breadth pass did not mention: boundaries, error paths, concurrency, inputs at the edges of each type, and the domain facts (`domain.md`): every path that writes the state an invariant guards, every second writer, every outside payload past the edge.
3. **Validate** every finding as above. Write the confirmed ones as `file:line — failure — evidence path`.
4. **Fix** the confirmed ones through the loop: one locked failing test per finding, then the fix; S findings inline, several findings as one executor FIX brief.
5. **Re-check** as above, then finish. The report lists confirmed, fixed, rejected (with reasons) and deferred findings.

**Review only.** When the owner asks for findings without fixes ("review this, don't change anything"), stop after step 3: report the confirmed findings (`file:line — failure — evidence path — P0–P3`), the rejected ones with their reason, and the ones you could not settle. Change nothing. *(owner)*

Do not invoke other review skills or commands from inside this mode. *(evidence)*
