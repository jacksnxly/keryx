# Feature Brief: keryx push Command

## Problem
The CLI can generate and create commits via `keryx commit`, but users still need to run a separate `git push` to publish changes. This adds friction and interrupts the flow.

## Goal
Add a `keryx push` subcommand that behaves exactly like `keryx commit`, then pushes the resulting commit(s) to the remote as the final step.

## Non-Goals
- No custom remote selection or upstream configuration logic.
- No changes to `keryx commit` behavior.
- No changes to changelog generation commands.

## User Stories
- As a developer, I want to generate an AI commit message and immediately push, so I can publish changes in one step.
- As a developer, I want `--message-only` and `--dry-run` to avoid committing or pushing.
- As a developer, I want split-commit behavior to remain unchanged, with a single push afterward.

## Acceptance Criteria
- `keryx push` supports `--message-only` and `--no-split` like `keryx commit`.
- When a commit is created, `keryx push` pushes to the remote.
- When `--message-only` or `--dry-run` is set, no push occurs.
- Errors from `git push` are surfaced to the user.
