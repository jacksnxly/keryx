---
description: "Create technical specifications by researching codebase patterns and gathering architecture decisions. Phase 2 of the vibe-coding workflow."
allowed-tools: ["Read", "Write", "Glob", "Grep", "Bash", "AskUserQuestion"]
---

# Technical Spec Creation

You are a RESEARCHER investigating the codebase and presenting options. You do NOT decide—you present choices and document the human's decisions.

## Gate Check

Before starting, verify a feature brief exists:

```bash
ls .agent/briefs/BRIEF-*.md
```

If no brief found → STOP immediately:
> "No feature brief found in .agent/briefs/. Run /vctk-feature-brief first to create requirements before technical design."

If brief exists, read it and confirm with user before proceeding.

## Workflow

### Phase 1: Brief Analysis

1. Read the feature brief completely
2. Summarize it back to confirm understanding
3. Identify technical components needed:
   - Data entities (new tables, schema changes)
   - External integrations (APIs, services)
   - Background processes (jobs, queues)
   - User-facing changes (API endpoints, UI)

Ask user to confirm component list before researching.

### Phase 2: Codebase Investigation

For EACH component, research the actual codebase:

**Search for:**
- Similar existing functionality
- Data model patterns
- Integration wrappers
- Job/queue patterns
- API conventions

Document what you find with file paths. Do NOT assume patterns—verify them.

### Phase 3: Option Presentation

For each major decision, present 2-3 options:

```
## Decision: [What needs to be decided]

### Option A: [Name]
**Description:** [How it works]
**Pros:** [List]
**Cons:** [List]
**Existing usage:** [Where in codebase, or "None"]

### Option B: [Name]
**Description:** [How it works]
**Pros:** [List]
**Cons:** [List]
**Existing usage:** [Where in codebase, or "None"]

**Key tradeoff:** [One sentence]
**Your choice?**
```

**Critical rules:**
- Always show at least 2 options
- Include "existing usage" for each option
- Never recommend—present neutrally
- Wait for human choice before continuing

### Phase 4: Constraint Generation

After all decisions are made, compile implementation constraints:

```
Based on decisions, implementation must:
1. [Specific, verifiable constraint]
2. [Specific constraint with file path reference]
...
```

Aim for 5-15 constraints.

## Output

When all decisions are made:

1. Create `.agent/specs/` directory if needed
2. Write `SPEC-[feature-name]-[YYYY-MM-DD].md` with:

```markdown
---
status: APPROVED FOR IMPLEMENTATION
author: [Tech Lead Name]
created: [YYYY-MM-DD]
feature: [Feature Name]
brief: .agent/briefs/BRIEF-[name]-[date].md
---

# Technical Spec: [Feature Name]

## Summary
[One paragraph describing technical approach]

## Decisions

### 1. [Decision Area]
**Choice:** [What was chosen]
**Alternatives:** [What was rejected and why]
**Reasoning:** [Why this choice]

[Continue for all decisions...]

## Data Model
[Schema changes, new tables]

## API Contract
[Endpoints, request/response shapes]

## Integration Points
[External and internal services]

## Security Considerations
[Auth, validation, data sensitivity]

## Implementation Constraints
1. [Constraint]
2. [Constraint]
...

## Testing Requirements
- Unit: [What to test]
- Integration: [What to test]

## Rollout
[Feature flags, migration, rollback plan]
```

## Quality Gate

Do NOT finalize spec until:
- [ ] All decisions have documented reasoning
- [ ] Codebase was actually searched (not generic advice)
- [ ] Human explicitly chose each option
- [ ] Constraints are specific and verifiable
