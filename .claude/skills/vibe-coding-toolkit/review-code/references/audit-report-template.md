# Audit Report Template

Use this format for the final review output.

```markdown
# Code Review Audit

**Spec:** .agent/specs/SPEC-[name]-[date].md
**Brief:** .agent/briefs/BRIEF-[name]-[date].md
**Reviewer:** AI Auditor
**Date:** [YYYY-MM-DD]

---

## Summary

| Category | Status |
|----------|--------|
| Constraint Compliance | [X/Y passing] |
| Security | [Clean / X issues] |
| Scope | [Clean / X violations] |
| Tests | [Complete / Gaps found] |

**Recommendation:** APPROVE | REQUEST CHANGES | NEEDS DISCUSSION

---

## Blocking Issues

Issues that must be resolved. All scored ≥80 confidence.

### Issue 1: [Title]

**Confidence:** [Score]/100
**Category:** [Constraint Violation / Security / Scope / Test Gap]
**Location:** `[file:line]`

**Problem:**
[Description of the issue]

**Evidence:**
[Quote from spec constraint or security rule]

**Required Action:**
[What needs to change]

---

### Issue 2: [Title]

[Same format...]

---

## Non-Blocking Notes

Issues scored <80 or informational. Not required to fix but worth noting.

1. **[Note title]** - [Brief description] (`file:line`)
2. **[Note title]** - [Brief description] (`file:line`)

---

## Detailed Findings

### Constraint Compliance

| # | Constraint | Status | Evidence |
|---|------------|--------|----------|
| 1 | [Constraint text] | ✅ PASS | `file:line` |
| 2 | [Constraint text] | ❌ FAIL (95) | `file:line` - [issue] |
| 3 | [Constraint text] | ⚠️ PARTIAL (75) | `file:line` - [note] |

### Security Scan

| Check | Status | Location |
|-------|--------|----------|
| Injection | ✅ PASS | - |
| Auth/AuthZ | ❌ FAIL (90) | `file:line` |
| Secrets | ✅ PASS | - |
| Input Validation | ✅ PASS | - |

### Scope Verification

**Files Modified:**
- `src/jobs/scorer.ts` - ✅ In spec
- `src/models/score.ts` - ✅ In spec
- `src/utils/slack.ts` - ❌ NOT in spec (scope violation)

**Scope Status:** [Clean / Violation found]

### Test Verification

**Required by Spec:**
- Unit tests for scorer
- Integration test for scoring flow

**Found:**
- ✅ `src/__tests__/scorer.test.ts`
- ❌ Missing integration test

---

## Recommendation

**APPROVE** - All constraints satisfied, no blocking issues.

OR

**REQUEST CHANGES** - [N] blocking issues must be resolved:
1. [Issue summary]
2. [Issue summary]

OR

**NEEDS DISCUSSION** - Findings require human judgment:
1. [Ambiguous finding]
2. [Trade-off to consider]

---

*Human reviewer: Please verify findings and make final decision.*
```

## Recommendation Criteria

### APPROVE
- All constraints verified ✅
- No security issues ≥80 confidence
- No scope violations
- Tests match spec requirements
- Zero blocking issues

### REQUEST CHANGES
- Any constraint violation ≥80 confidence
- Any security issue ≥80 confidence
- Scope violation (unauthorized files/features)
- Missing required tests

### NEEDS DISCUSSION
- Constraint ambiguity discovered
- Trade-offs that need human input
- Conflicting requirements
- Edge cases spec didn't address
