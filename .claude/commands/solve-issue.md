---
description: "Solve an issue end-to-end (auto-detects Linear, local system, or inline description)"
argument-hint: "<issue-id-or-description> [--skip-research] [--dry-run]"
allowed-tools: ["Bash", "Read", "Write", "Edit", "Glob", "Grep", "Task", "WebSearch", "TodoWrite", "mcp__linear__get_issue", "mcp__linear__update_issue", "mcp__linear__list_issue_statuses", "mcp__linear__create_comment"]
---

# Solve Issue

**Arguments:** "$ARGUMENTS"

Comprehensive workflow to solve an issue from start to finish, supporting Linear, local markdown-based systems, and inline issue descriptions.

---

## Step 1: Parse Arguments

Extract:
- **Input** - Could be:
  - Issue ID (e.g., `ATF-52`, `ATH-001`)
  - Inline description (any text that doesn't match ID patterns)
- **Flags:**
  - `--skip-research` - Skip web research phase
  - `--dry-run` - Plan only, don't execute

---

## Step 2: Detect Input Type

Determine what kind of input was provided:

### Pattern Matching

1. **Linear/Local ID pattern:** Matches `[A-Z]+-[0-9]+` (e.g., `ATF-52`, `ATH-001`)
   - First try Linear: `mcp__linear__get_issue(id: "<issue-id>")`
   - If not found, search local: `.issues/*/<issue-id>.md`

2. **Inline description:** Everything else
   - Contains spaces, sentences, file paths, or error descriptions
   - Does NOT match the `[A-Z]+-[0-9]+` pattern
   - → Use **Inline Path**

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
    │       │                                   └─► Not found → Error
    │       │
    │       └─► No (contains spaces, sentences, etc.)
    │                  │
    │                  └─► Inline Path
    │
    └─► Empty → Error: No issue provided
```

**IMPORTANT:** If input contains multiple words, sentences, file paths, or error descriptions, treat it as an **Inline Issue** - do NOT try to look it up in Linear or local systems.

---

## Step 3: Route to Appropriate System

- **Linear Path** → [Solve Linear Issue](#solve-linear-issue)
- **Local Path** → [Solve Local Issue](#solve-local-issue)
- **Inline Path** → [Solve Inline Issue](#solve-inline-issue)

---

# Solve Linear Issue

## L1: Fetch Issue Details

```
mcp__linear__get_issue(id: "<issue-id>", includeRelations: true)
```

Extract:
- Title and description
- Affected files (from description)
- Acceptance criteria
- Priority and labels
- Related issues

## L2: Launch Issue Validator Agent

**Agent:** `issue-validator`

Determine if issue is still relevant by examining codebase.

**Outputs:**
- `STILL_RELEVANT` → Continue
- `ALREADY_FIXED` → Add comment, close, exit
- `PARTIALLY_FIXED` → Note scope, continue
- `CANNOT_DETERMINE` → Ask for clarification

## L3: Launch Best Practices Researcher

**Skip if:** `--skip-research` flag

**Agent:** `best-practices-researcher`

Search for credible solutions from:
- Official documentation
- Engineering blogs (Netflix, Stripe, Airbnb)
- Reputable publications

**Output:** Research summary with links.

## L4: Launch Implementation Planner

**Agent:** `implementation-planner`

Create detailed plan with:
- Step-by-step changes
- Files to modify
- Code snippets
- Risk assessment
- Testing strategy

## L5: Dry Run Check

**If `--dry-run`:**
- Display plan
- Exit without executing

## L6: Execute Plan

For each step:
1. Create todo items
2. Read target file
3. Make changes with Edit tool
4. Mark complete
5. Proceed to next

## L7: Launch Build Verifier

**Agent:** `build-verifier`

Run:
- `npm run build`
- `npm run check`
- Tests if available

**If fails:** Fix and retry.

## L8: Update Linear Status

**Agent:** `linear-status-updater`

Actions:
1. Move to "In Review" (or "Done")
2. Add implementation comment with:
   - Approach taken
   - Files changed
   - Research sources
   - Testing status

---

# Solve Local Issue

## C1: Load Issue

```
Find .issues/*/<issue-id>.md
Read file content and frontmatter
```

Parse YAML frontmatter:
```yaml
id: "ATH-001"
title: "Fix calendar bug"
type: bug
status: backlog
priority: high
labels: [frontend]
```

## C2: Move to In Progress

Move file from current folder to `in-progress/`:

```bash
mv .issues/backlog/ATH-001.md .issues/in-progress/ATH-001.md
```

Update frontmatter:
```yaml
status: in-progress
updated: "[TODAY]"
```

## C3: Launch Issue Validator Agent

**Agent:** `issue-validator`

Same validation as Linear path:
- Examine codebase for issue relevance
- Check if already fixed

**If ALREADY_FIXED:**
1. Move to `done/`
2. Add resolution note to file
3. Exit

## C4: Launch Best Practices Researcher

**Skip if:** `--skip-research` flag

**Agent:** `best-practices-researcher`

Same research process as Linear path.

## C5: Launch Implementation Planner

**Agent:** `implementation-planner`

Create detailed plan based on:
- Issue content
- Validation results
- Research findings

## C6: Dry Run Check

**If `--dry-run`:**
- Display plan
- Keep issue in `in-progress/`
- Exit

## C7: Execute Plan

Same execution as Linear:
1. Todo tracking
2. File modifications
3. Atomic changes

## C8: Launch Build Verifier

**Agent:** `build-verifier`

Same build verification as Linear.

## C9: Update Issue Status

### Move to In Review

```bash
mv .issues/in-progress/ATH-001.md .issues/in-review/ATH-001.md
```

### Update Frontmatter

```yaml
status: in-review
updated: "[TODAY]"
```

### Add Resolution Section

Append to issue file:

```markdown
---

## Resolution

**Completed:** [DATE]

### Approach
[Brief description of approach taken]

### Changes Made
- `path/to/file1.ts`: [What changed]
- `path/to/file2.ts`: [What changed]

### Research Sources
- [Link 1]
- [Link 2]

### Testing
- [x] Build passes
- [x] Type checks pass
- [ ] Manual testing required

---
*Solved by Claude Code*
```

## C10: Output Summary

```markdown
## Issue Solved

**[ATH-001]** Fix calendar timezone bug
Status: `in-review`
Location: `.issues/in-review/ATH-001.md`

### Changes Made
- `src/components/Calendar.svelte`: Fixed timezone conversion
- `src/lib/dates.ts`: Added locale-aware formatting

### Next Steps
1. Review the changes
2. Run manual tests
3. Move to `done/` when verified
```

---

# Solve Inline Issue

Use this path when the input is a free-form issue description rather than an issue ID.

## I1: Parse Issue Description

Extract from the inline description:
- Problem statement
- Affected files (if mentioned)
- Expected behavior
- Any provided fix suggestions

**Example inputs:**
```
"Fix the TypeScript error in UserProfile component"
"Add 'none' variant to SignalStrengthSchema to match Rust backend"
"The API returns 500 when email is empty - add validation"
"Critical Issues (1 found)
  1. Missing 'none' in SignalStrengthSchema
  File: apps/webapp/src/lib/validation/cme-gap.schema.ts:104
  ..."
```

## I2: Launch Issue Validator Agent

**Agent:** `issue-validator`

Even for inline issues, ALWAYS validate first:
- Examine codebase to confirm the issue exists
- Check if it's already been fixed
- Identify the exact scope of changes needed

**Outputs:**
- `STILL_RELEVANT` → Continue
- `ALREADY_FIXED` → Report and exit
- `PARTIALLY_FIXED` → Note scope, continue
- `CANNOT_DETERMINE` → Ask for clarification

## I3: Launch Best Practices Researcher

**Skip if:** `--skip-research` flag

**Agent:** `best-practices-researcher`

Same research process as other paths:
- Search official documentation
- Find relevant best practices
- Identify potential pitfalls

## I4: Launch Implementation Planner

**Agent:** `implementation-planner`

Create detailed plan with:
- Step-by-step changes
- Files to modify
- Code snippets
- Risk assessment
- Testing strategy

## I5: Dry Run Check

**If `--dry-run`:**
- Display plan
- Exit without executing

## I6: Execute Plan

Same execution as other paths:
1. Create todo items for tracking
2. Read target files
3. Make changes with Edit tool
4. Mark complete
5. Proceed to next step

## I7: Launch Build Verifier

**Agent:** `build-verifier`

Same build verification as other paths.

## I8: Output Summary (No Status Update)

Since inline issues aren't tracked in any system, skip status updates.

```markdown
## Issue Solved

**Issue:** [Brief description from input]

### Validation
✓ Issue confirmed - [what was found]

### Research
✓ [Research summary if applicable]

### Changes Made
- `path/to/file1.ts`: [What changed]
- `path/to/file2.ts`: [What changed]

### Build Status
✓ Build passes
✓ Type checks pass

### Next Steps
1. Review the changes
2. Run manual tests
3. Consider creating a tracked issue for documentation
```

---

# Shared Agents

All three paths (Linear, Local, Inline) use the same agents:

| Agent | Purpose |
|-------|---------|
| `issue-validator` | Check if issue still relevant |
| `best-practices-researcher` | Find credible solutions |
| `implementation-planner` | Create detailed plan |
| `build-verifier` | Verify build passes |

The difference is the final status update:
- **Linear:** MCP tools to update status and add comment
- **Local:** File move and markdown update
- **Inline:** Summary only (no status to update)

---

# Options

| Option | Description |
|--------|-------------|
| `--dry-run` | Create plan only, don't execute |
| `--skip-research` | Skip web research phase |

---

# Examples

## Solve Linear Issue

```bash
/solve-issue ATF-52
```

Output:
```
Detected: Linear issue ATF-52

[Validation] ✓ Issue still relevant
[Research] ✓ Found 3 relevant sources
[Planning] ✓ Created 5-step implementation plan
[Execution] ✓ Modified 2 files
[Build] ✓ All checks pass
[Status] ✓ Moved to "In Review"

Issue ATF-52 solved and ready for review.
```

## Solve Local Issue

```bash
/solve-issue ATH-001
```

Output:
```
Detected: Local issue ATH-001 (was in backlog/)

[Status] → Moved to in-progress/
[Validation] ✓ Issue still relevant
[Research] ✓ Found 2 relevant sources
[Planning] ✓ Created 3-step implementation plan
[Execution] ✓ Modified 1 file
[Build] ✓ All checks pass
[Status] → Moved to in-review/

Issue ATH-001 solved.
Location: .issues/in-review/ATH-001.md
```

## Dry Run

```bash
/solve-issue ATH-001 --dry-run
```

Output:
```
Detected: Local issue ATH-001

[Validation] ✓ Issue still relevant
[Research] ✓ Found sources
[Planning] ✓ Plan created

## Implementation Plan for ATH-001

### Summary
Fix calendar timezone conversion...

### Changes Required
1. `src/components/Calendar.svelte` - Update timezone handling
2. `src/lib/dates.ts` - Add conversion function

### Testing Strategy
- Unit test timezone conversion
- Manual test in Safari

---
DRY RUN: Plan created but not executed.
Run without --dry-run to implement.
```

## Solve Inline Issue

```bash
/solve-issue "Missing 'none' in SignalStrengthSchema - File: cme-gap.schema.ts:104"
```

Output:
```
Detected: Inline issue description

[Validation] ✓ Issue confirmed - SignalStrengthSchema missing 'none' variant
[Research] ✓ Checked Rust backend enum definition
[Planning] ✓ Created 2-step implementation plan
[Execution] ✓ Modified 2 files
[Build] ✓ All checks pass

## Issue Solved

**Issue:** Missing 'none' in SignalStrengthSchema

### Changes Made
- `cme-gap.schema.ts`: Added 'none' to SignalStrengthSchema enum
- `cme-gap.schema.test.ts`: Added test for 'none' value

### Build Status
✓ Build passes
✓ 60 tests pass
```

---

# Error Handling

| Error | Linear | Local | Inline |
|-------|--------|-------|--------|
| Issue not found | Check ID, permissions | Check .issues/ exists | N/A |
| Build fails | Report errors, don't update status | Keep in `in-progress/` | Report errors |
| Validation unclear | Ask for clarification | Ask for clarification | Ask for clarification |
| Issue already fixed | Add comment, close | Move to done/ | Report and exit |

---

# Notes

- **Always validates before starting work** - Even for inline issues
- **Always researches best practices** - Unless `--skip-research` is passed
- **Always creates implementation plan** - Before making any changes
- Build must pass before status update (for tracked issues)
- Local issues get resolution notes appended
- Linear issues get comprehensive comments
- Inline issues get summary only (no status to update)
- All three paths use the same agent pipeline
