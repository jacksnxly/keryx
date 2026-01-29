---
status: APPROVED
author: Developer Interview
created: 2026-01-29
feature: LLM Provider Selection + Codex Fallback
---

# Feature Brief: LLM Provider Selection + Codex Fallback

## Problem

**Persona:** Developers using `keryx` to generate release notes, currently dependent on Claude CLI.

**Trigger:** Running `keryx` when Claude CLI is unavailable, or when users prefer Codex.

**Pain:**
- Single-provider dependency causes hard failures if Claude CLI isn't installed/authenticated or is rate-limited.
- No way for users to explicitly select provider for their environment.
- In automation, reliability suffers without a fallback path.

## Solution

Introduce provider selection with Codex support and automatic fallback behavior.

### User Journey

1. Developer runs `keryx`.
2. `keryx` selects a provider based on CLI flags or default policy.
3. `keryx` attempts generation with the selected provider.
4. If generation fails, `keryx` falls back to the alternate provider when allowed.
5. If both providers fail, `keryx` reports a clear error describing both failures.

### Provider Selection

- Users can explicitly choose a provider via a CLI flag (e.g., `--provider codex|claude`).
- Default behavior uses a provider preference order with fallback.

### Default / Fallback Policy (confirmed)

- Default order: Claude → Codex.
- Codex CLI is supported as a provider (CLI only).
- If users explicitly choose Codex and it fails, fall back to Claude.
- If users explicitly choose Claude and it fails, fall back to Codex.
- If both fail, surface a combined error.

### Error Handling

- If a provider binary is missing or fails execution, attempt fallback when policy allows.
- If both providers fail, return an error that includes:
  - which providers were attempted
  - per-provider failure reason
  - suggested remediation steps (install/authenticate CLI)

## Scope

### In Scope
- Add Codex CLI provider for changelog generation.
- Provider selection flag (`--provider`).
- Fallback logic with clear error messages.
- Keep existing Claude provider behavior unchanged.

### Out of Scope
- Switching to the OpenAI API for Codex (CLI only for now).
- Additional LLMs/providers beyond Claude and Codex.
- New config file formats or persistent provider preferences.

## Examples

### Default Run (Fallback on Failure)

```
$ keryx
```

Behavior (intended):
- Provider chosen by default policy.
- If provider fails, automatically try the other.
- If success, proceed to write changelog.

### Explicit Codex Run

```
$ keryx --provider codex
```

Behavior:
- Attempt Codex first.
- If Codex fails, fallback to Claude.
- If Claude fails, return combined error.

### Explicit Claude Run

```
$ keryx --provider claude
```

Behavior:
- Attempt Claude only (or fallback policy TBD).

## Open Questions

1. **Error messaging:** Should we include raw stderr from both providers or summarize?
2. **Future API support:** Do we want to reserve the option for direct API usage later?

## Priority

**Urgency:** Medium-High
- Improves reliability across environments (local + CI)
- Reduces hard dependency on a single CLI
- Enables users to standardize on their preferred provider
