---
description: "Initialize developer session with lazy-loaded project context"
allowed-tools: ["Bash", "Read", "Glob", "AskUserQuestion"]
---

# Initialize Session

## Step 1: Check for VCTK Updates

Run this check silently and store the result:

```bash
LOCAL_VER=$(cat .claude/skills/vibe-coding-toolkit/.version 2>/dev/null | tr -d '[:space:]' || echo "unknown")
REMOTE_VER=$(curl -fsSL --connect-timeout 2 https://raw.githubusercontent.com/jacksnxly/claude-vibe-coding-toolkit/main/VERSION 2>/dev/null | tr -d '[:space:]' || echo "$LOCAL_VER")
if [ "$LOCAL_VER" != "$REMOTE_VER" ] && [ "$REMOTE_VER" != "unknown" ] && [ "$LOCAL_VER" != "unknown" ]; then
  echo "UPDATE_AVAILABLE|$LOCAL_VER|$REMOTE_VER"
else
  echo "UP_TO_DATE|$LOCAL_VER"
fi
```

If output starts with `UPDATE_AVAILABLE`, show this notice at the TOP of your response:

```
┌─────────────────────────────────────────────────────────────┐
│  ⬆️  VCTK Update Available: {LOCAL_VER} → {REMOTE_VER}       │
│  Run: curl -fsSL https://raw.githubusercontent.com/         │
│       jacksnxly/claude-vibe-coding-toolkit/main/install.sh  │
│       | bash                                                │
└─────────────────────────────────────────────────────────────┘
```

If `UP_TO_DATE`, show nothing about versions—proceed silently.

## Step 2: Identify Developer

```bash
git config user.name
```

Store the result as `$DEV_USERNAME`.

## Step 3: Load Session Context

Read the developer's session file:

`.agent/sessions/{$DEV_USERNAME}/last_session.md`

If file doesn't exist, that's OK—new developer. Say so briefly and continue.

## Step 4: Display Context Index

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

## Step 5: Show Current State

Run briefly:

```bash
git branch --show-current
git status --short | head -10
```

## Step 6: Show Workflow Commands

```
## Vibe Coding Workflow

| Phase | Command | Output |
|-------|---------|--------|
| 1. Discovery | /vctk-feature-brief | .agent/briefs/BRIEF-*.md |
| 2. Design | /vctk-technical-spec | .agent/specs/SPEC-*.md |
| 3. Build | /vctk-implement-feature | Code changes |
| 4. Verify | /vctk-review-code | Audit report |

| Utility | Command |
|---------|---------|
| Preflight check | /vctk-init |
| Save session | /vctk-save-session |
| Update VCTK | /vctk-update |
| Sync docs | /vctk-sync-docs |
```

## Step 7: Ready Prompt

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
6. **DO** show update notice prominently if available
