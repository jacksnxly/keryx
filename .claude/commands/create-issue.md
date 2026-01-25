---
description: "Create a well-structured issue (auto-detects Linear or local system)"
argument-hint: "[--linear|--local] [--interactive] [--type bug|feature|task|improvement] [--from-conversation]"
allowed-tools: ["Bash", "Read", "Write", "Glob", "Grep", "AskUserQuestion", "mcp__linear__create_issue", "mcp__linear__list_teams", "mcp__linear__list_issue_labels", "mcp__linear__list_projects", "mcp__linear__list_issues"]
---

# Create Issue

**Arguments:** "$ARGUMENTS"

Creates a well-structured issue in either Linear or the local markdown-based system.

---

## Step 1: Detect Issue System

**Priority order:**

1. If `--linear` flag → Use Linear
2. If `--local` flag → Use local system
3. Auto-detect:
   - Check if `.issues/config.json` exists → Local system available
   - Check if Linear MCP tools respond → Linear available
   - If both available → Ask user which to use
   - If only one available → Use that one
   - If neither → Prompt to initialize local system

```
# Check for local system
Read .issues/config.json

# Check for Linear
Try mcp__linear__list_teams() - if it works, Linear is available
```

**If neither system exists:**
```
No issue tracking system found.

Would you like to:
1. Initialize local issue tracker (/init-issue-tracker)
2. Configure Linear MCP server
```

---

## Step 2: Route to Appropriate System

