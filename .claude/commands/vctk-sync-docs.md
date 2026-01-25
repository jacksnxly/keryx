---
description: "Scan codebase and synchronize .agent documentation"
allowed-tools: ["Bash", "Read", "Write", "Glob", "Grep", "Task", "AskUserQuestion"]
---

# Sync Documentation

You are an expert code documentation specialist. Your goal is to do deep scan & analysis to provide accurate, up-to-date documentation of the codebase so any engineer can get full context.

## .agent Documentation Structure

```
.agent/
├── README.md           # Index of all documentation (entry point)
├── CONTEXT_INDEX.md    # Lightweight trigger table for /init-session
├── Tasks/              # PRD & implementation plans for features
├── System/             # Current state docs (architecture, schema, etc.)
├── SOP/                # Standard operating procedures (how-to guides)
├── briefs/             # Feature briefs from /vctk-feature-brief
├── specs/              # Technical specs from /vctk-technical-spec
└── sessions/           # Developer session history
```

---

## Mode Selection

Use AskUserQuestion to determine the operation:

```
AskUserQuestion({
  questions: [{
    question: "What documentation task do you want to perform?",
    header: "Doc Task",
    options: [
      { label: "Initialize", description: "First-time setup: scan codebase and create all docs" },
      { label: "Update", description: "Refresh existing docs with recent changes" },
      { label: "Add SOP", description: "Document a specific procedure or workflow" }
    ],
    multiSelect: false
  }]
})
```

---

## Mode: Initialize Documentation

For first-time setup or major restructuring:

### Step 1: Deep Codebase Scan

Thoroughly explore the codebase:

1. **Project structure** - Identify all major directories and their purposes
2. **Tech stack** - Languages, frameworks, databases, infrastructure
3. **Entry points** - Main files, API routes, CLI commands
4. **Integration points** - External services, APIs, third-party dependencies
5. **Database schema** - Tables, relationships, migrations

Use Glob, Grep, and Read tools extensively. If available, use Task tool with Explore agent for complex codebases.

### Step 2: Generate System Documentation

Create `.agent/System/project_architecture.md` with:

```markdown
# Project Architecture

## Overview
[Project goal and purpose]

## Tech Stack
| Layer | Technology |
|-------|------------|
| Frontend | ... |
| Backend | ... |
| Database | ... |
| Infrastructure | ... |

## Project Structure
[Directory tree with explanations]

## Integration Points
[External services and APIs]

## Key Flows
[Critical user journeys or data flows]
```

### Step 3: Create Database Schema (if applicable)

If database exists, create `.agent/System/database_schema.md`:

```markdown
# Database Schema

## Tables
[List tables with columns and relationships]

## Migrations
[How to run migrations]
```

### Step 4: Create README.md Index

Create `.agent/README.md`:

```markdown
# .agent Documentation Index

This folder contains all project documentation for engineers.

## Quick Start
- **New to project?** Start with `System/project_architecture.md`
- **Need to do X?** Check `SOP/` for how-to guides
- **Working on feature?** Check `Tasks/` for specs

## Documentation Map

| Folder | Purpose | Key Files |
|--------|---------|-----------|
| System/ | Architecture & state | `project_architecture.md` |
| SOP/ | How-to guides | ... |
| Tasks/ | Feature specs | ... |
| briefs/ | VCTK feature briefs | ... |
| specs/ | VCTK technical specs | ... |

## Related Documentation
[Links to external docs, wikis, etc.]
```

### Step 5: Create CONTEXT_INDEX.md

Create a lightweight trigger table for `/vctk-init-session` (under 80 lines):

```markdown
# Context Index

Quick reference for loading docs on-demand.

| When you need... | Read this |
|------------------|-----------|
| Project overview | `.agent/System/project_architecture.md` |
| Database schema | `.agent/System/database_schema.md` |
| Add API endpoint | `.agent/SOP/api_endpoints.md` |
| Run migrations | `.agent/SOP/database_migrations.md` |
| Feature specs | `.agent/Tasks/` |
```

---

## Mode: Update Documentation

For refreshing existing documentation:

### Step 1: Read Current State

```bash
ls -la .agent/
ls -la .agent/System/ 2>/dev/null
ls -la .agent/SOP/ 2>/dev/null
```

Read `.agent/README.md` to understand what exists.

### Step 2: Identify Changes

Use AskUserQuestion to clarify:

```
AskUserQuestion({
  questions: [{
    question: "What changed that needs documentation?",
    header: "Changes",
    options: [
      { label: "New feature", description: "Added new functionality" },
      { label: "Architecture", description: "Changed structure or tech stack" },
      { label: "Database", description: "Schema or migration changes" },
      { label: "Full refresh", description: "Re-scan everything" }
    ],
    multiSelect: true
  }]
})
```

### Step 3: Update Relevant Docs

Based on selection:
- Scan the changed areas
- Update the specific documentation files
- Keep other docs unchanged

### Step 4: Update Index Files

Always update:
- `.agent/README.md` - Ensure index is current
- `.agent/CONTEXT_INDEX.md` - Update if paths changed

---

## Mode: Add SOP

For documenting specific procedures:

### Step 1: Gather Information

Use AskUserQuestion:

```
AskUserQuestion({
  questions: [{
    question: "What procedure do you want to document?",
    header: "SOP Topic",
    options: [
      { label: "API endpoint", description: "How to add new API routes" },
      { label: "Database migration", description: "How to create/run migrations" },
      { label: "Testing", description: "How to write and run tests" },
      { label: "Deployment", description: "How to deploy the application" }
    ],
    multiSelect: false
  }]
})
```

### Step 2: Research the Procedure

Scan the codebase for existing examples of the procedure. Find:
- Existing files that follow the pattern
- Configuration files
- Test examples

### Step 3: Create SOP Document

Create `.agent/SOP/{topic}.md`:

```markdown
# How to: [Topic]

## Overview
[What this procedure accomplishes]

## Prerequisites
[Required setup or knowledge]

## Steps

### 1. [First step]
[Detailed instructions with code examples]

### 2. [Second step]
[...]

## Examples
[Reference existing code that demonstrates this]

## Common Issues
[Troubleshooting tips]

## Related Documentation
- [Link to related docs]
```

### Step 4: Update Index

Add the new SOP to:
- `.agent/README.md`
- `.agent/CONTEXT_INDEX.md`

---

## Rules

1. **DO** consolidate docs—avoid overlap between files
2. **DO** keep CONTEXT_INDEX.md under 80 lines (pointers only, not content)
3. **DO** include "Related Documentation" section in every doc
4. **DO** use tables and structured formats for scannability
5. **DO NOT** duplicate information across multiple files
6. **DO NOT** include full content in CONTEXT_INDEX.md (just paths)
7. **DO** update README.md index after any documentation changes
