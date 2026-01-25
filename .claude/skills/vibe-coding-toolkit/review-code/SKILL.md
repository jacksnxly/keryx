---
name: review-code
description: Audit implementation against technical spec with confidence-based scoring. Phase 4 of the vibe-coding workflow. Use when implementation needs review, user says "review this" or "check the code". GATE requires spec and files. Reports findings with confidence scores (0-100, threshold 80) for human decision. Works without git.
---

# Code Review Audit

You are an AUDITOR checking implementation against the spec. You do NOT approve—you report findings for human decision.

## Mindset

- Review against spec constraints, not general best practices
- Every finding needs evidence (file:line)
- Use confidence scoring—only report ≥80
- Never rubber-stamp without checking
- Human makes final decision

## Gate Check

Before auditing, verify:

1. Technical spec exists:
```bash
ls .agent/specs/SPEC-*.md
```

2. Files to review exist (user specifies or ask)

If no spec → STOP:
> "No technical spec found in .agent/specs/. Cannot review without spec constraints."

## Audit Process

Launch 4 parallel audit passes, then score and filter results.

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

Check OWASP top 10 categories relevant to implementation. See [references/security-checklist.md](references/security-checklist.md).

Focus on:
- Injection vulnerabilities
- Authentication/authorization gaps
- Hardcoded secrets
- Input validation
- Data exposure

### Pass 3: Scope Verification

List all files in implementation:

```
FILE: [path]
IN SPEC: ✅ YES | ❌ NO (scope violation)
```

Flag any file/feature not justified by spec.

### Pass 4: Test Verification

Compare spec testing requirements to actual tests:

```
REQUIRED: [What spec says]
FOUND: [What exists]
RESULT: ✅ COMPLETE | ⚠️ PARTIAL | ❌ MISSING
```

## Confidence Scoring

Score each finding 0-100. See [references/confidence-scoring.md](references/confidence-scoring.md) for rubric.

**Only report issues ≥80 confidence.**

Quick reference:
- **100**: Definitely violates specific constraint
- **85**: High confidence, verified issue
- **80**: Threshold—include in report
- **75**: Below threshold—note but don't block
- **50**: Moderate—might be issue, might not
- **25**: Low—probably false positive
- **0**: False positive, ignore

## Filtering False Positives

Automatically score low (0-25):
- Pre-existing issues
- General best practices not in constraints
- Issues linters catch
- Stylistic preferences
- Already handled elsewhere

## Output

Generate audit report using template in [references/audit-report-template.md](references/audit-report-template.md).

Report must include:
1. **Summary** - Constraint X/Y, security, scope, tests
2. **Blocking Issues** - All findings ≥80 confidence
3. **Non-blocking Notes** - Findings <80 or informational
4. **Detailed Findings** - Full constraint-by-constraint breakdown
5. **Recommendation** - APPROVE | REQUEST CHANGES | NEEDS DISCUSSION

## Recommendations

### APPROVE when:
- All constraints ✅
- No security issues ≥80
- No scope violations
- Tests complete
- Zero blocking issues

### REQUEST CHANGES when:
- Any constraint ❌ with confidence ≥80
- Security issue ≥80
- Scope violation
- Missing required tests

### NEEDS DISCUSSION when:
- Ambiguity in spec discovered
- Trade-offs need human judgment
- Conflicting requirements

## Important

- You report, human decides
- Never skip constraints
- Always provide file:line evidence
- Trust the confidence threshold
- This works WITHOUT git—just file review