Based on detection, follow either:
- **Linear Path** → Continue to [Linear Issue Creation](#linear-issue-creation)
- **Local Path** → Continue to [Local Issue Creation](#local-issue-creation)

---

# Linear Issue Creation

## L1: Parse Arguments

Extract from "$ARGUMENTS":
- `--interactive` → Step-by-step guided creation
- `--from-conversation` → Extract from chat context
- `--type <type>` → Pre-set issue type

## L2: Gather Issue Information

### Mode A: From Conversation (`--from-conversation`)

Analyze conversation to extract:
1. **Problem Statement** - What's broken or needed?
2. **Proposed Solution** - What approach was discussed?
3. **Technical Details** - Files, functions, APIs mentioned
4. **Acceptance Criteria** - How do we verify it works?
5. **Issue Type** - Bug, feature, task, or improvement?

Present extracted info for confirmation.

### Mode B: Interactive (`--interactive`)

Use AskUserQuestion to gather:

1. **Issue Type** - Bug, Feature, Task, Improvement
2. **Title** - Must start with verb, be specific
3. **Context/Why** - Business justification
4. **Description** - Based on type (see templates below)
5. **Acceptance Criteria** - Testable conditions
6. **Technical Notes** - Relevant code, dependencies
7. **Metadata** - Team, project, priority, labels, assignee

## L3: Fetch Linear Metadata

```
mcp__linear__list_teams() → Get team options
mcp__linear__list_issue_labels(team: teamId) → Get labels
mcp__linear__list_projects(team: teamId) → Get projects
```

## L4: Format Description

Use templates based on type (see [Templates](#issue-templates) section).

## L5: Validate Quality

Check:
- [ ] Title starts with verb
- [ ] Title is specific (not "Fix bug")
- [ ] Description includes WHY
- [ ] Acceptance criteria are testable
- [ ] Scope is appropriate

Warn about anti-patterns.

## L6: Preview and Confirm

Show formatted issue, ask for confirmation.

## L7: Create in Linear

```
mcp__linear__create_issue(
  title: "...",
  team: "team-id",
  description: "...",
  labels: [...],
  project: "project-id",
  priority: 0-4,
  assignee: "user-id"
)
```

## L8: Output Result

```markdown
## Issue Created in Linear

**[TEAM-123]** Title here
https://linear.app/team/issue/TEAM-123

**Type:** Bug | **Priority:** High | **Team:** Engineering
```

---

# Local Issue Creation

## C1: Load Config

```
Read .issues/config.json
```

Extract:
- `prefix` - Issue ID prefix (e.g., "ATH")
- `nextId` - Next available ID number
- `labels` - Available labels

## C2: Parse Arguments

Same as Linear: `--interactive`, `--from-conversation`, `--type`

## C3: Gather Issue Information

### Mode A: From Conversation (`--from-conversation`)

Same extraction logic as Linear path.

### Mode B: Interactive (`--interactive`)

Use AskUserQuestion:

1. **Issue Type** - Bug, Feature, Task, Improvement
2. **Title** - Must start with verb, be specific
3. **Context/Why** - Business justification
4. **Description** - Based on type
5. **Acceptance Criteria** - Testable conditions
6. **Technical Notes** - Relevant code, dependencies
7. **Priority** - Urgent, High, Medium, Low, None
8. **Labels** - From available or create new
9. **Assignee** - Optional username

## C4: Generate Issue ID

```
ID = config.prefix + "-" + padStart(config.nextId, 3, "0")
Example: ATH-001, ATH-042
```

## C5: Format Issue Content

Read template from `.issues/templates/{type}.md`

Replace placeholders:
- `{{ID}}` → Generated ID
- `{{TITLE}}` → Issue title
- `{{DATE}}` → Current ISO date

Fill in content sections based on gathered info.

## C6: Validate Quality

Same checks as Linear:
- [ ] Title starts with verb
- [ ] Title is specific
- [ ] Description includes WHY
- [ ] Acceptance criteria are testable
- [ ] Scope is appropriate

## C7: Preview and Confirm

```markdown
## Preview: [ATH-001] Fix calendar timezone bug

**Type:** Bug | **Priority:** High | **Status:** Backlog

---

[Full issue content here]

---

Create this issue? (Yes / Edit / Cancel)
```

## C8: Write Issue File

```
Write to: .issues/backlog/{ID}.md
```

## C9: Update Config

Increment `nextId` in `.issues/config.json`:

```json
{
  "prefix": "ATH",
  "nextId": 2,  // Was 1, now 2
  ...
}
```

## C10: Output Result

```markdown
## Issue Created

**[ATH-001]** Fix calendar timezone bug
Location: `.issues/backlog/ATH-001.md`

**Type:** Bug | **Priority:** High | **Status:** Backlog

To start working: move to `.issues/in-progress/`
Or use: `/solve-issue ATH-001`
```

---

# Issue Templates

## Bug Template

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

## Feature Template

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
[What this does NOT include - prevents scope creep]

## Technical Notes
[Implementation hints, relevant code areas]
```

## Task/Improvement Template

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

# Quality Checks

## Anti-Pattern Detection

| Anti-Pattern | Detection | Suggestion |
|--------------|-----------|------------|
| Vague one-liner | Description < 50 chars | "Add more context" |
| Missing WHY | No context section | "Why does this matter?" |
| Giant multi-task | Multiple verbs, "and" | "Split into separate issues" |
| No acceptance criteria | AC empty | "How will we know it's done?" |
| Prescribed implementation | Code in description | "Describe WHAT, not HOW" |

## Title Validation

Good titles start with:
- **Fix** - Bug fixes
- **Add** - New features
- **Update** - Modifications
- **Implement** - New systems
- **Remove** - Deletions
- **Refactor** - Code improvements
- **Improve** - Enhancements
- **Migrate** - Data/system moves

Bad titles:
- "Bug in calendar" → "Fix calendar timezone display on Safari"
- "User feature" → "Add CSV export for analytics dashboard"
- "Update code" → "Update auth middleware to handle expired tokens"

---

# Quick Mode

For trivial issues:

```
/create-issue --quick "Fix typo in login button"
```

Creates minimal issue:
- Title as provided
- Type inferred (Fix → bug)
- No description
- Default priority
- Backlog status (local) or Triage (Linear)

---

# Examples

## From Conversation

**Conversation:**
> "The export button crashes when there are more than 1000 rows"

**Command:**
```
/create-issue --from-conversation --type bug
```

**Result:**
```markdown
[ATH-015] Fix export crash with large datasets

## Problem
Export functionality crashes when dataset exceeds 1000 rows.

## Current Behavior
Clicking "Export" with >1000 rows causes browser tab to freeze/crash.

## Expected Behavior
Export works regardless of dataset size, or shows appropriate error.

## Acceptance Criteria
- [ ] Export works with 5000+ rows
- [ ] Progress indicator shown for large exports
- [ ] Memory usage stays reasonable
```

## Interactive Feature

**Command:**
```
/create-issue --interactive --type feature
```

**Result after prompts:**
```markdown
[ATH-016] Add dark mode toggle to settings

## Context
Users have requested dark mode for extended use sessions.
> "I use the app late at night and the white background is harsh"

## Problem Statement
No dark mode option, causing eye strain for nighttime users.

## Proposed Solution
Add toggle in Settings > Appearance that switches between light/dark themes.

## Acceptance Criteria
Given user is in Settings
When they toggle "Dark Mode"
Then all UI elements switch to dark theme
And preference persists across sessions
```
