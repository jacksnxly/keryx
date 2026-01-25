---
description: "Save session context for continuity across conversations"
allowed-tools: ["Bash", "Read", "Write", "Glob", "Grep"]
---

# Save Session

You are an expert session documenter. Create comprehensive session summaries that capture all changes and context, ensuring any engineer or LLM can understand exactly what was accomplished.

## Step 1: Get Developer Identity

```bash
git config user.name
```

Store as `$DEV_USERNAME`.

## Step 2: Create Developer Folder

```bash
mkdir -p .agent/sessions/{$DEV_USERNAME}
```

## Step 3: Analyze Session

Gather information about what happened this session:

1. **Check git status** for modified/added files
2. **Check recent commits** if any were made
3. **Review conversation context** for what was discussed/built
4. **Check .agent/briefs/** for new feature briefs created
5. **Check .agent/specs/** for new specs created

## Step 4: Generate Session Summary

Write to `.agent/sessions/{$DEV_USERNAME}/last_session.md`:

```markdown
# Session Summary [YYYY-MM-DD]

## Developer

**Git Username:** `{$DEV_USERNAME}`

## Session Objective

[Clear statement of what this session aimed to accomplish]

## Files Modified

### Created
- `path/to/file.ext` - [purpose]

### Modified
- `path/to/file.ext` - [what changed]

### Deleted
- `path/to/file.ext` - [reason]

## Implementation Details

### Main Changes
[Detailed explanation of what was built/fixed/refactored]

### Technical Decisions
[Key choices made and reasoning]

### Code Structure
[If new patterns or architecture was introduced]

## Workflow Progress

| Phase | Document | Status |
|-------|----------|--------|
| Brief | .agent/briefs/BRIEF-*.md | [Created/Updated/N/A] |
| Spec | .agent/specs/SPEC-*.md | [Created/Updated/N/A] |
| Implementation | [files] | [In Progress/Complete/N/A] |
| Review | [audit] | [Passed/Pending/N/A] |

## Testing & Validation

[What was tested and results]

## Current State

[Where the project stands after this session]

## Blockers/Issues

- [Any unresolved problems]
- [TODOs that weren't completed]

## Next Steps

1. [Priority task for next session]
2. [Secondary tasks]

## Related Documentation

- [Links to relevant docs in .agent folder]
```

## Step 5: Confirm Save

After writing, confirm:

```
Session saved to .agent/sessions/{$DEV_USERNAME}/last_session.md

Summary:
- [1-2 sentence summary of session]
- Next: [Primary next step]
```

---

## Guidelines

- Run this at the end of each coding session before switching context
- Include enough detail to resume work after time away
- Reference specific file paths and line numbers where relevant
- Capture the "why" behind decisions, not just the "what"
- Keep it concise but complete
