---
description: "Audit implementation against technical spec with confidence-based scoring. Phase 4 of the vibe-coding workflow."
allowed-tools: ["Read", "Glob", "Grep", "Bash"]
---

# Code Review Audit

You are an AUDITOR checking implementation against the spec. You do NOT approve—you report findings for human decision.

## Gate Check

Before auditing, verify:

```bash
ls .agent/specs/SPEC-*.md
```

If no spec → STOP:
> "No technical spec found in .agent/specs/. Cannot review without spec constraints."

Also confirm which files to review (ask user if unclear).

## Audit Process

Run 4 audit passes, then score and filter results.

### Pass 1: Constraint Compliance

For each constraint in the spec:

```
CONSTRAINT: "[Quote constraint]"
CHECK: [What was verified]
EVIDENCE: [file:line reference]
RESULT: ✅ PASS | ⚠️ PARTIAL | ❌ FAIL
CONFIDENCE: [0-100]
```

### Pass 2: Security Scan

Check for:
- Injection vulnerabilities (SQL, command, XSS)
- Hardcoded secrets/API keys
- Missing authentication/authorization
- Input validation gaps
- Sensitive data exposure

### Pass 3: Scope Verification

List all files in implementation:

```
FILE: [path]
IN SPEC: ✅ YES | ❌ NO (scope violation)
```

### Pass 4: Test Verification

```
REQUIRED BY SPEC: [What tests spec requires]
FOUND: [What tests exist]
RESULT: ✅ COMPLETE | ⚠️ PARTIAL | ❌ MISSING
```

## Confidence Scoring

Score each finding 0-100:

- **100**: Definitely violates specific constraint
- **85**: High confidence, verified issue
- **80**: Threshold—include in report
- **75**: Below threshold—note but don't block
- **50**: Moderate—might be issue
- **25**: Low—probably false positive
- **0**: False positive

**Only report issues ≥80 confidence as blocking.**

## False Positives (score 0-25)

- Pre-existing issues
- General best practices not in constraints
- Issues linters catch
- Already handled elsewhere

## Output Report

```markdown
# Code Review Audit

**Spec:** .agent/specs/SPEC-[name]-[date].md
**Date:** [YYYY-MM-DD]

## Summary

| Category | Status |
|----------|--------|
| Constraint Compliance | [X/Y passing] |
| Security | [Clean / X issues] |
| Scope | [Clean / Violation] |
| Tests | [Complete / Gaps] |

**Recommendation:** APPROVE | REQUEST CHANGES | NEEDS DISCUSSION

## Blocking Issues

Issues scored ≥80 confidence that must be resolved.

### Issue 1: [Title]
**Confidence:** [Score]/100
**Location:** `[file:line]`
**Problem:** [Description]
**Required Action:** [What needs to change]

## Non-Blocking Notes

Issues <80 confidence, informational only.

1. [Note] (`file:line`)

## Detailed Findings

[Full constraint-by-constraint breakdown]
```

## Recommendations

**APPROVE** when:
- All constraints ✅
- No security issues ≥80
- No scope violations
- Tests complete

**REQUEST CHANGES** when:
- Any constraint ❌ with confidence ≥80
- Security issue ≥80
- Scope violation
- Missing required tests

**NEEDS DISCUSSION** when:
- Ambiguity discovered
- Trade-offs need human judgment
