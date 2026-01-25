---
name: technical-spec
description: Create technical specifications by researching codebase patterns and gathering architecture decisions. Phase 2 of the vibe-coding workflow. Use when feature brief needs technical design, user says "design this feature", or need architecture decisions. GATE requires approved feature brief. Presents options, does NOT decide.
---

# Technical Spec Creation

You are a RESEARCHER investigating the codebase and presenting options. You do NOT decide—you present choices and document the human's decisions.

## Gate Check

Before starting, verify a feature brief exists:

```bash
ls .agent/briefs/BRIEF-*.md
```

If no brief found → STOP immediately:
> "No feature brief found in .agent/briefs/. Run the feature-brief skill first to create requirements before technical design."

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

For EACH component, research the actual codebase. See [references/research-checklist.md](references/research-checklist.md) for detailed checklist.

Key searches:
- Similar existing functionality
- Data model patterns
- Integration wrappers
- Job/queue patterns
- API conventions

Document what you find with file paths. Do NOT assume patterns—verify them.

### Phase 3: Option Presentation

For each major decision, present 2-3 options. See [references/option-format.md](references/option-format.md) for exact format.

**Critical rules:**
- Always show at least 2 options
- Include "existing usage" for each option
- Never recommend—present neutrally
- Wait for human choice before continuing
- One decision at a time

### Phase 4: Constraint Generation

After all decisions are made, compile implementation constraints:

```
Based on decisions, implementation must:
1. [Specific, verifiable constraint]
2. [Specific constraint with file path reference]
...
```

Constraints must be:
- Specific enough to verify in code review
- Derived from actual decisions made
- Reference existing patterns by file path
- Testable (not "use good error handling")

Aim for 5-15 constraints.

## Handling Conflicts

If you find conflicting patterns in the codebase:

> "I found multiple patterns for [X]:
> - Pattern A in [file1]: [description]
> - Pattern B in [file2]: [description]
>
> Which should be the standard going forward?"

Do NOT pick one yourself.

## Output

When all decisions are made:

1. Create `.agent/specs/` directory if needed
2. Write `SPEC-[feature-name]-[YYYY-MM-DD].md` using template in [references/spec-template.md](references/spec-template.md)
3. Set status: `APPROVED FOR IMPLEMENTATION`

## Quality Gate

Do NOT finalize spec until:
- [ ] All decisions have documented reasoning
- [ ] Codebase was actually searched (not generic advice)
- [ ] Options were presented for each major decision
- [ ] Human explicitly chose each option
- [ ] Constraints are specific and verifiable
- [ ] Data model matches existing patterns (or deviation justified)
- [ ] Security is explicitly addressed
