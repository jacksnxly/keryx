# Fresh review, and the review mode

## The fresh review (M and L, before finish)

One reviewer, fresh context, the whole branch, not just the last round's diff. *(owner)*

1. `cursor.py review-brief --slug <slug>` writes the package (commits, stat, full diff) and the reviewer's brief, and prints one `dispatch` line per finder. The brief comes from `prompts/reviewer.md`, which ships with keryx: the bar for a finding, P0–P3 and confidence, the reach and spec questions, the plan, the repository's rule files, and the exact shape of the findings file the reviewer writes. Base and head default to the executor loop's base and fetched head; for a branch or PR without a loop, pass `--base` and `--head`. *(evidence: a coordinator that retyped the prompt from memory lost the reach question and the grades)*
2. Dispatch each `dispatch` line as printed: a background subagent (Agent tool, general-purpose) with that model and that one-line prompt. Never rewrite the brief or retype its rules. When the repository keeps its architecture rules somewhere the brief's rules line does not name, append one line naming them to the brief before dispatch. *(owner)*
3. **Risk-list diffs get two finders**: `review-brief --risk` writes a second brief with a security pass (rank the changed files by risk, read what the change removed, name who could misuse each risky path and how) and prints the strongest model for the first finder and `sonnet` for the second. Dispatch both together and merge their findings by location and defect before you validate. *(evidence: a high-severity privacy defect reached through a path prefix passed one reviewer and two follow-up rounds and was found by an independent second reviewer; borrowed: parallel finders in published review tools — measured in field runs)*
4. Never pre-judge findings for the reviewer and never pass it the executor's report. *(evidence)*
5. The findings file is the review's record. `cursor.py finish` counts a review only when its file has the brief's shape (a reviewed head, a reach and a spec answer, each finding graded P0–P3 with a confidence, or "Findings: none") and its head is the shipped commit or an earlier one on its line. *(owner)*

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
   - Breadth: one fresh reviewer from `review-brief --slug <slug> --base <merge base> --head <PR head>`; for risk-list code, `--risk` and its two finders.
   - Depth: your own pass over the risk-list code and the paths the breadth pass did not mention: boundaries, error paths, concurrency, inputs at the edges of each type, and the domain facts (`domain.md`): every path that writes the state an invariant guards, every second writer, every outside payload past the edge.
3. **Validate** every finding as above. Write the confirmed ones as `file:line — failure — evidence path`.
4. **Fix** the confirmed ones through the loop: one locked failing test per finding, then the fix; S findings inline, several findings as one executor FIX brief.
5. **Re-check** as above, then finish. The report lists confirmed, fixed, rejected (with reasons) and deferred findings.

**Review only.** When the owner asks for findings without fixes ("review this, don't change anything"), stop after step 3: report the confirmed findings (`file:line — failure — evidence path — P0–P3`), the rejected ones with their reason, and the ones you could not settle. Change nothing. *(owner)*

Do not invoke other review skills or commands from inside this mode. *(evidence)*
