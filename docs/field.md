# Field metrics

`python field/field.py [--since DATE] [--save]` reads the owner's own session transcripts (`~/.claude/projects`) and prints, per workflow, numbers for real work: turns, busy time, tokens (subagents included), interruptions, pushback and "claimed done, then pushback". No model calls; no message text leaves the script. `--save` keeps the per-turn numbers under `~/.local/share/keryx/field/`, because old transcripts are deleted after about 30 days.

- Unit: one owner turn, from a prompt the owner typed (`origin.kind == "human"`) to the next. Busy time drops silences over 10 minutes.
- Workflow: the skills a turn ran (`attributionSkill`, `Skill` calls); a turn without one carries the session's last workflow for up to 30 turns while the owner keeps replying within 2 hours.
- Reliable: time and tokens. Rough: pushback is a keyword match (a check of 12 flagged replies found ~7 real complaints) at a 3 % base rate — too noisy to rank workflows.
- Experimental: rework (fix or revert commits on the same files within 72 h). Commits are attributed only by the SHA a turn's own `git commit` printed; quiet commits and executor commits are missed, so coverage is tiny.

Field quality for keryx v1 comes from its run log instead: escaped defects reported after "done" are logged per run.

## One real run as one result

`python field/run.py record --session <transcript.jsonl> --repo <repo> --slug <keryx slug>` turns one real keryx run into a record shaped like a bench result, saved as `~/.local/share/keryx/field-runs/<slug>.json`: wall and busy time from the owner's keryx prompt on; the owner's prompts, every question with how long it waited for an answer, interruptions; coordinator and subagent tokens by model; each executor loop (`<slug>*`) with its time, tokens and status — a loop silent for 10 minutes without a final result is `stalled`; the run log's rows and rulings; PRs first seen during the run. Re-run it at any time; `python field/run.py defect --slug <slug> "what broke"` adds a defect found after "done", and later snapshots keep it.
