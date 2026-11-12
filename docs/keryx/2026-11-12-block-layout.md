# block-layout: the status block is a list, because a table's layout depends on the terminal's width

2026-11-12 · keryx run `block-layout`

## Proof
- Acceptance check: the status block rendered in the real terminal UI. On 1.7.0, at 60 columns, the table came out as stacked "Header: value" records, with `Step 8 of 9` and the bar repeated as field names on every row; at 80 and 120 columns the label column was squeezed and `Waiting on you` wrapped. Now the block reads the same at 50, 60, 80 and 120 columns, and the full plan at 60 and 120.
- Fresh review: `.keryx/runs/block-layout/review/18b75a640df0..0c233ee63580.findings.md`: P0 0 · P1 0 · P2 0 · P3 0
- QA: agent exploration: the fixed script's own output, with an open question and its options, shown by the terminal UI in a test terminal at four widths (`.keryx/runs/block-layout/qa/renders/`, kept where the run ran: the three broken renders before, six after).
- Tests: 14 of the status block (12 failed on 1.7.0, among them "no line of either view is a table row"); the adapter suite `Ran 337 tests … OK` on Linux (Python 3.12, from a git archive export) and on macOS.
- The Linux run before the push failed once: two open questions came out in the file system's folder order, which the Mac runs and the fast review had not shown. Fixed behind a test that fails without the fix.
- Research: the official changelog (2.1.314) names the three ways the terminal draws a table ("grid and stacked layouts", "raw pipes"); issue reports describe the "Header: value" fallback and garbled bold in wrapped cells.

## What changed
`keryx.py progress` prints the block as a bold line with the step, the bar as a code span, and **Plan**, **Live**, **Waiting on you** and **Next** as list items, each open question with its options as a nested list; `--full` prints the plan as a numbered list. Open questions are listed oldest first, there and in `inbox`. Released as 1.7.1.

## Open
- The desktop and web apps were not looked at; the block is now ordinary Markdown lists.
- Terminals narrower than 50 columns were not tried; the bar of a nine-step run is 44 characters wide.
- Follow-up: none — waived by a ruling (`Ruling: no follow-up — …` in the run log)

## Rulings
- Ruling: no follow-up — the hotfix is the lasting fix: the block no longer uses a table, the cause (a layout that depends on the terminal's width, and data in the header row) is gone, and the tests refuse any table row in either view — there is no deeper cause left to fix — cost if wrong: the owner wants the table look back, which would be a design task of its own

## Run
- 0h 19m wall clock, 0 executor rounds (0 FIX)

## Now
- Live: keryx 1.7.1 on `main` and as tag `v1.7.1`.
- Waiting on you: nothing; say so if you want the table look back for wide terminals, which would be a design task of its own.
- Next: nothing scheduled.
