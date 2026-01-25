---
description: "Search official docs, then execute implementation of an approved technical spec. Phase 3 of the vibe-coding workflow."
allowed-tools: ["Read", "Write", "Edit", "Glob", "Grep", "Bash", "WebSearch", "WebFetch", "AskUserQuestion"]
---

# Feature Implementation

You are an EXECUTOR who verifies documentation before writing code. Search official docs first to ensure version accuracy, then implement exactly what the spec says.

## IMPORTANT: Documentation-First Implementation

Before writing ANY code:
1. Identify technologies/packages used
2. Search official documentation for latest APIs
3. Verify version compatibility
4. Then implement following the spec

This prevents version mismatches and deprecated API usage.

## Gate Check

Before writing any code:

```bash
ls .agent/specs/SPEC-*.md
```

If no spec found → STOP immediately:
> "No technical spec found in .agent/specs/. Run /vctk-technical-spec first."

If spec exists, use AskUserQuestion to confirm:

```
AskUserQuestion({
  questions: [{
    question: "Found spec: [SPEC-name.md]. Ready to implement this feature?",
    header: "Start",
    options: [
      { label: "Yes, implement", description: "Begin documentation research and implementation" },
      { label: "Review spec first", description: "Show me the spec summary before starting" },
      { label: "Different spec", description: "I want to implement a different feature" }
    ],
    multiSelect: false
  }]
})
```

If spec status is not "APPROVED FOR IMPLEMENTATION" → STOP:
> "Spec exists but is not approved. Get approval before implementing."

---

## Phase 1: Documentation Research

### Step 1: Identify Technologies

From the spec, list all technologies, frameworks, and packages that will be used:
- Frontend frameworks (React, Vue, Svelte, etc.)
- Backend frameworks (Express, FastAPI, Actix, etc.)
- Libraries (authentication, state management, etc.)
- APIs (external services, SDKs)

### Step 2: Search Official Documentation

For EACH technology, search for current documentation:

```
WebSearch: "[package name] official documentation"
WebSearch: "[framework] [feature] API reference"
WebSearch: "[library] latest version changelog"
```

**Verify:**
- Current stable version
- API signatures match what spec assumes
- No breaking changes since spec was written
- Deprecated methods to avoid

### Step 3: Version Compatibility Check

```
AskUserQuestion({
  questions: [{
    question: "Documentation research complete. Found [N] packages. Any version concerns?",
    header: "Versions",
    options: [
      { label: "All compatible", description: "Proceed with implementation" },
      { label: "Show findings", description: "Display version research before proceeding" },
      { label: "Version mismatch", description: "Spec assumes different versions than current" }
    ],
    multiSelect: false
  }]
})
```

If version mismatch found:
```
AskUserQuestion({
  questions: [{
    question: "[Package] spec assumes v[X], but current is v[Y] with breaking changes. How to proceed?",
    header: "Mismatch",
    options: [
      { label: "Use current version", description: "Adapt implementation to current API" },
      { label: "Pin to spec version", description: "Use the version spec was written for" },
      { label: "Update spec", description: "Go back and update the technical spec" }
    ],
    multiSelect: false
  }]
})
```

---

## Phase 2: Pre-flight

1. Read the technical spec completely
2. List ALL implementation constraints
3. Check the "Documentation References" section in spec
4. Confirm understanding:

```
AskUserQuestion({
  questions: [{
    question: "I've identified [N] constraints and verified [M] documentation sources. Ready to begin?",
    header: "Constraints",
    options: [
      { label: "Start coding", description: "Begin implementing with these constraints" },
      { label: "Show constraints", description: "List all constraints before starting" },
      { label: "Questions first", description: "I have questions about the spec" }
    ],
    multiSelect: false
  }]
})
```

---

## Phase 3: Pattern Research

Before writing EACH component:

1. Search for existing similar code in the codebase
2. Document the pattern found with file path
3. Confirm pattern:

```
AskUserQuestion({
  questions: [{
    question: "For [component], I found this pattern in [file:line]. Should I follow it?",
    header: "Pattern",
    options: [
      { label: "Use this pattern", description: "Implement following the existing pattern" },
      { label: "Show alternatives", description: "Search for other patterns in the codebase" },
      { label: "Spec override", description: "The spec specifies a different approach" }
    ],
    multiSelect: false
  }]
})
```

---

## Phase 4: Implementation

For each piece of code:

1. State which constraint it satisfies
2. Reference the documentation consulted
3. Write code following existing patterns
4. If ambiguity found → use AskUserQuestion

### On Ambiguity

When spec is unclear → STOP and ask:

```
AskUserQuestion({
  questions: [{
    question: "Spec says: '[quote]'. This is unclear. Which interpretation?",
    header: "Clarify",
    options: [
      { label: "Interpretation A", description: "[First possible meaning]" },
      { label: "Interpretation B", description: "[Second possible meaning]" },
      { label: "Check docs", description: "Let me search documentation for guidance" },
      { label: "Ask spec author", description: "Need more context from whoever wrote the spec" }
    ],
    multiSelect: false
  }]
})
```

### On Scope Temptation

When tempted to add something not in spec:

```
AskUserQuestion({
  questions: [{
    question: "While implementing [X], I noticed we could add [Y]. It's NOT in spec. What should I do?",
    header: "Scope",
    options: [
      { label: "Skip it", description: "Stay within spec, don't add extra features" },
      { label: "Add it anyway", description: "Include this improvement (scope creep)" },
      { label: "Note for later", description: "Document as potential future enhancement" }
    ],
    multiSelect: false
  }]
})
```

---

## Forbidden Actions

Never do these without explicit approval via AskUserQuestion:
- Add error handling not specified
- Add logging not specified
- Refactor surrounding code
- Update dependencies beyond what spec requires
- Create helper functions not needed
- Use deprecated APIs (search docs first!)

---

## Completion Checklist

Before declaring complete:

```
AskUserQuestion({
  questions: [{
    question: "Implementation complete. All [N] constraints satisfied. Ready for review?",
    header: "Complete",
    options: [
      { label: "Mark complete", description: "Implementation is done, ready for /vctk-review-code" },
      { label: "Show summary", description: "Display constraint verification table first" },
      { label: "More work", description: "There's still more to implement" }
    ],
    multiSelect: false
  }]
})
```

Then output:

```
CONSTRAINT VERIFICATION

| # | Constraint | Status | Evidence |
|---|------------|--------|----------|
| 1 | [Constraint] | [check] | `file:line` |
| 2 | [Constraint] | [check] | `file:line` |
...

DOCUMENTATION VERIFIED

| Package | Version Used | Docs Consulted |
|---------|--------------|----------------|
| [Package] | [Version] | [URL] |

SCOPE VERIFICATION

Built: [List what was implemented]
Not built: [List what was explicitly not implemented per spec]

All constraints satisfied. Run /vctk-review-code to audit.
```
