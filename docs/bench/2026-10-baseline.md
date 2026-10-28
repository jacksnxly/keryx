# Baseline, October 2026

The floor keryx v1 must hold: today's setup measured on the private replay cases, and the candidate change to cursor-loop measured against it. Cases are private (the owner's own past work); only aggregates are published here.

## Setup

- **Baseline** (`baseline-2026-10`): the owner's daily setup — the five keryx skills, cursor-loop, an always-on verification policy and a third-party workflow pack, the owner's global instructions as session text; coordinator Opus 5.5, executor Cursor CLI (Grok).
- **Candidate** (`candidate-fp-2026-10`): identical except cursor-loop gains an acceptance check that must fail on the base, a ground-truth block, a preflight of every done-command, a scope rule and a mutation probe in every QA round.
- 7 cases scored per arm: 3 bug fixes, 3 PR reviews with a known defect each, 1 feature slice. 4 more feature cases were dropped to save usage (owner, 2026-10-25). One run per case.
- Bench `v1` at 91e0b0b for the first four cases, resumed and rescanned at 14fad8f. The arms ran in parallel for the first four cases and one after the other for the rest (see "What the run taught the bench").

## Results

| | baseline | candidate |
|---|---|---|
| Bug cases (3): quality | 1.0 / 1.0 / 1.0 | 1.0 / 1.0 / 1.0 |
| Review cases (3): known defects fixed | 0 of 3 | 1 of 3 |
| Feature case (1): quality | 0.5 (false done) | 0.5 |
| False dones | 3 | 1 |
| Owner questions | 1 | 2 |
| Median time per case | 26.9 min | 24.3 min |
| Cost, 7 cases (list prices) | $85.69 | $81.51 |
| Cost per review case | $22–27 | $18–27 |

`compare`: **candidate wins (provisional)** — quality held in every mode and the median time fell 10 %. Provisional because 4 feature cases were not run.

Read with care: one run per case. The two arms ran the *same* review chain on the review cases (cursor-loop was not used there), and one review case flipped between 0/1 and 1/1 across arms and across a re-run — run-to-run variance on review cases is at least as large as the difference measured.

## Findings for keryx v1

- **Review is the weak mode and the expensive one.** The chained review skills found 1 of 6 planted defects across both arms at ~$18–27 a case (≈600 k Opus output tokens, 25–29 M cached reads, spent in nested review agents). Bug fixing was solid everywhere.
- **Executor time dominates small bugs.** On a bug case about half the wall clock was Cursor runs; a small fix done inline would be faster.
- **Field data agrees on cost.** In the owner's own sessions (3,340 turns, 30 days), turns run under a subagent-per-task workflow used a median ~4 M fresh tokens, ~100× an ordinary turn.

## keryx v1: first data point (n = 1)

keryx v1 (`keryx-v1-dev`: the keryx skill and the evidence policy only, session text 621 words against 1,899) ran the first bug case before the owner's weekly cap stopped new cases (seven-day window at 52 %, cap 50 %): **quality 1.0, 6 min, $1.48**, against 18–20 min and $2.14–2.51 for both arms. It treated the privacy fix as M (risk list): tests on the base first, the fix, one fresh review subagent, a mutation probe, a commit. One case says nothing about quality; it does show the process running at a fraction of the time and cost. The other six cases are not run yet.

## What the run taught the bench

Fixed during the run, each with a test that failed first:

1. The leak scan resolved `../` without following the shell's folder across calls (false contamination).
2. Usage limits: the owner's five-hour window rejected the run mid-way; the runner now waits for the reset, keeps the wait out of wall time, stops new cases at a weekly cap (50 %), and `run --resume` re-runs unscored cases in place.
3. Isolation: both arms built into the same `/tmp` folder at once and left database servers running under `/tmp`. Each case now removes the `/tmp` entries it created (also when interrupted), stops processes using them, and is not scored if it used an entry that existed before it started; only one runner may run at a time.
4. Background subagents' tool calls never reach the coordinator's stream; their transcripts are now kept and scanned.
5. A reviewer walking up the parent folders for instruction files is not a leak; only another run's folder, or a glob over them, is.
6. A cheap judge called a plain final report a question; a message without a question mark is now never one.
7. `rescan` re-checks finished runs with a newer detector; `compare --common --allow-bench-mismatch` gives provisional verdicts across bench versions.

Also found, outside the bench: the cursor-loop implementer brief kept the executor alive on one global `/tmp/qa-done` file, shared by every loop on the machine.
