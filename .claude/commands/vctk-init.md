---
description: "Preflight check to verify VCTK installation and project readiness"
allowed-tools: ["Bash", "Read", "Glob", "AskUserQuestion"]
---

# VCTK Preflight Check

Verify that the Vibe Coding Toolkit is properly installed and the project is ready for the workflow.

---

## Step 1: Check VCTK Installation

Verify all commands are installed:

```bash
echo "=== VCTK Commands ===" && \
ls -1 .claude/commands/vctk-*.md 2>/dev/null | wc -l | xargs -I {} echo "Found {} commands" && \
ls -1 .claude/commands/vctk-*.md 2>/dev/null
```

**Required commands (9 total):**
- `vctk-feature-brief.md`
- `vctk-technical-spec.md`
- `vctk-implement-feature.md`
- `vctk-review-code.md`
- `vctk-init-session.md`
- `vctk-save-session.md`
- `vctk-update.md`
- `vctk-sync-docs.md`
- `vctk-init.md`

If any missing → Report which ones and suggest: `Run the install script to fix.`

---

## Step 2: Check Skills Installation

```bash
echo "=== VCTK Skills ===" && \
ls -d .claude/skills/vibe-coding-toolkit/*/ 2>/dev/null | wc -l | xargs -I {} echo "Found {} skills"
```

**Required skills (4 total):**
- `feature-brief/`
- `technical-spec/`
- `implement-feature/`
- `review-code/`

---

## Step 3: Check .agent Folder Structure

```bash
echo "=== .agent Structure ===" && \
for dir in .agent .agent/briefs .agent/specs .agent/sessions .agent/Tasks .agent/System .agent/SOP; do
  if [ -d "$dir" ]; then
    echo "[ok] $dir"
  else
    echo "[missing] $dir"
  fi
done
```

If any missing → Create them:
```bash
mkdir -p .agent/{briefs,specs,sessions,Tasks,System,SOP}
```

---

## Step 4: Check Version and Updates

```bash
LOCAL_VER=$(cat .claude/skills/vibe-coding-toolkit/.version 2>/dev/null | tr -d '[:space:]' || echo "unknown")
REMOTE_VER=$(curl -fsSL --connect-timeout 3 https://raw.githubusercontent.com/jacksnxly/claude-vibe-coding-toolkit/main/VERSION 2>/dev/null | tr -d '[:space:]' || echo "$LOCAL_VER")
echo "Local version: $LOCAL_VER"
echo "Remote version: $REMOTE_VER"
if [ "$LOCAL_VER" != "$REMOTE_VER" ] && [ "$REMOTE_VER" != "unknown" ] && [ "$LOCAL_VER" != "unknown" ]; then
  echo "UPDATE_AVAILABLE"
else
  echo "UP_TO_DATE"
fi
```

If update available → Show notice.

---

## Step 5: Check Current Workflow State

```bash
echo "=== Workflow State ===" && \
echo "Briefs:" && ls -1 .agent/briefs/BRIEF-*.md 2>/dev/null | head -5 || echo "  (none)" && \
echo "Specs:" && ls -1 .agent/specs/SPEC-*.md 2>/dev/null | head -5 || echo "  (none)"
```

Report:
- Number of feature briefs
- Number of technical specs
- Any specs pending implementation (status != APPROVED)

---

## Step 6: Check Git Status

```bash
echo "=== Git Status ===" && \
git branch --show-current 2>/dev/null || echo "(not a git repo)" && \
git status --short 2>/dev/null | head -5
```

---

## Step 7: Generate Readiness Report

Output a summary table:

```
VCTK Preflight Check
====================

| Component | Status | Notes |
|-----------|--------|-------|
| Commands | [status] | [X/9 installed] |
| Skills | [status] | [X/4 installed] |
| .agent folders | [status] | [created/exists] |
| Version | [version] | [up-to-date/update available] |
| Git | [branch] | [clean/X uncommitted] |

Workflow State
--------------
Briefs: [N] (latest: [name])
Specs: [N] (latest: [name])

[Overall status message]
```

---

## Step 8: Next Steps

Based on readiness, suggest next action:

**If NOT ready:**
```
AskUserQuestion({
  questions: [{
    question: "VCTK setup incomplete. What would you like to do?",
    header: "Fix",
    options: [
      { label: "Run installer", description: "Re-run install script to fix missing components" },
      { label: "Create folders", description: "Just create missing .agent folders" },
      { label: "Continue anyway", description: "Proceed despite missing components" }
    ],
    multiSelect: false
  }]
})
```

**If ready but no briefs:**
```
Ready to go! Start with /vctk-feature-brief to define your first feature.
```

**If has briefs but no specs:**
```
Ready to go! You have [N] briefs. Run /vctk-technical-spec to design the next one.
```

**If has specs ready for implementation:**
```
Ready to go! Spec [name] is approved. Run /vctk-implement-feature to build it.
```

**If update available:**
```
Note: VCTK update available ([old] → [new]). Run /vctk-update to upgrade.
```

---

## Quick Reference

At the end, always show:

```
VCTK Workflow Commands
----------------------
/vctk-feature-brief      Phase 1: Define requirements
/vctk-technical-spec     Phase 2: Research & design
/vctk-implement-feature  Phase 3: Build from spec
/vctk-review-code        Phase 4: Audit implementation

Utility Commands
----------------
/vctk-init-session       Load developer context
/vctk-save-session       Save session state
/vctk-update             Update VCTK
/vctk-sync-docs          Sync .agent documentation
/vctk-init               This preflight check
```
