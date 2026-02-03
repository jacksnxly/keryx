# Technical Spec: keryx push Command

## Overview
Introduce a new `push` subcommand that reuses the existing commit flow and pushes the resulting commit(s) to the remote using the git CLI.

## Design
- Add a new `Commands::Push` clap variant with `message_only` and `no_split` flags.
- Refactor commit flow to return a `CommitOutcome` enum:
  - `NoCommit` for message-only or dry-run.
  - `Committed(Vec<Oid>)` when commits are created.
- Implement `run_push`:
  - Call `run_commit` and, if commits were created, run `git push` as a final step.
  - Skip pushing when `CommitOutcome::NoCommit`.
- Implement `push_to_remote` using `tokio::process::Command` with stdout/stderr inherited.

## Error Handling
- If `git push` fails (non-zero exit), surface an error with the exit status.
- If `git push` cannot be executed, return a contextual error.

## Files
- `src/main.rs`
  - Add `Commands::Push` variant.
  - Introduce `CommitOutcome` enum.
  - Update `run_commit` return type.
  - Add `run_push` and `push_to_remote` helpers.

## Testing
- No new tests added; behavior relies on existing commit flow and git CLI behavior.
- Manual verification steps:
  - Run `keryx push` with staged changes on a branch with upstream.
  - Run `keryx push --message-only` and verify no commit or push.
  - Run `keryx push --dry-run` and verify no commit or push.
