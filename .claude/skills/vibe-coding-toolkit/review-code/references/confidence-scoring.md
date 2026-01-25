# Confidence Scoring Guide

Adapted from the official Claude Code review plugin. Each finding receives a score 0-100.

## Scoring Rubric

Score each issue using this scale (provide verbatim to scoring agents):

### 0 - Not Confident (False Positive)
- Issue doesn't stand up to light scrutiny
- Pre-existing issue, not from this implementation
- Misread the constraint or code
- Issue is explicitly handled elsewhere

### 25 - Somewhat Confident
- Might be real, might be false positive
- Couldn't verify it's actually a problem
- Stylistic issue not explicitly in spec constraints
- Ambiguous whether spec requires this

### 50 - Moderately Confident
- Verified it's a real issue
- Minor impact or rare edge case
- Not critical to core functionality
- Spec is vague on this point

### 75 - Highly Confident
- Double-checked and verified real issue
- Will likely be hit in practice
- Implementation doesn't satisfy constraint
- Important for functionality

### 100 - Absolutely Certain
- Definitely violates a specific constraint
- Evidence directly confirms violation
- Will break functionality or security
- Constraint explicitly requires X, code does Y

## Threshold

**Default threshold: 80**

Only issues scoring ≥80 appear in the final report.

## Scoring Process

For each potential issue:

1. **Identify the claim**: What exactly is wrong?
2. **Find evidence**: Where in the code? What constraint?
3. **Verify**: Does the code actually violate this?
4. **Consider alternatives**: Could this be intentional or handled elsewhere?
5. **Score**: Apply rubric honestly

## Examples

### Score 100 - Definite violation
```
Constraint: "Use BullMQ for job processing"
Code: Uses setTimeout for background task
Evidence: src/jobs/scorer.ts:15 - no BullMQ import or usage
Score: 100 - Constraint explicitly requires BullMQ, code doesn't use it
```

### Score 85 - High confidence
```
Constraint: "Store model version with each score"
Code: Score saved without model_version field
Evidence: src/jobs/scorer.ts:67 - save() call missing field
Score: 85 - Constraint requires field, code omits it
```

### Score 50 - Moderate (below threshold)
```
Constraint: "Handle errors appropriately"
Code: Generic catch block
Evidence: src/jobs/scorer.ts:45
Score: 50 - Vague constraint, code does have error handling
```

### Score 25 - Low (below threshold)
```
Observation: Could add retry logic
Code: No retry on API failure
Evidence: src/services/ai.ts:23
Score: 25 - Not in spec constraints, just best practice
```

### Score 0 - False positive
```
Initial concern: Missing validation
On inspection: Validation happens in middleware
Evidence: src/middleware/validate.ts:12
Score: 0 - Issue doesn't exist, handled elsewhere
```

## False Positives to Filter

Automatically score 0-25 for:
- Pre-existing issues not from this implementation
- Code that looks wrong but isn't
- General best practices not in spec constraints
- Issues linters/typecheckers catch
- Pedantic nitpicks
- Already handled elsewhere in codebase
