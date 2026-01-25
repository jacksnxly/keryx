---
description: "Initialize developer session with lazy-loaded project context"
allowed-tools: ["Bash", "Read", "Glob", "AskUserQuestion"]
---

# Initialize Session

## Step 1: Identify Developer

```bash
git config user.name
```

Store the result as `$DEV_USERNAME`.

## Step 2: Load Session Context

Read the developer's session file:

`.agent/sessions/{$DEV_USERNAME}/last_session.md`

If file doesn't exist, that's OK—new developer. Say so briefly and continue.

## Step 3: Display Context Index

Output this reference table—DO NOT read these files, just list them:

```
## Quick Reference (load on-demand)

| Need | Location |
|------|----------|
| Project architecture | `.agent/System/` |
| Feature briefs | `.agent/briefs/` |
| Technical specs | `.agent/specs/` |
| Implementation plans | `.agent/Tasks/` |
| How-to guides | `.agent/SOP/` |
```

## Step 4: Show Current State

Run briefly:

```bash
git branch --show-current
git status --short | head -10
```

## Step 5: Show Workflow Commands

```
## Vibe Coding Workflow

| Phase | Command | Output |
|-------|---------|--------|
| 1. Discovery | /vctk-feature-brief | .agent/briefs/BRIEF-*.md |
| 2. Design | /vctk-technical-spec | .agent/specs/SPEC-*.md |
| 3. Build | /vctk-implement-feature | Code changes |
| 4. Verify | /vctk-review-code | Audit report |

| Session | Command |
|---------|---------|
| Save session | /vctk-save-session |
```

## Step 6: Ready Prompt

End with:

```
Session initialized for **{$DEV_USERNAME}**.

What would you like to work on?
```

---

## Rules

1. **DO NOT** read full documentation files during init
2. **DO NOT** summarize large README files
3. **DO** keep total output under 80 lines
4. **DO** let the developer request specific docs when needed
5. **DO** use Read tool later during actual work, not during init
