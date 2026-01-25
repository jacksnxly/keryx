---
name: solve-issue
description: Solve an issue end-to-end with validation, research, planning, execution, and status updates. Use when user wants to fix, work on, implement, or resolve an issue.
---

# Solve Issue

Comprehensive workflow to solve an issue from start to finish, supporting Linear, local markdown-based systems, and inline issue descriptions.

## Usage

```
/issue-toolkit:solve-issue <issue-id-or-description> [options]
```

**Options:**
- `--dry-run` - Create plan only, don't execute
- `--skip-research` - Skip web research phase

**Examples:**
```
/issue-toolkit:solve-issue ATH-001
/issue-toolkit:solve-issue ATF-52 --dry-run
/issue-toolkit:solve-issue ATH-001 --skip-research
/issue-toolkit:solve-issue "Fix the login button not working on mobile"
```

---

## Workflow Overview

```
┌──────────────────────┐
│  Issue Input         │  (ID or description)
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│ Detect Input Type    │ ──► Linear ID? Local ID? Inline description?
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│ Issue Validator      │ ──► Already fixed? Close & exit
└──────────┬───────────┘
           │ Still relevant
           ▼
┌──────────────────────┐
│ Best Practices       │ ──► Web search (skip with --skip-research)
│ Researcher           │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│ Implementation       │ ──► Detailed plan
│ Planner              │
└──────────┬───────────┘
           │ (--dry-run stops here)
           ▼
┌──────────────────────┐
│ Execute Plan         │ ──► Code changes
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│ Build Verifier       │ ──► Build & type checks
└──────────┬───────────┘
           │ Build passes
           ▼
┌──────────────────────┐
│ Status Updater       │ ──► Linear: API update
│ (if tracked issue)   │     Local: File move + resolution
└──────────────────────┘     Inline: Summary only
```

---

## Step 1: Parse Arguments

