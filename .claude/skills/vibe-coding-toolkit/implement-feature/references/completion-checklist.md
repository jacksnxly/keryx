# Completion Checklist

Use this format to verify implementation before declaring complete.

## Constraint Verification

For EACH constraint in the spec, document how it's satisfied:

```markdown
## Constraint Verification

| # | Constraint | Status | Evidence |
|---|------------|--------|----------|
| 1 | [Quote constraint] | ✅ | `file:line` - [brief description] |
| 2 | [Quote constraint] | ✅ | `file:line` - [brief description] |
| 3 | [Quote constraint] | ⚠️ | [Explanation of partial compliance] |
| 4 | [Quote constraint] | ❌ | [Why not satisfied, blocker] |

### Details

**Constraint 1:** [Full constraint text]
- Satisfied by: `src/jobs/scorer.ts:15-42`
- Implementation: [1-2 sentence description]

**Constraint 2:** [Full constraint text]
- Satisfied by: `src/models/score.ts:8`
- Implementation: [1-2 sentence description]

[Continue for all constraints...]
```

### Rules

- Every constraint must be listed
- Every ✅ must have a file:line reference
- Any ⚠️ or ❌ is a blocker—do not declare complete

---

## Test Verification

```markdown
## Test Verification

### Required by Spec
[Quote testing requirements from spec]

### Implemented

| Test Type | Location | Coverage |
|-----------|----------|----------|
| Unit | `src/__tests__/scorer.test.ts` | [What's tested] |
| Integration | `src/__tests__/scoring-flow.test.ts` | [What's tested] |

### Test Results

```
[Paste test output showing all pass]
```
```

---

## Scope Verification

```markdown
## Scope Verification

### Built (per spec)
- [Feature/component implemented]
- [Feature/component implemented]
- [Feature/component implemented]

### Not Built (per spec out-of-scope)
- [Feature explicitly excluded in spec]
- [Feature explicitly excluded in spec]

### Scope Notes Logged
- [Any SCOPE NOTE entries from implementation]
```

---

## PR Description Template

```markdown
## Summary

[1-2 sentences describing what was implemented]

## Links

- Feature Brief: `.agent/briefs/BRIEF-[name]-[date].md`
- Technical Spec: `.agent/specs/SPEC-[name]-[date].md`

## Constraint Verification

| # | Constraint | Evidence |
|---|------------|----------|
| 1 | [Constraint] | `file:line` |
| 2 | [Constraint] | `file:line` |
[...]

## Scope

**Built:**
- [List]

**Explicitly not built (per spec):**
- [List]

## Testing

- [ ] Unit tests passing
- [ ] Integration tests passing
- [ ] Manual QA completed per spec

## Rollout

- Feature flag: `[flag_name]`
- Rollout plan: [As specified]
```

---

## Final Checklist

Before declaring complete:

- [ ] All constraints verified with file:line references
- [ ] No ⚠️ or ❌ in constraint verification
- [ ] All required tests implemented
- [ ] All tests passing
- [ ] No features added beyond spec
- [ ] All SCOPE NOTEs logged (not implemented)
- [ ] PR description complete with links
- [ ] No ambiguities left unresolved
