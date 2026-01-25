---
name: create-issue
description: Create a well-structured issue in Linear or local markdown system with quality validation. Use when user wants to create an issue, log a bug, file a bug report, or create a feature request.
---

# Create Issue

Creates a well-structured issue in either Linear or the local markdown-based system.

## Usage

```
/issue-toolkit:create-issue [options]
```

**Options:**
- `--interactive` - Step-by-step guided creation
- `--from-conversation` - Extract from current chat context
- `--type <type>` - Pre-set: bug, feature, task, improvement
- `--quick "<title>"` - Minimal issue for trivial fixes
- `--local` - Force local system
- `--linear` - Force Linear

**Examples:**
```
/issue-toolkit:create-issue --from-conversation
/issue-toolkit:create-issue --interactive --type bug
/issue-toolkit:create-issue --local --quick "Fix typo in header"
```

---

## Issue Quality Principles

A ticket should be a contract, not a conversation starter:

1. **Title starts with a verb** - "Fix", "Add", "Update", "Implement", "Remove"
2. **Include the WHY** - Business context helps developers make tradeoffs
3. **Testable acceptance criteria** - Anyone can verify completion
4. **Small scope** - Completable in days, not weeks
5. **Self-contained** - All context in the issue, not in side channels

---

## Step 1: Detect Issue System

**Priority order:**

1. If `--linear` flag → Use Linear
2. If `--local` flag → Use local system
3. Auto-detect:
   - Check if `.issues/config.json` exists → Local system available
   - Check if Linear MCP tools respond → Linear available
   - If both available → Ask user which to use
   - If neither → Prompt to initialize local system with `/issue-toolkit:init-issue-tracker`

---

## Step 2: Gather Issue Information

### Mode A: From Conversation (`--from-conversation`)

Analyze the conversation to extract:

1. **Problem Statement** - What's broken or needed?
2. **Proposed Solution** - What approach was discussed?
3. **Technical Details** - Files, functions, APIs mentioned
4. **Acceptance Criteria** - How do we verify it works?
5. **Issue Type** - Bug, feature, task, or improvement?

Present extracted information for confirmation before creating.

### Mode B: Interactive (`--interactive`)

Use AskUserQuestion to gather step-by-step:

1. **Issue Type** - Bug, Feature, Task, Improvement
2. **Title** - Must start with verb, be specific
3. **Context/Why** - Business justification
4. **Description** - Based on type (see templates)
5. **Acceptance Criteria** - Testable conditions
6. **Technical Notes** - Relevant code, dependencies
7. **Priority** - Urgent, High, Medium, Low, None
8. **Labels** - From available or create new
9. **Assignee** - Optional

---

## Step 3: Validate Quality

Check before creating:
- [ ] Title starts with verb (Add, Fix, Update, Implement, Remove, Refactor)
- [ ] Title is specific (not "Fix bug" but "Fix calendar timezone on Safari")
- [ ] Description includes WHY (business context)
- [ ] Acceptance criteria are testable
- [ ] Scope is appropriate (single feature/fix)

### Anti-Pattern Detection

| Anti-Pattern | Detection | Suggestion |
|--------------|-----------|------------|
| Vague one-liner | Description < 50 chars | "Add more context" |
| Missing WHY | No context section | "Why does this matter?" |
| Giant multi-task | Multiple verbs, "and" | "Split into separate issues" |
| No acceptance criteria | AC empty | "How will we know it's done?" |
| Prescribed implementation | Code in description | "Describe WHAT, not HOW" |

---

## Step 4: Format Issue

### Bug Template

```markdown
## Problem
[Clear description of what's broken]

## Current Behavior
[What happens now - be specific]

## Expected Behavior
[What should happen instead]

## Steps to Reproduce
1. [Step 1]
2. [Step 2]
3. [Step 3]

**Environment:** [Browser, OS, version if relevant]

## Acceptance Criteria
- [ ] [Testable condition 1]
- [ ] [Testable condition 2]

## Technical Notes
[Relevant files, functions, or context]
```

### Feature Template

```markdown
## Context
[Why this matters - quote customer feedback if available]

## Problem Statement
[What user problem are we solving?]

## Proposed Solution
[High-level approach]

## Acceptance Criteria
Given [precondition]
When [user action]
Then [expected outcome]

## Out of Scope
[What this does NOT include]

## Technical Notes
[Implementation hints, relevant code areas]
```

### Task/Improvement Template

```markdown
## Context
[Why this work is needed]

## Current State
[How things work now]

## Desired State
[How things should work after]

## Acceptance Criteria
- [ ] [Condition 1]
- [ ] [Condition 2]

## Technical Notes
[Relevant files, dependencies, constraints]
```

---

## Step 5: Preview and Confirm

Show formatted issue to user:

```markdown
## Preview: [Title]

**Type:** [Bug/Feature/Task/Improvement]
**Priority:** [Priority level]
**System:** [Linear/Local]

---

[Full description]

---

Create this issue? (Yes / Edit / Cancel)
```

---

## Step 6: Create Issue

### For Linear

```
mcp__linear__create_issue(
  title: "...",
  team: "team-id",
  description: "...",
  labels: [...],
  priority: 0-4
)
```

### For Local

1. Generate ID from config: `PREFIX-XXX`
2. Write to `.issues/backlog/{ID}.md`
3. Update `nextId` in config.json

---

## Step 7: Confirm Creation

**Linear:**
```markdown
## Issue Created in Linear

**[TEAM-123]** Title here
https://linear.app/team/issue/TEAM-123
```

**Local:**
```markdown
## Issue Created

**[ATH-001]** Title here
Location: `.issues/backlog/ATH-001.md`

To start working: `/issue-toolkit:solve-issue ATH-001`
```