Extract:
- **Input** - Could be:
  - Issue ID (e.g., `ATF-52`, `ATH-001`)
  - Inline description (any text that doesn't match ID patterns)
- **Flags** - `--dry-run`, `--skip-research`

---

## Step 2: Detect Input Type

Determine what kind of input was provided:

### Pattern Matching

1. **Linear ID pattern:** Matches `[A-Z]+-[0-9]+` (e.g., `ATF-52`, `PROJ-123`)
   - Try: `mcp__linear__get_issue(id: "<issue-id>")`
   - If found → **Linear Path**

2. **Local ID pattern:** Matches `[A-Z]+-[0-9]+` but not in Linear
   - Search: `.issues/*/<issue-id>.md`
   - If found → **Local Path**

3. **Inline description:** Everything else (doesn't match ID patterns, or contains spaces/sentences)
   - Parse as free-form issue description → **Inline Path**

### Decision Tree

```
Input received
    │
    ├─► Matches [A-Z]+-[0-9]+?
    │       │
    │       ├─► Yes ─► Try Linear API
    │       │              │
    │       │              ├─► Found → Linear Path
    │       │              │
    │       │              └─► Not found → Search .issues/
    │       │                                   │
    │       │                                   ├─► Found → Local Path
    │       │                                   │
    │       │                                   └─► Not found → Error: Issue not found
    │       │
    │       └─► No (contains spaces, sentences, or doesn't match pattern)
    │                  │
    │                  └─► Inline Path
    │
    └─► Empty → Error: No issue provided
```

**IMPORTANT:** If input contains multiple words, sentences, file paths, or error descriptions, treat it as an **Inline Issue** - do NOT try to look it up in Linear or local systems.

---

## Step 3: Validate Issue (Agent: issue-validator)

Determine if issue is still relevant by examining codebase.

**Outputs:**
- `STILL_RELEVANT` → Continue with fix
- `ALREADY_FIXED` → Add comment, close, exit
- `PARTIALLY_FIXED` → Note scope, continue
- `CANNOT_DETERMINE` → Ask for clarification

---

## Step 4: Research Best Practices (Agent: best-practices-researcher)

**Skip if:** `--skip-research` flag provided

Search for credible solutions from:
- Official documentation
- Engineering blogs (Netflix, Stripe, Airbnb)
- Reputable publications (LogRocket, Smashing Magazine)

**Output:** Research summary with links and recommendations.

---

## Step 5: Create Implementation Plan (Agent: implementation-planner)

Create detailed plan with:
- Step-by-step changes
- Files to modify with line numbers
- Code snippets
- Risk assessment
- Testing strategy

**Plan format:**
```markdown
## Implementation Plan for [ISSUE-ID]

### Summary
[Brief description of the fix]

### Approach
[Technical approach based on research]

### Changes Required

#### File 1: `path/to/file.ts`
- [ ] Change X to Y
- [ ] Add error handling for Z

### Testing Strategy
- [ ] Unit tests
- [ ] Build verification

### Risks
- [Potential issues to watch for]
```

---

## Step 6: Dry Run Check

**If `--dry-run`:**
- Display the implementation plan
- Exit without executing
- User can review and run again without flag

---

## Step 7: Execute Plan

For each step in the plan:

1. Create todo items for tracking
2. Read the target file
3. Make the required changes using Edit tool
4. Mark todo as complete
5. Proceed to next step

**Best practices:**
- Make atomic changes (one logical change at a time)
- Preserve existing code style
- Add comments only where logic isn't self-evident

---

## Step 8: Verify Build (Agent: build-verifier)

Run verification:
- `npm run build` (or appropriate build command)
- `npm run check` (TypeScript/Svelte checks)
- Tests if available
- Linting

**If build fails:**
1. Analyze the error
2. Fix the issue
3. Re-run verification
4. Repeat until success

---

## Step 9: Update Status

### For Linear (Agent: linear-status-updater)

1. Move issue to "In Review" (or "Done")
2. Add implementation comment:

```markdown
## Fix Implemented

**Approach:** [Description]

**Changes:**
- `file1.ts`: [What changed]
- `file2.ts`: [What changed]

**Research Sources:**
- [Link 1]

**Testing:**
- [x] Build passes
- [ ] Manual testing required

---
*Solved by Claude Code using issue-toolkit*
```

### For Local (Agent: local-status-updater)

1. Move file: `.issues/in-progress/` → `.issues/in-review/`
2. Update frontmatter status
3. Append resolution section to issue file

### For Inline Issues (No status update)

Since inline issues aren't tracked in any system:
1. **Skip status update** - No issue to update
2. **Output summary only** - Show what was done
3. **Suggest creating issue** - Optionally create a local issue for tracking

---

## Output Summary

### For Tracked Issues (Linear/Local)

```markdown
## Issue Solved

**[ATH-001]** Fix calendar timezone bug
Status: `in-review`

### Changes Made
- `src/components/Calendar.svelte`: Fixed timezone conversion
- `src/lib/dates.ts`: Added locale-aware formatting

### Next Steps
1. Review the changes
2. Run manual tests
3. Move to `done/` when verified
```

### For Inline Issues

```markdown
## Issue Solved

**Issue:** Fix the login button not working on mobile

### Validation
✓ Issue confirmed - button click handler missing touch events

### Research
✓ Found solution in React Native docs for touch handling

### Changes Made
- `src/components/LoginButton.tsx`: Added touch event handlers
- `src/styles/mobile.css`: Fixed button sizing

### Build Status
✓ Build passes
✓ Type checks pass

### Next Steps
1. Review the changes
2. Test on mobile devices
3. Consider creating a tracked issue for documentation
```

---

## Error Handling

| Error | Action |
|-------|--------|
| Issue ID not found | Exit with error message |
| Build fails | Report errors, don't update status |
| Validation unclear | Ask for clarification |
| Inline issue ambiguous | Ask for clarification on scope |

Build must pass before status is updated (for tracked issues).

---

## Inline Issue Guidelines

When processing inline issue descriptions:

1. **Always validate first** - Use the issue-validator agent to check if the described problem exists in the codebase
2. **Research unless skipped** - Still run best-practices-researcher (unless `--skip-research`)
3. **Create implementation plan** - Plan before executing
4. **Verify build** - Always run build verification
5. **No status update** - Skip the status updater since there's no tracked issue

**Example inline inputs:**
- `"Fix the TypeScript error in UserProfile component"`
- `"Add 'none' variant to SignalStrengthSchema to match Rust backend"`
- `"The API returns 500 when email is empty - add validation"`
- Multi-line descriptions pasted from error logs or code reviews
