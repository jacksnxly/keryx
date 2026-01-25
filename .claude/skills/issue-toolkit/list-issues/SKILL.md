---
name: list-issues
description: List and filter issues from Linear or local markdown system. Use when user wants to show issues, view backlog, see issues in progress, or check their issues.
---

# List Issues

Lists issues from Linear or local markdown-based system with filtering options.

## Usage

```
/issue-toolkit:list-issues [options]
```

**Options:**
- `--status <status>` - Filter: backlog, in-progress, in-review, done
- `--type <type>` - Filter: bug, feature, task, improvement
- `--assignee <name>` - Filter by assignee (or "me")
- `--priority <level>` - Filter: urgent, high, medium, low
- `--local` - Force local system
- `--linear` - Force Linear
- `--limit <n>` - Limit results (default: 20)

**Examples:**
```
/issue-toolkit:list-issues --status in-progress
/issue-toolkit:list-issues --type bug --priority high
/issue-toolkit:list-issues --assignee me
```

---

## Step 1: Detect System

1. If `--linear` → Linear
2. If `--local` → Local
3. Auto-detect based on available systems
4. If both → Default to local (faster, no API calls)

---

## Step 2: Fetch Issues

### For Linear

```
mcp__linear__list_issues(
  assignee: "<assignee or me>",
  state: "<status>",
  label: "<type>",
  limit: <n>,
  orderBy: "updatedAt"
)
```

### For Local

```bash
# Find all issue files
find .issues -name "*.md" -not -path "*templates*" -not -name "README.md"
```

For each file:
1. Read YAML frontmatter
2. Extract: id, title, type, priority, status, assignee
3. Apply filters

---

## Step 3: Apply Filters

```
if --status: filter where status == arg
if --type: filter where type == arg
if --assignee: filter where assignee == arg
if --priority: filter where priority == arg
```

---

## Step 4: Sort Results

Default sort: by status priority, then by ID

Status order:
1. in-progress (active work first)
2. in-review
3. backlog
4. done

---

## Step 5: Format Output

### Table View (Default)

```markdown
## Issues

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

Total: 8 issues
```

### Filtered View

```markdown
## High Priority Bugs

| ID | Title | Status |
|----|-------|--------|
| ATH-003 | Fix calendar timezone bug | In Progress |
| ATH-008 | Login fails on Safari | Backlog |

Total: 2 issues matching filters
```

---

## Quick Views

### My Issues
```
/issue-toolkit:list-issues --assignee me
```

### Active Work
```
/issue-toolkit:list-issues --status in-progress
```

### Ready for Review
```
/issue-toolkit:list-issues --status in-review
```

### High Priority Backlog
```
/issue-toolkit:list-issues --status backlog --priority high
```

### All Bugs
```
/issue-toolkit:list-issues --type bug
```

---

## Notes

- Local listing is instant (file system read)
- Linear listing requires API call
- Default limit is 20, use `--limit 50` for more
- Archived issues excluded by default
