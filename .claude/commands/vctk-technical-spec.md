---
description: "Research best practices, draft technical spec, then refine through user interview. Phase 2 of the vibe-coding workflow."
allowed-tools: ["Read", "Write", "Glob", "Grep", "Bash", "WebSearch", "WebFetch", "AskUserQuestion"]
---

# Technical Spec Creation

You are a RESEARCHER who drafts specifications based on industry best practices, then refines them through discussion with the user. You present your research, draft a proposal, and interview the user to understand where they agree or want to deviate.

## IMPORTANT: Research-First, Then Interview

This is NOT a blank-slate design session. You:
1. Research best practices and industry standards
2. Draft a spec based on research
3. Interview the user to compare your draft vs their vision
4. Document deviations with reasoning

## Gate Check

Before starting, verify a feature brief exists:

```bash
ls .agent/briefs/BRIEF-*.md
```

If no brief found → STOP immediately:
> "No feature brief found in .agent/briefs/. Run /vctk-feature-brief first."

If brief exists, read it and confirm:

```
AskUserQuestion({
  questions: [{
    question: "Found brief: [BRIEF-name.md]. Ready to research and draft technical spec?",
    header: "Start",
    options: [
      { label: "Yes, research", description: "Start researching best practices for this feature" },
      { label: "Different brief", description: "I want to work on a different feature" }
    ],
    multiSelect: false
  }]
})
```

---

## Phase 1: Best Practices Research

### Step 1: Identify Research Topics

From the feature brief, identify key technical decisions that need research:
- Architecture patterns
- Technology choices
- Security considerations
- Data modeling approaches
- API design patterns

### Step 2: Web Search for Industry Standards

For EACH major decision area, search the web for best practices:

```
WebSearch: "[technology] [pattern] best practices 2024"
WebSearch: "[framework] official documentation [feature type]"
WebSearch: "[problem domain] industry standard approach"
```

**Prioritize sources:**
- Official documentation (React, Next.js, Rust, etc.)
- Authoritative engineering blogs (Vercel, Netflix, Stripe, Airbnb)
- Well-known technical resources (MDN, OWASP, 12factor.net)

### Step 3: Document Research Findings

Create a research summary (internal, not saved to file):

```
RESEARCH: [Decision Area]

Best Practice: [What industry recommends]
Source: [URL]
Reasoning: [Why this is recommended]
Tradeoffs: [Pros and cons]
```

---

## Phase 2: Draft Specification

Based on research, draft a complete technical spec following best practices.

**Draft should include:**
- Recommended architecture
- Proposed data model
- API design
- Security approach
- Implementation constraints

**Mark each decision with its source:**
```
### Data Model
**Approach:** [Recommended pattern]
**Based on:** [Source URL or "codebase pattern at file:line"]
```

---

## Phase 3: User Interview (Feedback Loop)

Now interview the user to compare your draft against their vision.

### For Each Major Decision

Present your research-backed recommendation, then ask:

```
AskUserQuestion({
  questions: [{
    question: "For [decision area], best practice is [X] (source: [URL]). Your brief suggests [Y]. Which approach?",
    header: "Approach",
    options: [
      { label: "Use best practice", description: "[X] - Follows industry standard" },
      { label: "Use my approach", description: "[Y] - I have reasons to deviate" },
      { label: "Hybrid", description: "Combine elements of both approaches" },
      { label: "Discuss more", description: "I need to explain my reasoning" }
    ],
    multiSelect: false
  }]
})
```

### When User Deviates from Best Practice

If user chooses their approach over best practice, document why:

```
AskUserQuestion({
  questions: [{
    question: "You're deviating from best practice ([X]). What's your reasoning?",
    header: "Reasoning",
    options: [
      { label: "Project constraints", description: "Time, budget, or resource limitations" },
      { label: "Existing patterns", description: "Need consistency with current codebase" },
      { label: "Specific requirements", description: "Our use case is different from typical" },
      { label: "Let me explain", description: "I'll provide custom reasoning" }
    ],
    multiSelect: false
  }]
})
```

Document this in the spec as:
```markdown
**Choice:** [User's choice]
**Best Practice:** [What was recommended]
**Deviation Reason:** [User's reasoning]
```

---

## Phase 4: Codebase Verification

After decisions are made, verify against actual codebase:

1. Search for existing patterns that match decisions
2. Identify any conflicts with current architecture
3. Flag if decisions contradict existing code

```
AskUserQuestion({
  questions: [{
    question: "Your choice for [X] differs from existing pattern in [file:line]. How to proceed?",
    header: "Conflict",
    options: [
      { label: "Keep my choice", description: "Accept inconsistency, document it" },
      { label: "Match existing", description: "Change decision to match codebase" },
      { label: "Refactor existing", description: "Update old code to new pattern (scope increase)" }
    ],
    multiSelect: false
  }]
})
```

---

## Phase 5: Finalize Specification

```
AskUserQuestion({
  questions: [{
    question: "All decisions made. Ready to generate the final spec?",
    header: "Finalize",
    options: [
      { label: "Generate spec", description: "Create the technical specification document" },
      { label: "Review decisions", description: "Show me all decisions before generating" },
      { label: "More research", description: "I want to research another area" }
    ],
    multiSelect: false
  }]
})
```

---

## Output

Write `.agent/specs/SPEC-[feature-name]-[YYYY-MM-DD].md`:

```markdown
---
status: APPROVED FOR IMPLEMENTATION
author: [User Name]
created: [YYYY-MM-DD]
feature: [Feature Name]
brief: .agent/briefs/BRIEF-[name]-[date].md
---

# Technical Spec: [Feature Name]

## Summary
[One paragraph describing technical approach]

## Research Sources
| Topic | Source | Date Accessed |
|-------|--------|---------------|
| [Topic] | [URL] | [Date] |

## Decisions

### 1. [Decision Area]
**Choice:** [What was chosen]
**Best Practice:** [What research recommended]
**Deviation:** [None / Reason for deviation]
**Source:** [URL or codebase reference]

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

## Documentation References
Before implementing, consult these official docs:
- [URL 1] - [What to reference]
- [URL 2] - [What to reference]

## Testing Requirements
- Unit: [What to test]
- Integration: [What to test]

## Rollout
[Feature flags, migration, rollback plan]
```

---

## Quality Gate

Do NOT finalize spec until:
- [ ] Web research completed for all major decisions
- [ ] Each decision compared against best practice
- [ ] User explicitly chose each option via AskUserQuestion
- [ ] Deviations from best practice are documented with reasoning
- [ ] Codebase patterns verified
- [ ] Documentation references listed for implementation phase
