---
description: "List issues from Linear or local system"
argument-hint: "[--status <status>] [--type <type>] [--assignee <name>] [--local|--linear]"
allowed-tools: ["Bash", "Read", "Glob", "Grep", "mcp__linear__list_issues", "mcp__linear__list_teams"]
---

# List Issues

**Arguments:** "$ARGUMENTS"

Lists issues from Linear or local markdown-based system with filtering options.

---

## Step 1: Parse Arguments

Extract filters:
- `--status <status>` - Filter by status (backlog, in-progress, in-review, done)
- `--type <type>` - Filter by type (bug, feature, task, improvement)
- `--assignee <name>` - Filter by assignee (or "me")
- `--priority <level>` - Filter by priority
- `--local` - Force local system
- `--linear` - Force Linear
- `--limit <n>` - Limit results (default: 20)

---

## Step 2: Detect System

Same detection as create-issue:
1. If `--linear` → Linear
2. If `--local` → Local
3. Auto-detect based on available systems
4. If both → Default to local for listing (faster, no API calls)

---

# List Linear Issues

## L1: Build Query

```
mcp__linear__list_issues(
  assignee: "<assignee or me>",
  state: "<status>",
  label: "<type>",
  limit: <n>,
  orderBy: "updatedAt"
)
```

## L2: Format Output

```markdown
## Linear Issues

| ID | Title | Type | Priority | Status | Assignee |
|----|-------|------|----------|--------|----------|
| ATF-52 | Fix calendar bug | Bug | High | In Progress | jack |
| ATF-51 | Add export feature | Feature | Medium | Backlog | - |

Total: 15 issues
```

---

# List Local Issues

## C1: Find Issue Files

```bash
# All issues
find .issues -name "*.md" -not -path "*templates*" -not -name "README.md"

# By status
ls .issues/backlog/*.md
ls .issues/in-progress/*.md
```

## C2: Parse Each Issue

For each `.md` file:
1. Read YAML frontmatter
2. Extract: id, title, type, priority, status, assignee
3. Apply filters

## C3: Apply Filters

```
if --status: filter where status == arg
if --type: filter where type == arg
if --assignee: filter where assignee == arg
if --priority: filter where priority == arg
```

## C4: Sort Results

Default sort: by status priority, then by ID

Status order:
1. in-progress (active work first)
2. in-review
3. backlog
4. done

## C5: Format Output

```markdown
## Local Issues (.issues/)

### In Progress (2)
| ID | Title | Type | Priority |
|----|-------|------|----------|
| ATH-003 | Fix calendar timezone bug | Bug | High |
| ATH-005 | Update auth middleware | Task | Medium |

### In Review (1)
| ID | Title | Type | Priority |
|----|-------|------|----------|
| ATH-002 | Add CSV export | Feature | Medium |

### Backlog (5)
| ID | Title | Type | Priority |
|----|-------|------|----------|
| ATH-006 | Improve error messages | Improvement | Low |
| ATH-007 | Add dark mode | Feature | Medium |
| ... | | | |

Total: 8 issues (2 in-progress, 1 in-review, 5 backlog)
```

---

# Filter Examples

## By Status

```bash
/list-issues --status in-progress
```

```markdown
## In Progress Issues

| ID | Title | Type | Priority |
|----|-------|------|----------|
| ATH-003 | Fix calendar timezone bug | Bug | High |
| ATH-005 | Update auth middleware | Task | Medium |

Total: 2 issues in progress
```

## By Type

```bash
/list-issues --type bug
```

```markdown
## Bug Issues

| ID | Title | Status | Priority |
|----|-------|--------|----------|
| ATH-003 | Fix calendar timezone bug | In Progress | High |
| ATH-008 | Login fails on Safari | Backlog | High |

Total: 2 bugs
```

## By Assignee

```bash
/list-issues --assignee jack
```

```markdown
## Issues Assigned to jack

| ID | Title | Type | Status |
|----|-------|------|--------|
| ATH-003 | Fix calendar bug | Bug | In Progress |
| ATH-007 | Add dark mode | Feature | Backlog |

Total: 2 issues assigned to jack
```

## Combined Filters

```bash
/list-issues --status backlog --type bug --priority high
```

```markdown
## High Priority Bugs in Backlog

| ID | Title |
|----|-------|
| ATH-008 | Login fails on Safari |

Total: 1 issue
```

---

# Quick Views

## My Issues

```bash
/list-issues --assignee me
```

## Active Work

```bash
/list-issues --status in-progress
```

## Ready for Review

```bash
/list-issues --status in-review
```

## High Priority Backlog

```bash
/list-issues --status backlog --priority high
```

---

# Output Options

## Compact View (Default)

Table format as shown above.

## Detailed View (`--detailed`)

```markdown
## ATH-003: Fix calendar timezone bug

**Type:** Bug | **Priority:** High | **Status:** In Progress
**Assignee:** jack | **Created:** 2024-01-15

### Problem
Calendar events display in UTC instead of user's timezone on Safari.

### Acceptance Criteria
- [ ] Events display in user's timezone on Safari
- [ ] Matches Chrome/Firefox behavior

---
```

## IDs Only (`--ids`)

```
ATH-003
ATH-005
ATH-002
```

Useful for scripting:
```bash
/list-issues --status backlog --ids | head -1 | xargs /solve-issue
```

---

# Notes

- Local listing is instant (file system)
- Linear listing requires API call
- Default limit is 20, use `--limit 50` for more
- Archived issues excluded by default (add `--include-archived` to include)
