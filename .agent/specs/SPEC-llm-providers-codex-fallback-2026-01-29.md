---
status: IMPLEMENTED
author: jacksnxly
created: 2026-01-29
feature: LLM Provider Selection + Codex Fallback
brief: .agent/briefs/BRIEF-llm-providers-codex-fallback-2026-01-29.md
---

# Technical Spec: LLM Provider Selection + Codex Fallback

## Summary

Add a multi-provider LLM layer to keryx with Codex CLI support and automatic fallback between Claude and Codex. The CLI gets a `--provider` flag to select a primary provider, but failures always attempt the alternate provider. Default order is Claude → Codex. Codex integration uses `codex exec` with schema-constrained JSON output to match the existing `ChangelogOutput` contract.

## Decisions

### 1) Provider Abstraction

**Choice:** Introduce a provider layer with a shared interface and a fallback orchestration function.

**Reasoning:** We need to route LLM requests to Claude or Codex and capture failures consistently. A provider abstraction keeps main CLI code stable and enables deterministic fallback behavior across both generation and verification calls.

### 2) Provider Selection Policy

**Choice:** Default provider order is Claude → Codex. `--provider` sets the primary provider, but fallback to the other is always attempted on failure. The selection is sticky: once a provider succeeds after a fallback, it becomes the primary for the rest of the run.

**Reasoning:** This satisfies the desired UX (explicit selection allowed, but fallback for reliability). Stickiness avoids repeated failures when one provider is broken for the current run.

### 3) Codex Integration (CLI)

**Choice:** Use Codex CLI in non-interactive mode (`codex exec`) and enforce structured JSON output with `--output-schema` (schema stored in-repo and/or written to a temp file). Parse the final message as `ChangelogOutput`.

**Reasoning:** CLI mode avoids API key management in the app and matches the current subprocess approach used for Claude. Schema enforcement reduces JSON parsing errors and aligns with existing output contracts.

### 4) Prompt Ownership

**Choice:** Move prompt construction into a neutral module (`llm::prompt`) and re-export as needed.

**Reasoning:** The prompt is provider-agnostic. Keeping it under `claude` becomes misleading once we add Codex.

### 5) Error Modeling

**Choice:** Add `CodexError` and a top-level `LlmError` that can wrap provider-specific failures and represent “both providers failed.”

**Reasoning:** We need to show clear failure reasons when both providers fail and avoid conflating errors across providers.

## Architecture

### Modules

- `src/llm/mod.rs`
  - `Provider` enum: `Claude`, `Codex`
  - `ProviderOrder` or `ProviderSelection` struct: primary + fallback
  - `LlmClient` (or `ProviderRouter`) with `generate(prompt)` + fallback orchestration
  - `generate_with_fallback(prompt, selection)` returns `ChangelogOutput`

- `src/llm/prompt.rs`
  - Move `ChangelogInput`, `build_prompt`, `build_verification_prompt`, `sanitize_for_prompt`

- `src/claude/` (existing)
  - Keep subprocess + retry, but make it implement the provider interface

- `src/codex/` (new)
  - `subprocess.rs`: `check_codex_installed()`, `run_codex(prompt)`
  - `retry.rs`: same backoff config as Claude

### Main flow changes

- CLI parsing: add `--provider` (global) that maps to `Provider`.
- `run_generate`/`run_init_*` and `verify_changelog_entries` should use the provider router instead of calling Claude directly.
- Provider selection (primary + fallback) created from CLI flag and passed to all LLM calls.
- On fallback, print a warning; in `--verbose` mode include details of the failure.

### Provider stickiness

- If the primary provider fails and the fallback succeeds, the client updates its primary provider for the rest of the run (e.g., verification or further historical tag processing uses the successful provider first).

## CLI Changes

- Add `--provider <claude|codex>` (global). Default: no flag (uses Claude → Codex fallback).
- Help text should mention fallback behavior.

## Error Handling

- `CodexError` mirrors `ClaudeError` variants (NotInstalled, SpawnFailed, InvalidJson, Timeout, NonZeroExit, RetriesExhausted, SerializationFailed).
- New `LlmError` variants:
  - `PrimaryFailed { provider, source }`
  - `FallbackFailed { provider, source }`
  - `AllProvidersFailed { primary, primary_error, fallback, fallback_error }`

User-facing behavior:
- If primary fails and fallback succeeds: emit warning and continue.
- If both fail: return an error summarizing both failures and remediation hints (install/auth/authenticate).
- Raw stderr is only shown in verbose mode; non-verbose still shows a concise user-facing failure notification.

## Codex CLI Details

- Command: `codex exec` in repo workdir
- Output: enforce JSON schema for `ChangelogOutput` (file-based schema; temp file if needed)
- Timeout: add `KERYX_CODEX_TIMEOUT` (default 300s, same behavior as Claude)
- Invocation should capture stdout/stderr; parse stdout as JSON; map errors to `CodexError`.

## Data Model

### Provider Enum

```rust
pub enum Provider {
    Claude,
    Codex,
}
```

### ProviderSelection

```rust
pub struct ProviderSelection {
    pub primary: Provider,
    pub fallback: Provider,
}
```

## Tests

- Unit tests for `codex::subprocess` parity with Claude:
  - timeout handling
  - non-zero exit error mapping
  - invalid JSON parsing
  - spawn failure
- Unit tests for provider selection:
  - default order is Claude → Codex
  - `--provider codex` selects Codex primary + Claude fallback
  - stickiness after fallback success
- Integration tests (if feasible):
  - simulate provider failure and ensure fallback path is used

## Documentation

- Update `README.md` with new `--provider` flag and fallback behavior.
- Update `.agent/README.md` if needed to reflect multi-provider capability.

## Rollout / Migration

- No breaking changes for existing users.
- Claude remains the default primary provider.
- Codex support is opt-in via flag but will be used automatically as fallback when Claude fails.

## Open Questions

None.
