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
/create-issue --local

# Solve an issue
/solve-issue KRX-001

# List issues
/list-issues [--status backlog]
```

## Issue Format

Issues are markdown files with YAML frontmatter:

```yaml
---
id: "KRX-001"
title: "Issue title"
type: bug|feature|task|improvement
status: backlog|in-progress|in-review|done
priority: urgent|high|medium|low|none
labels: [label1, label2]
created: "2024-01-15"
updated: "2024-01-15"
assignee: username
---
```

## File Naming

Issues are named: `[ID].md` (e.g., `KRX-001.md`)

The file lives in the folder matching its status.
