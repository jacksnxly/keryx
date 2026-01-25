---
name: init-issue-tracker
description: Initialize local markdown-based issue tracking system for projects without Linear. Use when user wants to setup local issues folder or create an issue tracking system.
---

# Initialize Local Issue Tracker

Sets up a local markdown-based issue tracking system that mirrors Linear workflows.

## Usage

```
/issue-toolkit:init-issue-tracker [project-prefix]
```

**Example:**
```
/issue-toolkit:init-issue-tracker ATH
```

---

## Step 1: Determine Project Prefix

If no prefix provided, ask the user:

```
What prefix should issues use? (e.g., ATH, PRJ, CORE)
This will create IDs like ATH-001, ATH-002, etc.
```

Validate:
- 2-5 uppercase letters
- No numbers or special characters

---

## Step 2: Create Folder Structure

```bash
mkdir -p .issues/{backlog,in-progress,in-review,done,archived}
mkdir -p .issues/templates
```

**Structure:**
```
.issues/
├── config.json           # Project settings, ID counter
├── templates/
│   ├── bug.md
│   ├── feature.md
│   ├── task.md
│   └── improvement.md
├── backlog/              # New issues awaiting work
├── in-progress/          # Currently being worked on
├── in-review/            # Ready for review/PR submitted
├── done/                 # Completed issues
└── archived/             # Old issues for reference
```

---

## Step 3: Create Config File

Write `.issues/config.json`:

```json
{
  "prefix": "[PREFIX]",
  "nextId": 1,
  "created": "[ISO_DATE]",
  "statuses": ["backlog", "in-progress", "in-review", "done", "archived"],
  "types": ["bug", "feature", "task", "improvement"],
  "priorities": ["urgent", "high", "medium", "low", "none"],
  "labels": []
}
```

---

## Step 4: Create Issue Templates

### Bug Template (`.issues/templates/bug.md`)

```markdown
---
id: "{{ID}}"
title: "{{TITLE}}"
type: bug
status: backlog
priority: medium
labels: []
created: "{{DATE}}"
updated: "{{DATE}}"
assignee: null
---

# {{TITLE}}

## Problem
<!-- Clear description of what's broken -->

## Current Behavior
<!-- What happens now - be specific -->

## Expected Behavior
<!-- What should happen instead -->

## Steps to Reproduce
1.
2.
3.

**Environment:** <!-- Browser, OS, version if relevant -->

## Acceptance Criteria
- [ ] <!-- Testable condition 1 -->
- [ ] <!-- Testable condition 2 -->

## Technical Notes
<!-- Relevant files, functions, or context -->
```

### Feature Template (`.issues/templates/feature.md`)

```markdown
---
id: "{{ID}}"
title: "{{TITLE}}"
type: feature
status: backlog
priority: medium
labels: []
created: "{{DATE}}"
updated: "{{DATE}}"
assignee: null
---

# {{TITLE}}

## Context
<!-- Why this matters - quote customer feedback if available -->

## Problem Statement
<!-- What user problem are we solving? -->

## Proposed Solution
<!-- High-level approach -->

## Acceptance Criteria
<!-- Use Given/When/Then format -->
Given <!-- precondition -->
When <!-- user action -->
Then <!-- expected outcome -->

## Out of Scope
<!-- What this does NOT include - prevents scope creep -->

## Technical Notes
<!-- Implementation hints, relevant code areas -->
```

### Task Template (`.issues/templates/task.md`)

```markdown
---
id: "{{ID}}"
title: "{{TITLE}}"
type: task
status: backlog
priority: medium
labels: []
created: "{{DATE}}"
updated: "{{DATE}}"
assignee: null
---

# {{TITLE}}

## Context
<!-- Why this work is needed -->

## Current State
<!-- How things work now -->

## Desired State
<!-- How things should work after -->

## Acceptance Criteria
- [ ] <!-- Condition 1 -->
- [ ] <!-- Condition 2 -->

## Technical Notes
<!-- Relevant files, dependencies, constraints -->
```

### Improvement Template (`.issues/templates/improvement.md`)

```markdown
---
id: "{{ID}}"
title: "{{TITLE}}"
type: improvement
status: backlog
priority: medium
labels: []
created: "{{DATE}}"
updated: "{{DATE}}"
assignee: null
---

# {{TITLE}}

## Context
<!-- Why this improvement matters -->

## Current Implementation
<!-- How it works now -->

## Proposed Improvement
<!-- What should change and why -->

## Acceptance Criteria
- [ ] <!-- Measurable outcome 1 -->
- [ ] <!-- Measurable outcome 2 -->

## Technical Notes
<!-- Files to modify, risks, dependencies -->
```

---

## Step 5: Add to .gitignore (Optional)

Ask user:
```
Should completed/archived issues be git-ignored?
- Yes - Only track active issues in git
- No - Track all issues in git (recommended for audit trail)
```

If yes, add to `.gitignore`:
```
.issues/done/
.issues/archived/
```

---

## Step 6: Create README

Write `.issues/README.md`:

```markdown
# Local Issue Tracker

This project uses a markdown-based issue tracking system.

## Quick Reference

| Status | Folder | Description |
|--------|--------|-------------|
| Backlog | `backlog/` | New issues awaiting work |
| In Progress | `in-progress/` | Currently being worked on |
| In Review | `in-review/` | PR submitted, awaiting review |
| Done | `done/` | Completed issues |
| Archived | `archived/` | Old issues for reference |

## Commands

```bash
# Create a new issue
/issue-toolkit:create-issue

# Solve an issue
/issue-toolkit:solve-issue [PREFIX]-001

# List issues
/issue-toolkit:list-issues
```

## Issue Format

Issues are markdown files with YAML frontmatter.
```

---

## Step 7: Confirmation

Output:

```markdown
## Local Issue Tracker Initialized

**Prefix:** [PREFIX]
**Location:** .issues/

**Structure created:**
- .issues/config.json
- .issues/templates/ (4 templates)
- .issues/backlog/
- .issues/in-progress/
- .issues/in-review/
- .issues/done/
- .issues/archived/

**Next steps:**
1. Create your first issue: `/issue-toolkit:create-issue`
2. Or solve an existing issue: `/issue-toolkit:solve-issue [PREFIX]-001`

**Tip:** Commit the .issues/ folder to track issues in git.
```
